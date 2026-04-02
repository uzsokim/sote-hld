#!/usr/bin/env python3
"""
Cisco ISE inventory dashboard generator.

The script:
1. Authenticates to Cisco ISE using ERS API
2. Downloads network devices and supporting inventory data
3. Saves a raw JSON export
4. Builds a polished HTML dashboard

Credentials:
- Host: 10.81.145.7
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

ISE_HOST = "10.81.145.7"
ISE_USERNAME = "admin"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100
ISE_PORT_CANDIDATES = (9060, 443)


class CiscoISEClient:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.base_url = f"https://{host}"
        self.active_port: int | None = None
        self.session = requests.Session()
        self.session.verify = False
        self.session.auth = (username, password)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    @staticmethod
    def _decode_json_response(response: requests.Response, path: str) -> Any:
        body = response.text.strip()
        if not body:
            return {}

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            snippet = body[:300].replace("\n", " ")
            raise RuntimeError(
                f"Non-JSON response from {path} "
                f"(status={response.status_code}, content-type={content_type}): {snippet}"
            ) from exc

    @staticmethod
    def _looks_like_login_page(response: requests.Response) -> bool:
        content_type = response.headers.get("Content-Type", "").lower()
        body = response.text[:500].lower()
        return "text/html" in content_type and ("<html" in body or "login" in body)

    def _set_active_port(self, port: int) -> None:
        self.active_port = port
        self.base_url = f"https://{self.host}:{port}"

    def probe(self) -> None:
        failures: list[str] = []

        for port in ISE_PORT_CANDIDATES:
            self._set_active_port(port)
            try:
                response = self.session.get(
                    f"{self.base_url}/ers/config/networkdevice",
                    params={"size": 1, "page": 1},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()

                if self._looks_like_login_page(response):
                    failures.append(
                        f"port {port}: HTML login page returned instead of ERS JSON"
                    )
                    continue

                self._decode_json_response(response, "/ers/config/networkdevice")
                return
            except Exception as exc:  # noqa: BLE001
                failures.append(f"port {port}: {exc}")

        failure_text = "; ".join(failures)
        raise RuntimeError(
            "Cisco ISE ERS API is not reachable in API mode. "
            "Checked ports 443 and 9060. "
            f"Details: {failure_text}"
        )

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return self._decode_json_response(response, path)

    def get_paginated_search_result(
        self,
        path: str,
        page_size: int = PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1

        while True:
            data = self.get(path, params={"size": page_size, "page": page})
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected response format from {path}: {type(data).__name__}")

            search_result = data.get("SearchResult", {})
            if not search_result and data:
                raise RuntimeError(
                    f"Missing SearchResult in {path} response. Keys: {', '.join(sorted(data.keys())[:12])}"
                )

            resources = search_result.get("resources", [])
            if not resources:
                break

            items.extend(resources)

            total = int(search_result.get("total", len(items)))
            if len(items) >= total or len(resources) < page_size:
                break

            page += 1

        return items

    def get_network_devices(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/networkdevice")

    def get_network_device_detail(self, device_id: str) -> dict[str, Any]:
        data = self.get(f"/ers/config/networkdevice/{device_id}")
        return data.get("NetworkDevice", {})

    def get_nodes(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/node")

    def get_node_detail(self, node_id: str) -> dict[str, Any]:
        data = self.get(f"/ers/config/node/{node_id}")
        return data.get("Node", {})

    def get_device_groups(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/networkdevicegroup")

    def get_device_group_detail(self, group_id: str) -> dict[str, Any]:
        data = self.get(f"/ers/config/networkdevicegroup/{group_id}")
        return data.get("NetworkDeviceGroup", {})

    def collect_inventory(self) -> dict[str, Any]:
        warnings: list[str] = []

        devices: list[dict[str, Any]] = []
        try:
            devices = self.get_network_devices()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Network device query failed: {exc}")

        enriched_devices: list[dict[str, Any]] = []
        for index, device in enumerate(devices, start=1):
            device_id = str(device.get("id") or "")
            name = device.get("name") or f"network-device-{index}"
            print(f"[{index}/{len(devices)}] Collecting {name}")

            detail: dict[str, Any] = {}
            if device_id:
                try:
                    detail = self.get_network_device_detail(device_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Network device detail failed for {name}: {exc}")

            enriched_devices.append({"summary": device, "detail": detail})

        nodes_summary: list[dict[str, Any]] = []
        enriched_nodes: list[dict[str, Any]] = []
        try:
            nodes_summary = self.get_nodes()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Node query failed: {exc}")

        for node in nodes_summary:
            node_id = str(node.get("id") or "")
            node_name = node.get("name") or node.get("fqdn") or node_id
            detail: dict[str, Any] = {}
            if node_id:
                try:
                    detail = self.get_node_detail(node_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Node detail failed for {node_name}: {exc}")
            enriched_nodes.append({"summary": node, "detail": detail})

        groups_summary: list[dict[str, Any]] = []
        enriched_groups: list[dict[str, Any]] = []
        try:
            groups_summary = self.get_device_groups()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Network device group query failed: {exc}")

        for group in groups_summary:
            group_id = str(group.get("id") or "")
            group_name = group.get("name") or group_id
            detail: dict[str, Any] = {}
            if group_id:
                try:
                    detail = self.get_device_group_detail(group_id)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Network device group detail failed for {group_name}: {exc}")
            enriched_groups.append({"summary": group, "detail": detail})

        return {
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "ise_host": self.host,
                "username": self.username,
                "device_count": len(enriched_devices),
                "node_count": len(enriched_nodes),
                "group_count": len(enriched_groups),
                "warnings": warnings,
            },
            "network_devices": enriched_devices,
            "nodes": enriched_nodes,
            "network_device_groups": enriched_groups,
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
        rendered = []
        for item in value[:10]:
            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("ipaddress")
                    or item.get("fqdn")
                    or item.get("value")
                    or json.dumps(item, ensure_ascii=False, sort_keys=True)
                )
                rendered.append(str(name))
            else:
                rendered.append(str(item))
        return ", ".join(rendered)
    if isinstance(value, dict):
        compact = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return compact if len(compact) <= 120 else compact[:117] + "..."
    return str(value)


def normalize_network_device(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("summary", {})
    detail = record.get("detail", {})
    merged = {**summary, **detail}

    auth_settings = detail.get("authenticationSettings", {}) if isinstance(detail, dict) else {}
    radius_settings = detail.get("radiusSettings", {}) if isinstance(detail, dict) else {}
    tacacs_settings = detail.get("tacacsSettings", {}) if isinstance(detail, dict) else {}
    snmp_settings = detail.get("snmpsettings", {}) if isinstance(detail, dict) else {}

    ips = detail.get("NetworkDeviceIPList", []) if isinstance(detail, dict) else []
    group_list = detail.get("NetworkDeviceGroupList", []) if isinstance(detail, dict) else []

    ip_blob = ", ".join(
        item.get("ipaddress", "")
        for item in ips
        if isinstance(item, dict) and item.get("ipaddress")
    )

    return {
        "id": stringify(value_from_paths(merged, "id")),
        "name": stringify(value_from_paths(merged, "name")),
        "description": stringify(value_from_paths(merged, "description")),
        "profile_name": stringify(value_from_paths(merged, "profileName")),
        "ip_addresses": stringify(ip_blob or ips),
        "mask": stringify(
            ", ".join(
                str(item.get("mask", ""))
                for item in ips
                if isinstance(item, dict) and item.get("mask")
            )
        ),
        "group_list": stringify(group_list),
        "model_name": stringify(value_from_paths(merged, "NetworkDeviceProfile.displayName")),
        "coa_port": stringify(value_from_paths(auth_settings, "coaPort")),
        "radius_enabled": stringify(value_from_paths(radius_settings, "networkProtocol")),
        "tacacs_enabled": stringify(value_from_paths(tacacs_settings, "sharedSecret")),
        "snmp_version": stringify(value_from_paths(snmp_settings, "version")),
        "raw": merged,
        "ips": ips,
    }


def normalize_node(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("summary", {})
    detail = record.get("detail", {})
    merged = {**summary, **detail}
    return {
        "name": stringify(value_from_paths(merged, "name")),
        "fqdn": stringify(value_from_paths(merged, "fqdn")),
        "ip_address": stringify(value_from_paths(merged, "ipAddress")),
        "roles": stringify(value_from_paths(merged, "roles")),
        "node_type": stringify(value_from_paths(merged, "nodeType")),
        "software_version": stringify(value_from_paths(merged, "softwareVersion")),
        "raw": merged,
    }


def normalize_group(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("summary", {})
    detail = record.get("detail", {})
    merged = {**summary, **detail}
    return {
        "name": stringify(value_from_paths(merged, "name")),
        "description": stringify(value_from_paths(merged, "description")),
        "other_name": stringify(value_from_paths(merged, "othername")),
        "raw": merged,
    }


def build_summary_stats(
    devices: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> dict[str, Any]:
    profile_counter = Counter(device["profile_name"] for device in devices)
    snmp_counter = Counter(device["snmp_version"] for device in devices)
    group_counter = Counter()
    for device in devices:
        for name in str(device["group_list"]).split(","):
            cleaned = name.strip()
            if cleaned and cleaned != "N/A":
                group_counter[cleaned] += 1

    node_role_counter = Counter(nodes_item["roles"] for nodes_item in nodes)

    return {
        "total_devices": len(devices),
        "total_nodes": len(nodes),
        "total_groups": len(groups),
        "top_profiles": profile_counter.most_common(6),
        "top_snmp_versions": snmp_counter.most_common(6),
        "top_device_groups": group_counter.most_common(6),
        "top_node_roles": node_role_counter.most_common(6),
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
    devices = [normalize_network_device(record) for record in inventory.get("network_devices", [])]
    nodes = [normalize_node(record) for record in inventory.get("nodes", [])]
    groups = [normalize_group(record) for record in inventory.get("network_device_groups", [])]
    stats = build_summary_stats(devices, nodes, groups)
    metadata = inventory.get("metadata", {})

    device_cards: list[str] = []
    for device in devices:
        overview = {
            "Name": device["name"],
            "Description": device["description"],
            "Profile": device["profile_name"],
            "IP addresses": device["ip_addresses"],
            "Mask": device["mask"],
            "Groups": device["group_list"],
            "Model/Profile display": device["model_name"],
            "CoA port": device["coa_port"],
            "RADIUS protocol": device["radius_enabled"],
            "TACACS configured": device["tacacs_enabled"],
            "SNMP version": device["snmp_version"],
        }

        ip_table = render_list_table(
            "IP assignments",
            device["ips"],
            ["ipaddress", "mask"],
        )

        search_blob = " ".join(
            [
                device["name"],
                device["description"],
                device["profile_name"],
                device["ip_addresses"],
                device["group_list"],
                device["snmp_version"],
            ]
        ).lower()

        device_cards.append(
            '<article class="device-card" '
            f'data-search="{escape(search_blob)}" '
            f'data-profile="{escape(device["profile_name"].lower())}" '
            f'data-snmp="{escape(device["snmp_version"].lower())}">'
            '<div class="device-header">'
            '<div>'
            '<p class="eyebrow">ISE Network Device</p>'
            f"<h2>{escape(device['name'])}</h2>"
            f'<p class="meta-line">{escape(device["ip_addresses"])} | {escape(device["profile_name"])}</p>'
            "</div>"
            f'<span class="status-pill">{escape(device["snmp_version"])}</span>'
            "</div>"
            '<div class="quick-grid">'
            f'<div><span>Groups</span><strong>{escape(device["group_list"])}</strong></div>'
            f'<div><span>CoA port</span><strong>{escape(device["coa_port"])}</strong></div>'
            f'<div><span>RADIUS</span><strong>{escape(device["radius_enabled"])}</strong></div>'
            f'<div><span>TACACS</span><strong>{escape(device["tacacs_enabled"])}</strong></div>'
            "</div>"
            "<details>"
            "<summary>Open full details</summary>"
            + render_key_value_table("Overview", overview)
            + ip_table
            + '<section class="panel"><h3>Raw JSON</h3>'
            + f"<pre>{escape(json.dumps(device['raw'], indent=2, ensure_ascii=False))}</pre></section>"
            + "</details>"
            "</article>"
        )

    node_rows = []
    for node in nodes:
        node_rows.append(
            {
                "name": node["name"],
                "fqdn": node["fqdn"],
                "ip_address": node["ip_address"],
                "roles": node["roles"],
                "node_type": node["node_type"],
                "software_version": node["software_version"],
            }
        )

    group_rows = []
    for group in groups:
        group_rows.append(
            {
                "name": group["name"],
                "description": group["description"],
                "other_name": group["other_name"],
            }
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
  <title>Cisco ISE Device Dashboard</title>
  <style>
    :root {{
      --bg: #eef3f5;
      --bg-accent: #d7e3e8;
      --surface: rgba(252, 254, 255, 0.88);
      --surface-strong: #ffffff;
      --ink: #12202a;
      --muted: #53616d;
      --line: rgba(18, 32, 42, 0.12);
      --brand: #005f73;
      --brand-strong: #0a3d52;
      --ok: #2b6e5a;
      --shadow: 0 18px 50px rgba(18, 52, 78, 0.10);
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
        radial-gradient(circle at top left, rgba(0, 95, 115, 0.14), transparent 26%),
        radial-gradient(circle at top right, rgba(215, 227, 232, 0.95), transparent 28%),
        linear-gradient(180deg, #fbfdfe 0%, var(--bg) 100%);
    }}
    .shell {{
      width: min(1400px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.98), rgba(236,245,247,0.94));
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
      background: radial-gradient(circle, rgba(0,95,115,0.20), transparent 70%);
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
      max-width: 11ch;
    }}
    .hero p {{
      max-width: 74ch;
      color: var(--muted);
    }}
    .top-grid, .band {{
      display: grid;
      gap: 16px;
    }}
    .top-grid {{
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      margin-top: 22px;
    }}
    .band {{
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin: 22px 0;
    }}
    .stat, .panel, .device-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .stat {{
      padding: 16px;
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
    .panel, .device-card {{
      padding: 18px;
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
      background: rgba(0, 95, 115, 0.08);
      color: var(--brand-strong);
      font-size: 0.92rem;
    }}
    .badge span {{
      background: rgba(0, 95, 115, 0.12);
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
      background: rgba(255,255,255,0.88);
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
      background: rgba(43,110,90,0.12);
      color: var(--ok);
      padding: 10px 14px;
      font-weight: 700;
      border: 1px solid rgba(43,110,90,0.15);
    }}
    .quick-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 18px 0 8px;
    }}
    .quick-grid div {{
      border-radius: 16px;
      padding: 12px;
      background: rgba(255,255,255,0.74);
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
      border-bottom: 1px solid rgba(18, 32, 42, 0.10);
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
      background: #12202a;
      color: #dfeff7;
      overflow-x: auto;
      font-family: var(--mono);
      font-size: 0.86rem;
    }}
    .muted {{
      color: var(--muted);
    }}
    .warnings {{
      background: rgba(0, 95, 115, 0.08);
      border: 1px solid rgba(0, 95, 115, 0.14);
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
      <p class="eyebrow">Cisco Identity Services Engine</p>
      <h1>ISE Inventory Dashboard</h1>
      <p>Detailed inventory report for Cisco ISE host {escape(ISE_HOST)}. The page includes searchable network device cards, ISE node inventory, network device groups, and raw JSON sections for troubleshooting.</p>
      <div class="top-grid">
        <div class="stat"><span>Total network devices</span><strong>{stats["total_devices"]}</strong></div>
        <div class="stat"><span>ISE nodes</span><strong>{stats["total_nodes"]}</strong></div>
        <div class="stat"><span>Device groups</span><strong>{stats["total_groups"]}</strong></div>
        <div class="stat"><span>Generated</span><strong>{escape(stringify(metadata.get("generated_at")))}</strong></div>
      </div>
    </section>

    <section class="band">
      <section class="panel">
        <h2>Report metadata</h2>
        <p class="muted">Generated against {escape(stringify(metadata.get("ise_host")))} with user {escape(stringify(metadata.get("username")))}.</p>
      </section>
      <section class="panel">
        <h2>Top profiles</h2>
        <div class="badge-row">{render_badges(stats["top_profiles"])}</div>
      </section>
      <section class="panel">
        <h2>Top device groups</h2>
        <div class="badge-row">{render_badges(stats["top_device_groups"])}</div>
      </section>
      <section class="panel">
        <h2>SNMP versions</h2>
        <div class="badge-row">{render_badges(stats["top_snmp_versions"])}</div>
      </section>
    </section>

    {warning_blocks}

    <section class="toolbar">
      <input id="searchBox" type="search" placeholder="Search device, IP, profile, group, SNMP...">
      <select id="profileFilter">
        <option value="">All profiles</option>
      </select>
      <select id="snmpFilter">
        <option value="">All SNMP versions</option>
      </select>
      <div class="count"><span id="visibleCount">{stats["total_devices"]}</span> visible devices</div>
    </section>

    <section id="deviceList" class="device-list">
      {''.join(device_cards)}
    </section>

    <section class="band">
      {render_list_table("ISE Nodes", node_rows, ["name", "fqdn", "ip_address", "roles", "node_type", "software_version"])}
      {render_list_table("Network Device Groups", group_rows, ["name", "description", "other_name"])}
    </section>
  </main>

  <script>
    const cards = Array.from(document.querySelectorAll('.device-card'));
    const searchBox = document.getElementById('searchBox');
    const profileFilter = document.getElementById('profileFilter');
    const snmpFilter = document.getElementById('snmpFilter');
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

    fillSelect(profileFilter, uniqueValues('profile'));
    fillSelect(snmpFilter, uniqueValues('snmp'));

    function applyFilters() {{
      const query = searchBox.value.trim().toLowerCase();
      const profile = profileFilter.value;
      const snmp = snmpFilter.value;
      let visible = 0;

      cards.forEach(card => {{
        const matchesQuery = !query || card.dataset.search.includes(query);
        const matchesProfile = !profile || card.dataset.profile === profile;
        const matchesSnmp = !snmp || card.dataset.snmp === snmp;
        const show = matchesQuery && matchesProfile && matchesSnmp;
        card.style.display = show ? '' : 'none';
        if (show) visible += 1;
      }});

      visibleCount.textContent = visible;
    }}

    [searchBox, profileFilter, snmpFilter].forEach(element => {{
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
    print(" Cisco ISE Device Dashboard Generator")
    print(f" Target: {ISE_HOST} | User: {ISE_USERNAME}")
    print("=" * 72)

    password = getpass("Cisco ISE password: ")
    if not password:
        print("Password is required.")
        return 1

    client = CiscoISEClient(ISE_HOST, ISE_USERNAME, password)

    try:
        print("[*] Connecting to Cisco ISE ERS API...")
        client.probe()
        print(f"[+] Authentication successful. Using ERS port {client.active_port}.")

        print("[*] Downloading inventory and related details...")
        inventory = client.collect_inventory()
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "unknown"
        body = response.text if response is not None else str(exc)
        print(f"[!] HTTP error during Cisco ISE query: {status}")
        print(body[:1000])
        return 2
    except requests.RequestException as exc:
        print(f"[!] Network error during Cisco ISE query: {exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Unexpected error: {exc}")
        return 4

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = Path(f"cisco_ise_devices_{timestamp}.json")
    html_path = Path(f"cisco_ise_devices_{timestamp}.html")

    save_json_report(inventory, json_path)
    build_html_report(inventory, html_path)

    print("[+] Export completed.")
    print(f"    JSON : {json_path.resolve()}")
    print(f"    HTML : {html_path.resolve()}")
    print("Open the HTML file in a browser for the visual dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
