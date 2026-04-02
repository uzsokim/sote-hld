#!/usr/bin/env python3
"""
Cisco ISE TrustSec policy exporter for offline IOS-XE CLI generation.

The script:
1. Authenticates to Cisco ISE ERS API
2. Downloads SGT, SGACL and TrustSec policy matrix data
3. Saves a raw JSON snapshot
4. Builds an offline IOS-XE CLI configuration file

Default target:
- Host: 10.8.11.101
- Username: admin
- Password: prompted securely at runtime
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HOST = "10.8.11.101"
DEFAULT_USERNAME = "admin"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100
ISE_PORT_CANDIDATES = (9060, 443)


@dataclass
class SGT:
    id: str
    name: str
    value: int | None
    description: str


@dataclass
class SGACL:
    id: str
    name: str
    ip_version: str
    acl_lines: list[str]
    description: str


@dataclass
class MatrixCell:
    id: str
    source_sgt_id: str | None
    destination_sgt_id: str | None
    source_sgt_name: str | None
    destination_sgt_name: str | None
    default_rule: str | None
    sgacl_ids: list[str]
    sgacl_names: list[str]
    description: str


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
                    f"{self.base_url}/ers/config/sgt",
                    params={"size": 1, "page": 1},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()

                if self._looks_like_login_page(response):
                    failures.append(
                        f"port {port}: HTML login page returned instead of ERS JSON"
                    )
                    continue

                self._decode_json_response(response, "/ers/config/sgt")
                return
            except Exception as exc:  # noqa: BLE001
                failures.append(f"port {port}: {exc}")

        failure_text = "; ".join(failures)
        raise RuntimeError(
            "Cisco ISE ERS API is not reachable in API mode. "
            "Checked ports 443 and 9060. "
            f"Details: {failure_text}"
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
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
                raise RuntimeError(
                    f"Unexpected response format from {path}: {type(data).__name__}"
                )

            search_result = data.get("SearchResult", {})
            resources = search_result.get("resources", [])
            if not resources:
                break

            items.extend(resources)

            total = int(search_result.get("total", len(items)))
            if len(items) >= total or len(resources) < page_size:
                break

            page += 1

        return items

    def get_resource_detail(self, path: str, resource_id: str) -> dict[str, Any]:
        data = self.get(f"{path}/{resource_id}")
        payload = unwrap_payload(data)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected detail payload for {path}/{resource_id}")
        return payload

    def get_sgts(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/sgt")

    def get_sgt_detail(self, resource_id: str) -> dict[str, Any]:
        return self.get_resource_detail("/ers/config/sgt", resource_id)

    def get_sgacls(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/sgacl")

    def get_sgacl_detail(self, resource_id: str) -> dict[str, Any]:
        return self.get_resource_detail("/ers/config/sgacl", resource_id)

    def get_matrix_cells(self) -> list[dict[str, Any]]:
        return self.get_paginated_search_result("/ers/config/egressmatrixcell")

    def get_matrix_cell_detail(self, resource_id: str) -> dict[str, Any]:
        return self.get_resource_detail("/ers/config/egressmatrixcell", resource_id)


def unwrap_payload(data: dict[str, Any]) -> Any:
    if len(data) == 1:
        return next(iter(data.values()))

    for key in (
        "Sgt",
        "Sgacl",
        "EgressMatrixCell",
        "Response",
        "response",
    ):
        value = data.get(key)
        if value is not None:
            return value

    return data


def get_ci(data: dict[str, Any], *keys: str) -> Any:
    lookup = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        lowered = key.lower()
        if lowered in lookup:
            return lookup[lowered]
    return None


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_acl_lines(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = str(raw_value).replace("\r", "").split("\n")
    return [line.strip() for line in values if str(line).strip()]


def sanitize_name(value: str, max_length: int = 64) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "UNNAMED"
    return normalized[:max_length]


def normalize_default_rule(value: str | None) -> str | None:
    if not value:
        return None
    token = re.sub(r"[^A-Za-z0-9]+", "_", value.upper()).strip("_")
    aliases = {
        "NONE": None,
        "NO_RULE": None,
        "PERMIT_IP": "permit ip",
        "PERMIT": "permit ip",
        "DENY_IP": "deny ip",
        "DENY": "deny ip",
    }
    return aliases.get(token, value.lower())


def parse_sgt(detail: dict[str, Any]) -> SGT:
    raw_value = get_ci(detail, "value", "tag", "sgtValue")
    value: int | None
    try:
        value = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None

    return SGT(
        id=str(get_ci(detail, "id") or ""),
        name=str(get_ci(detail, "name") or f"sgt_{value if value is not None else 'unknown'}"),
        value=value,
        description=str(get_ci(detail, "description") or ""),
    )


def parse_sgacl(detail: dict[str, Any]) -> SGACL:
    raw_lines = (
        get_ci(detail, "aclcontent", "aclContent", "acl", "content")
        or get_ci(detail, "commands", "aclEntries")
        or []
    )
    return SGACL(
        id=str(get_ci(detail, "id") or ""),
        name=str(get_ci(detail, "name") or "unnamed_sgacl"),
        ip_version=str(get_ci(detail, "ipVersion", "ipversion") or "IPV4"),
        acl_lines=normalize_acl_lines(raw_lines),
        description=str(get_ci(detail, "description") or ""),
    )


def parse_name_list(items: list[Any]) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    names: list[str] = []

    for item in items:
        if isinstance(item, dict):
            item_id = get_ci(item, "id")
            item_name = get_ci(item, "name")
            if item_id:
                ids.append(str(item_id))
            if item_name:
                names.append(str(item_name))
        elif item is not None:
            names.append(str(item))

    return ids, names


def parse_matrix_cell(detail: dict[str, Any]) -> MatrixCell:
    source = get_ci(detail, "sourceSgt", "sourceSGT", "srcSgt", "srcSGT") or {}
    destination = get_ci(
        detail,
        "destinationSgt",
        "destinationSGT",
        "dstSgt",
        "dstSGT",
    ) or {}

    source_id = (
        get_ci(detail, "sourceSgtId", "sourceSGTId", "srcSgtId", "srcSGTId")
        or (get_ci(source, "id") if isinstance(source, dict) else None)
    )
    destination_id = (
        get_ci(detail, "destinationSgtId", "destinationSGTId", "dstSgtId", "dstSGTId")
        or (get_ci(destination, "id") if isinstance(destination, dict) else None)
    )
    source_name = (
        get_ci(detail, "sourceSgtName", "sourceSGTName", "srcSgtName", "srcSGTName")
        or (get_ci(source, "name") if isinstance(source, dict) else None)
    )
    destination_name = (
        get_ci(
            detail,
            "destinationSgtName",
            "destinationSGTName",
            "dstSgtName",
            "dstSGTName",
        )
        or (get_ci(destination, "name") if isinstance(destination, dict) else None)
    )

    raw_sgacls = (
        get_ci(detail, "sgacls", "sgacl", "sgaclList", "acl")
        or get_ci(detail, "matrixCellACL", "matrixCellAcls")
        or []
    )
    sgacl_ids, sgacl_names = parse_name_list(ensure_list(raw_sgacls))

    return MatrixCell(
        id=str(get_ci(detail, "id") or ""),
        source_sgt_id=str(source_id) if source_id else None,
        destination_sgt_id=str(destination_id) if destination_id else None,
        source_sgt_name=str(source_name) if source_name else None,
        destination_sgt_name=str(destination_name) if destination_name else None,
        default_rule=str(get_ci(detail, "defaultRule", "defaultrule") or "") or None,
        sgacl_ids=sgacl_ids,
        sgacl_names=sgacl_names,
        description=str(get_ci(detail, "description") or ""),
    )


def collect_trustsec_data(client: CiscoISEClient) -> dict[str, Any]:
    print("Kapcsolat ellenőrzése az ISE ERS API felé...")
    client.probe()
    print(f"Kapcsolódva: {client.base_url}")

    sgt_summary = client.get_sgts()
    sgacl_summary = client.get_sgacls()
    matrix_summary = client.get_matrix_cells()

    print(f"SGT lekérdezés: {len(sgt_summary)} elem")
    print(f"SGACL lekérdezés: {len(sgacl_summary)} elem")
    print(f"Policy matrix lekérdezés: {len(matrix_summary)} elem")

    sgts: list[dict[str, Any]] = []
    for index, item in enumerate(sgt_summary, start=1):
        resource_id = str(item.get("id") or "")
        name = item.get("name") or f"sgt-{index}"
        print(f"[SGT {index}/{len(sgt_summary)}] {name}")
        detail = client.get_sgt_detail(resource_id) if resource_id else item
        sgts.append(detail)

    sgacls: list[dict[str, Any]] = []
    for index, item in enumerate(sgacl_summary, start=1):
        resource_id = str(item.get("id") or "")
        name = item.get("name") or f"sgacl-{index}"
        print(f"[SGACL {index}/{len(sgacl_summary)}] {name}")
        detail = client.get_sgacl_detail(resource_id) if resource_id else item
        sgacls.append(detail)

    matrix_cells: list[dict[str, Any]] = []
    for index, item in enumerate(matrix_summary, start=1):
        resource_id = str(item.get("id") or "")
        name = item.get("name") or f"matrix-cell-{index}"
        print(f"[CELL {index}/{len(matrix_summary)}] {name}")
        detail = client.get_matrix_cell_detail(resource_id) if resource_id else item
        matrix_cells.append(detail)

    return {
        "metadata": {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "ise_host": client.host,
            "ise_port": client.active_port,
            "username": client.username,
        },
        "sgts": sgts,
        "sgacls": sgacls,
        "egress_matrix_cells": matrix_cells,
    }


def build_iosxe_cli(data: dict[str, Any]) -> str:
    sgts = [parse_sgt(item) for item in data.get("sgts", [])]
    sgacls = [parse_sgacl(item) for item in data.get("sgacls", [])]
    matrix_cells = [parse_matrix_cell(item) for item in data.get("egress_matrix_cells", [])]

    sgt_by_id = {item.id: item for item in sgts if item.id}
    sgt_by_name = {item.name: item for item in sgts}
    sgacl_by_id = {item.id: item for item in sgacls if item.id}
    sgacl_by_name = {item.name: item for item in sgacls}

    acl_name_map: dict[str, str] = {}
    used_acl_names: set[str] = set()

    def reserve_acl_name(base_name: str) -> str:
        candidate = sanitize_name(base_name)
        if candidate not in used_acl_names:
            used_acl_names.add(candidate)
            return candidate

        suffix = 2
        while True:
            trimmed = sanitize_name(base_name, max_length=max(1, 60 - len(str(suffix))))
            candidate = f"{trimmed}_{suffix}"
            if candidate not in used_acl_names:
                used_acl_names.add(candidate)
                return candidate
            suffix += 1

    lines: list[str] = []
    lines.extend(
        [
            "! ============================================================",
            "! Cisco ISE TrustSec -> IOS-XE offline CLI export",
            f"! Generated: {data.get('metadata', {}).get('exported_at', '')}",
            f"! ISE host: {data.get('metadata', {}).get('ise_host', '')}",
            "!",
            "! Assumption: the target switch accepts offline role-based ACL",
            "! definitions with 'ip access-list role-based' and bindings with",
            "! 'cts role-based permissions from <src> to <dst> ipv4 <acl>'.",
            "! Review the generated commands on the exact IOS-XE release before",
            "! bulk deployment in production.",
            "! ============================================================",
            "",
        ]
    )

    lines.append("cts role-based enforcement")
    lines.append("")

    if sgts:
        lines.append("! SGT reference table")
        for sgt in sorted(sgts, key=lambda item: (item.value is None, item.value, item.name)):
            value_text = "unknown" if sgt.value is None else str(sgt.value)
            desc_suffix = f" | {sgt.description}" if sgt.description else ""
            lines.append(f"! SGT {value_text}: {sgt.name}{desc_suffix}")
        lines.append("")

    for sgacl in sorted(sgacls, key=lambda item: item.name.lower()):
        acl_name = reserve_acl_name(sgacl.name)
        acl_name_map[sgacl.name] = acl_name
        if sgacl.id:
            acl_name_map[sgacl.id] = acl_name

        lines.append(f"! SGACL source: {sgacl.name}")
        if sgacl.description:
            lines.append(f"! Description: {sgacl.description}")
        lines.append(f"ip access-list role-based {acl_name}")
        if sgacl.acl_lines:
            for acl_line in sgacl.acl_lines:
                lines.append(f" {acl_line}")
        else:
            lines.append(" remark Empty SGACL from ISE")
        lines.append("exit")
        lines.append("")

    lines.append("! Policy matrix bindings")

    for cell in matrix_cells:
        source_sgt = None
        if cell.source_sgt_id:
            source_sgt = sgt_by_id.get(cell.source_sgt_id)
        if source_sgt is None and cell.source_sgt_name:
            source_sgt = sgt_by_name.get(cell.source_sgt_name)

        destination_sgt = None
        if cell.destination_sgt_id:
            destination_sgt = sgt_by_id.get(cell.destination_sgt_id)
        if destination_sgt is None and cell.destination_sgt_name:
            destination_sgt = sgt_by_name.get(cell.destination_sgt_name)

        if source_sgt is None or destination_sgt is None:
            lines.append(
                f"! SKIPPED cell {cell.id}: source/destination SGT not resolved "
                f"({cell.source_sgt_name or cell.source_sgt_id} -> "
                f"{cell.destination_sgt_name or cell.destination_sgt_id})"
            )
            continue

        if source_sgt.value is None or destination_sgt.value is None:
            lines.append(
                f"! SKIPPED cell {cell.id}: missing numeric SGT value "
                f"({source_sgt.name} -> {destination_sgt.name})"
            )
            continue

        source_value = source_sgt.value
        destination_value = destination_sgt.value
        default_rule = normalize_default_rule(cell.default_rule)

        resolved_acl_names: list[str] = []
        for sgacl_id in cell.sgacl_ids:
            acl_name = acl_name_map.get(sgacl_id)
            if acl_name:
                resolved_acl_names.append(acl_name)
            elif sgacl_id in sgacl_by_id:
                resolved_acl_names.append(acl_name_map.get(sgacl_by_id[sgacl_id].name, ""))

        for sgacl_name in cell.sgacl_names:
            acl_name = acl_name_map.get(sgacl_name)
            if acl_name:
                resolved_acl_names.append(acl_name)
            elif sgacl_name in sgacl_by_name:
                resolved_acl_names.append(acl_name_map.get(sgacl_by_name[sgacl_name].name, ""))

        resolved_acl_names = [name for name in dict.fromkeys(resolved_acl_names) if name]

        comment = (
            f"! {source_sgt.name} ({source_value}) -> "
            f"{destination_sgt.name} ({destination_value})"
        )
        if cell.description:
            comment = f"{comment} | {cell.description}"
        lines.append(comment)

        if resolved_acl_names:
            if len(resolved_acl_names) == 1:
                lines.append(
                    f"cts role-based permissions from {source_value} to {destination_value} "
                    f"ipv4 {resolved_acl_names[0]}"
                )
            else:
                merged_acl_base = (
                    f"MERGED_{source_sgt.name}_{destination_sgt.name}_{source_value}_{destination_value}"
                )
                merged_acl_name = reserve_acl_name(merged_acl_base)
                merged_lines: list[str] = []
                for acl_name in resolved_acl_names:
                    sgacl_obj = next(
                        (item for item in sgacls if acl_name_map.get(item.name) == acl_name),
                        None,
                    )
                    if sgacl_obj is not None:
                        merged_lines.extend(sgacl_obj.acl_lines)

                insert_index = len(lines) - 1
                merged_block = [f"ip access-list role-based {merged_acl_name}"]
                if merged_lines:
                    for acl_line in merged_lines:
                        merged_block.append(f" {acl_line}")
                else:
                    merged_block.append(" remark Empty merged SGACL content")
                merged_block.extend(["exit", ""])
                lines[insert_index:insert_index] = merged_block

                lines.append(
                    f"cts role-based permissions from {source_value} to {destination_value} "
                    f"ipv4 {merged_acl_name}"
                )
        elif default_rule in {"permit ip", "deny ip"}:
            lines.append(
                f"cts role-based permissions from {source_value} to {destination_value} "
                f"{default_rule}"
            )
        else:
            lines.append(
                f"! No SGACL/default rule mapped for this cell "
                f"(defaultRule={cell.default_rule or 'none'})"
            )

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_outputs(output_prefix: str, data: dict[str, Any], cli_text: str) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = Path(f"{output_prefix}_{timestamp}.json")
    cli_path = Path(f"{output_prefix}_{timestamp}.txt")

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    cli_path.write_text(cli_text, encoding="utf-8")

    return json_path, cli_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cisco ISE TrustSec policy export to offline IOS-XE CLI"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Cisco ISE host/IP")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Cisco ISE username")
    parser.add_argument(
        "--output-prefix",
        default="ise_trustsec_iosxe",
        help="Output filename prefix for JSON and CLI exports",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"Cisco ISE TrustSec export indul: host={args.host}, user={args.username}")
    password = getpass("ISE jelszó: ")
    if not password:
        print("Hiba: üres jelszóval nem indul a lekérdezés.", file=sys.stderr)
        return 1

    client = CiscoISEClient(args.host, args.username, password)

    try:
        data = collect_trustsec_data(client)
        cli_text = build_iosxe_cli(data)
        json_path, cli_path = save_outputs(args.output_prefix, data, cli_text)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        print(f"HTTP hiba történt (status={status_code}): {exc}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(f"Hálózati/API hiba történt: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"Feldolgozási hiba történt: {exc}", file=sys.stderr)
        return 4

    print(f"Nyers export mentve: {json_path}")
    print(f"IOS-XE CLI mentve:   {cli_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
