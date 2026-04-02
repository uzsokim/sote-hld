#!/usr/bin/env python3
"""
Cisco Catalyst Center device inventory dashboard generator.

The script:
1. Authenticates to Cisco Catalyst Center
2. Downloads network device inventory and related details
3. Saves the raw export to JSON
4. Builds a polished HTML dashboard for browsing the devices

Credentials:
- Host: 10.8.11.100
- Username: admin
- Password: prompted securely at runtime
"""

from __future__ import annotations

import json
import math
import sys
import urllib3
from collections import Counter
from datetime import datetime
from getpass import getpass
from html import escape
from pathlib import Path
from typing import Any

import requests


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CC_HOST = "10.8.11.100"
CC_USERNAME = "admin"
BASE_URL = f"https://{CC_HOST}"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 500


class CatalystCenterClient:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.base_url = f"https://{host}"
        self.session = requests.Session()
        self.session.verify = False
        self.token: str | None = None

    def authenticate(self) -> str:
        url = f"{self.base_url}/dna/system/api/v1/auth/token"
        response = self.session.post(
            url,
            auth=(self.username, self.password),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        payload = response.json()
        token = payload.get("Token") or payload.get("token")
        if not token:
            raise RuntimeError("Authentication succeeded but no token was returned.")

        self.token = token
        self.session.headers.update(
            {
                "X-Auth-Token": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        return token

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def get_paginated_response(self, path: str, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 1

        while True:
            data = self.get(path, params={"offset": offset, "limit": page_size})
            response = data.get("response", data)
            if not isinstance(response, list):
                if isinstance(response, dict):
                    items.append(response)
                break

            if not response:
                break

            items.extend(response)

            if len(response) < page_size:
                break

            offset += page_size

        return items

    def get_network_devices(self) -> list[dict[str, Any]]:
        return self.get_paginated_response("/dna/intent/api/v1/network-device")

    def get_device_detail(self, device_id: str) -> dict[str, Any]:
        data = self.get(f"/dna/intent/api/v1/network-device/{device_id}")
        response = data.get("response", data)
        return response if isinstance(response, dict) else {}

    def get_device_interfaces(self, device_id: str) -> list[dict[str, Any]]:
        data = self.get(f"/dna/intent/api/v1/interface/network-device/{device_id}")
        response = data.get("response", data)
        return response if isinstance(response, list) else []

    def get_device_modules(self, device_id: str) -> list[dict[str, Any]]:
        data = self.get("/dna/intent/api/v1/network-device/module", params={"deviceId": device_id})
        response = data.get("response", data)
        return response if isinstance(response, list) else []

    def collect_inventory(self) -> dict[str, Any]:
        devices = self.get_network_devices()
        enriched_devices: list[dict[str, Any]] = []
        warnings: list[str] = []

        for index, device in enumerate(devices, start=1):
            device_id = str(device.get("id") or "")
            hostname = device.get("hostname") or device.get("managementIpAddress") or f"device-{index}"
            print(f"[{index}/{len(devices)}] Collecting {hostname}")

            detail: dict[str, Any] = {}
            interfaces: list[dict[str, Any]] = []
            modules: list[dict[str, Any]] = []

            if device_id:
                try:
                    detail = self.get_device_detail(device_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Device detail failed for {hostname}: {exc}")

                try:
                    interfaces = self.get_device_interfaces(device_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Interface query failed for {hostname}: {exc}")

                try:
                    modules = self.get_device_modules(device_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Module query failed for {hostname}: {exc}")

            enriched_devices.append(
                {
                    "summary": device,
                    "detail": detail,
                    "interfaces": interfaces,
                    "modules": modules,
                }
            )

        return {
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "catalyst_center_host": self.host,
                "username": self.username,
                "device_count": len(enriched_devices),
                "warnings": warnings,
            },
            "devices": enriched_devices,
        }


def value_from_paths(source: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = source
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current and current[part] not in ("", None):
                current = current[part]
            else:
                found = False
                break
        if found:
            return current
    return None


def stringify(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.2f}"
        return str(value)
    if isinstance(value, list):
        if not value:
            return "N/A"
        return ", ".join(stringify(item) for item in value[:8])
    if isinstance(value, dict):
        compact = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return compact if len(compact) <= 120 else compact[:117] + "..."
    return str(value)


def normalize_device(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("summary", {})
    detail = record.get("detail", {})
    interfaces = record.get("interfaces", [])
    modules = record.get("modules", [])

    merged = {**summary, **detail}

    software = value_from_paths(
        merged,
        "softwareVersion",
        "version",
        "platformId",
        "deviceSupportLevel",
    )
    reachability = value_from_paths(
        merged,
        "reachabilityStatus",
        "errorCode",
        "collectionStatus",
    )
    health = value_from_paths(merged, "overallHealth", "healthScore")
    uptime = value_from_paths(merged, "upTime", "uptimeSeconds")
    serial_numbers = value_from_paths(merged, "serialNumber", "serialNumbers")
    role = value_from_paths(merged, "role", "deviceRole")

    return {
        "id": stringify(value_from_paths(merged, "id")),
        "hostname": stringify(value_from_paths(merged, "hostname", "instanceUuid", "managementIpAddress")),
        "management_ip": stringify(value_from_paths(merged, "managementIpAddress")),
        "mac_address": stringify(value_from_paths(merged, "macAddress")),
        "platform": stringify(value_from_paths(merged, "platformId", "series")),
        "role": stringify(role),
        "family": stringify(value_from_paths(merged, "family", "type")),
        "type": stringify(value_from_paths(merged, "type")),
        "software_version": stringify(software),
        "serial_number": stringify(serial_numbers),
        "reachability": stringify(reachability),
        "health": stringify(health),
        "location": stringify(value_from_paths(merged, "location", "locationName")),
        "site": stringify(value_from_paths(merged, "siteId", "siteHierarchy")),
        "last_updated": stringify(value_from_paths(merged, "lastUpdateTime", "lastUpdated")),
        "up_time": stringify(uptime),
        "interface_count": len(interfaces),
        "module_count": len(modules),
        "raw": merged,
        "interfaces": interfaces,
        "modules": modules,
    }


def build_summary_stats(devices: list[dict[str, Any]]) -> dict[str, Any]:
    role_counter = Counter(device["role"] for device in devices)
    family_counter = Counter(device["family"] for device in devices)
    reachability_counter = Counter(device["reachability"] for device in devices)

    return {
        "total_devices": len(devices),
        "total_interfaces": sum(device["interface_count"] for device in devices),
        "total_modules": sum(device["module_count"] for device in devices),
        "reachable_devices": sum(
            1
            for device in devices
            if "reachable" in device["reachability"].lower()
            or "managed" in device["reachability"].lower()
        ),
        "top_roles": role_counter.most_common(6),
        "top_families": family_counter.most_common(6),
        "top_reachability": reachability_counter.most_common(6),
    }


def render_badges(pairs: list[tuple[str, int]]) -> str:
    if not pairs:
        return '<span class="muted">No data</span>'
    return "".join(
        f'<span class="badge"><strong>{escape(name)}</strong><span>{count}</span></span>'
        for name, count in pairs
    )


def render_key_value_table(title: str, data: dict[str, Any]) -> str:
    rows = []
    for key, value in data.items():
        rows.append(
            "<tr>"
            f"<th>{escape(str(key))}</th>"
            f"<td>{escape(stringify(value))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel">'
        f"<h3>{escape(title)}</h3>"
        '<div class="table-wrap"><table class="kv-table">'
        + "".join(rows)
        + "</table></div></section>"
    )


def render_list_table(title: str, items: list[dict[str, Any]], columns: list[str]) -> str:
    if not items:
        return (
            '<section class="panel">'
            f"<h3>{escape(title)}</h3>"
            '<p class="muted">No data returned from the API for this section.</p>'
            "</section>"
        )

    header = "".join(f"<th>{escape(column)}</th>" for column in columns)
    rows = []
    for item in items:
        cells = "".join(f"<td>{escape(stringify(item.get(column)))}</td>" for column in columns)
        rows.append(f"<tr>{cells}</tr>")

    return (
        '<section class="panel">'
        f"<h3>{escape(title)}</h3>"
        '<div class="table-wrap"><table class="data-table">'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div></section>"
    )


def build_html_report(inventory: dict[str, Any], output_path: Path) -> None:
    devices = [normalize_device(record) for record in inventory.get("devices", [])]
    stats = build_summary_stats(devices)
    metadata = inventory.get("metadata", {})
    generated_at = stringify(metadata.get("generated_at"))

    device_cards: list[str] = []
    for device in devices:
        overview = {
            "Hostname": device["hostname"],
            "Management IP": device["management_ip"],
            "MAC address": device["mac_address"],
            "Role": device["role"],
            "Family": device["family"],
            "Type": device["type"],
            "Platform": device["platform"],
            "Software version": device["software_version"],
            "Serial number": device["serial_number"],
            "Reachability": device["reachability"],
            "Health": device["health"],
            "Location": device["location"],
            "Site": device["site"],
            "Last updated": device["last_updated"],
            "Uptime": device["up_time"],
            "Interfaces": device["interface_count"],
            "Modules": device["module_count"],
        }

        interface_columns = [
            "portName",
            "interfaceType",
            "status",
            "adminStatus",
            "speed",
            "vlanId",
            "ipAddress",
            "macAddress",
        ]
        module_columns = [
            "name",
            "partNumber",
            "serialNumber",
            "hardwareVersion",
            "softwareVersion",
        ]

        detail_blocks = [
            render_key_value_table("Overview", overview),
            render_list_table("Interfaces", device["interfaces"], interface_columns),
            render_list_table("Modules", device["modules"], module_columns),
            '<section class="panel">'
            "<h3>Raw JSON</h3>"
            f"<pre>{escape(json.dumps(device['raw'], indent=2, ensure_ascii=False))}</pre>"
            "</section>",
        ]

        search_blob = " ".join(
            [
                device["hostname"],
                device["management_ip"],
                device["role"],
                device["family"],
                device["type"],
                device["platform"],
                device["software_version"],
                device["serial_number"],
                device["reachability"],
                device["location"],
            ]
        ).lower()

        device_cards.append(
            '<article class="device-card" '
            f'data-search="{escape(search_blob)}" '
            f'data-role="{escape(device["role"].lower())}" '
            f'data-family="{escape(device["family"].lower())}" '
            f'data-reachability="{escape(device["reachability"].lower())}">'
            '<div class="device-header">'
            '<div>'
            f'<p class="eyebrow">{escape(device["role"])}</p>'
            f"<h2>{escape(device['hostname'])}</h2>"
            f'<p class="meta-line">{escape(device["management_ip"])} | {escape(device["platform"])}</p>'
            "</div>"
            f'<span class="status-pill">{escape(device["reachability"])}</span>'
            "</div>"
            '<div class="quick-grid">'
            f'<div><span>Family</span><strong>{escape(device["family"])}</strong></div>'
            f'<div><span>Type</span><strong>{escape(device["type"])}</strong></div>'
            f'<div><span>Software</span><strong>{escape(device["software_version"])}</strong></div>'
            f'<div><span>Serial</span><strong>{escape(device["serial_number"])}</strong></div>'
            f'<div><span>Interfaces</span><strong>{device["interface_count"]}</strong></div>'
            f'<div><span>Modules</span><strong>{device["module_count"]}</strong></div>'
            "</div>"
            "<details>"
            "<summary>Open full details</summary>"
            + "".join(detail_blocks)
            + "</details>"
            "</article>"
        )

    warning_blocks = ""
    warnings = metadata.get("warnings", [])
    if warnings:
        warning_items = "".join(f"<li>{escape(str(item))}</li>" for item in warnings)
        warning_blocks = (
            '<section class="warnings">'
            "<h2>Warnings</h2>"
            f"<ul>{warning_items}</ul>"
            "</section>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Catalyst Center Device Dashboard</title>
  <style>
    :root {{
      --bg: #f4efe8;
      --bg-accent: #e2d2bf;
      --surface: rgba(255, 252, 248, 0.86);
      --surface-strong: #fffaf5;
      --ink: #1f1b18;
      --muted: #665f57;
      --line: rgba(57, 43, 30, 0.12);
      --brand: #8c3b2f;
      --brand-strong: #6f2417;
      --ok: #2e6a4f;
      --shadow: 0 18px 50px rgba(69, 42, 18, 0.12);
      --radius: 22px;
      --mono: "Consolas", "Courier New", monospace;
      --sans: "Segoe UI", "Trebuchet MS", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(226, 210, 191, 0.85), transparent 30%),
        radial-gradient(circle at top right, rgba(140, 59, 47, 0.10), transparent 28%),
        linear-gradient(180deg, #fbf7f2 0%, var(--bg) 100%);
    }}
    .shell {{
      width: min(1400px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,250,245,0.96), rgba(249,238,226,0.92));
      border: 1px solid var(--line);
      border-radius: calc(var(--radius) + 6px);
      padding: 28px;
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -60px -60px auto;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(140,59,47,0.20), transparent 70%);
    }}
    .eyebrow {{
      margin: 0 0 8px;
      color: var(--brand);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.78rem;
      font-weight: 700;
    }}
    h1, h2, h3 {{
      margin: 0;
      line-height: 1.1;
    }}
    h1 {{
      font-size: clamp(2rem, 4vw, 3.6rem);
      max-width: 10ch;
    }}
    .hero p {{
      max-width: 70ch;
      color: var(--muted);
    }}
    .top-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .stat {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      backdrop-filter: blur(8px);
    }}
    .stat span {{
      display: block;
      color: var(--muted);
      font-size: 0.9rem;
      margin-bottom: 6px;
    }}
    .stat strong {{
      font-size: 1.9rem;
      color: var(--brand-strong);
    }}
    .band {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 22px 0;
    }}
    .panel {{
      background: var(--surface-strong);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(140, 59, 47, 0.08);
      color: var(--brand-strong);
      font-size: 0.92rem;
    }}
    .badge span {{
      background: rgba(140, 59, 47, 0.15);
      border-radius: 999px;
      padding: 2px 8px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin: 24px 0 16px;
    }}
    .toolbar input, .toolbar select {{
      appearance: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.8);
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 14px;
      min-width: 210px;
      font: inherit;
    }}
    .toolbar .count {{
      margin-left: auto;
      color: var(--muted);
      font-weight: 600;
    }}
    .device-list {{
      display: grid;
      gap: 18px;
    }}
    .device-card {{
      background: rgba(255,250,245,0.88);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow);
    }}
    .device-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
    }}
    .meta-line {{
      margin: 8px 0 0;
      color: var(--muted);
    }}
    .status-pill {{
      white-space: nowrap;
      border-radius: 999px;
      background: rgba(46,106,79,0.12);
      color: var(--ok);
      padding: 10px 14px;
      font-weight: 700;
      border: 1px solid rgba(46,106,79,0.15);
    }}
    .quick-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin: 18px 0 8px;
    }}
    .quick-grid div {{
      border-radius: 16px;
      padding: 12px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line);
    }}
    .quick-grid span {{
      display: block;
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    details {{
      margin-top: 10px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--brand-strong);
      padding: 8px 0;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid rgba(57, 43, 30, 0.10);
      padding: 10px 8px;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.88rem;
      font-weight: 700;
    }}
    pre {{
      margin: 12px 0 0;
      padding: 14px;
      border-radius: 16px;
      background: #201a16;
      color: #f7e9dc;
      overflow-x: auto;
      font-family: var(--mono);
      font-size: 0.86rem;
    }}
    .muted {{
      color: var(--muted);
    }}
    .warnings {{
      background: rgba(140, 59, 47, 0.08);
      border: 1px solid rgba(140, 59, 47, 0.14);
      border-radius: var(--radius);
      padding: 18px;
      margin: 20px 0;
    }}
    .warnings ul {{
      margin: 12px 0 0;
      padding-left: 18px;
    }}
    @media (max-width: 760px) {{
      .shell {{
        width: min(100% - 18px, 100%);
      }}
      .hero, .panel, .device-card {{
        border-radius: 18px;
        padding: 16px;
      }}
      .toolbar .count {{
        width: 100%;
        margin-left: 0;
      }}
      .device-header {{
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <p class="eyebrow">Cisco Catalyst Center Inventory</p>
      <h1>Network Device Dashboard</h1>
      <p>Detailed inventory report for Catalyst Center host {escape(CC_HOST)}. The page includes searchable device cards, interface and module tables, and the raw API payload for each device.</p>
      <div class="top-grid">
        <div class="stat"><span>Total devices</span><strong>{stats["total_devices"]}</strong></div>
        <div class="stat"><span>Reachable or managed</span><strong>{stats["reachable_devices"]}</strong></div>
        <div class="stat"><span>Total interfaces</span><strong>{stats["total_interfaces"]}</strong></div>
        <div class="stat"><span>Total modules</span><strong>{stats["total_modules"]}</strong></div>
      </div>
    </section>

    <section class="band">
      <section class="panel">
        <h2>Report metadata</h2>
        <p class="muted">Generated at {escape(generated_at)} against {escape(stringify(metadata.get("catalyst_center_host")))} with user {escape(stringify(metadata.get("username")))}.</p>
      </section>
      <section class="panel">
        <h2>Top roles</h2>
        <div class="badge-row">{render_badges(stats["top_roles"])}</div>
      </section>
      <section class="panel">
        <h2>Top families</h2>
        <div class="badge-row">{render_badges(stats["top_families"])}</div>
      </section>
      <section class="panel">
        <h2>Reachability mix</h2>
        <div class="badge-row">{render_badges(stats["top_reachability"])}</div>
      </section>
    </section>

    {warning_blocks}

    <section class="toolbar">
      <input id="searchBox" type="search" placeholder="Search hostname, IP, role, platform, serial...">
      <select id="roleFilter">
        <option value="">All roles</option>
      </select>
      <select id="familyFilter">
        <option value="">All families</option>
      </select>
      <select id="reachabilityFilter">
        <option value="">All reachability states</option>
      </select>
      <div class="count"><span id="visibleCount">{stats["total_devices"]}</span> visible devices</div>
    </section>

    <section id="deviceList" class="device-list">
      {''.join(device_cards)}
    </section>
  </main>

  <script>
    const cards = Array.from(document.querySelectorAll('.device-card'));
    const searchBox = document.getElementById('searchBox');
    const roleFilter = document.getElementById('roleFilter');
    const familyFilter = document.getElementById('familyFilter');
    const reachabilityFilter = document.getElementById('reachabilityFilter');
    const visibleCount = document.getElementById('visibleCount');

    function uniqueValues(attribute) {{
      const values = new Set();
      cards.forEach(card => {{
        const value = (card.dataset[attribute] || '').trim();
        if (value) values.add(value);
      }});
      return Array.from(values).sort();
    }}

    function fillSelect(select, values) {{
      values.forEach(value => {{
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
    }}

    fillSelect(roleFilter, uniqueValues('role'));
    fillSelect(familyFilter, uniqueValues('family'));
    fillSelect(reachabilityFilter, uniqueValues('reachability'));

    function applyFilters() {{
      const query = searchBox.value.trim().toLowerCase();
      const role = roleFilter.value;
      const family = familyFilter.value;
      const reachability = reachabilityFilter.value;
      let visible = 0;

      cards.forEach(card => {{
        const matchesQuery = !query || card.dataset.search.includes(query);
        const matchesRole = !role || card.dataset.role === role;
        const matchesFamily = !family || card.dataset.family === family;
        const matchesReachability = !reachability || card.dataset.reachability === reachability;
        const show = matchesQuery && matchesRole && matchesFamily && matchesReachability;
        card.style.display = show ? '' : 'none';
        if (show) visible += 1;
      }});

      visibleCount.textContent = visible;
    }}

    [searchBox, roleFilter, familyFilter, reachabilityFilter].forEach(element => {{
      element.addEventListener('input', applyFilters);
      element.addEventListener('change', applyFilters);
    }});
  </script>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")


def save_json_report(inventory: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    print("=" * 72)
    print(" Cisco Catalyst Center Device Dashboard Generator")
    print(f" Target: {CC_HOST} | User: {CC_USERNAME}")
    print("=" * 72)

    password = getpass("Catalyst Center password: ")
    if not password:
        print("Password is required.")
        return 1

    client = CatalystCenterClient(CC_HOST, CC_USERNAME, password)

    try:
        print("[*] Authenticating...")
        client.authenticate()
        print("[+] Authentication successful.")

        print("[*] Downloading inventory and device details...")
        inventory = client.collect_inventory()
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "unknown"
        body = response.text if response is not None else str(exc)
        print(f"[!] HTTP error during Catalyst Center query: {status}")
        print(body[:1000])
        return 2
    except requests.RequestException as exc:
        print(f"[!] Network error during Catalyst Center query: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Unexpected error: {exc}")
        return 4

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = Path(f"catalyst_center_devices_{timestamp}.json")
    html_path = Path(f"catalyst_center_devices_{timestamp}.html")

    save_json_report(inventory, json_path)
    build_html_report(inventory, html_path)

    print("[+] Export completed.")
    print(f"    JSON : {json_path.resolve()}")
    print(f"    HTML : {html_path.resolve()}")
    print("Open the HTML file in a browser for the visual dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
