#!/usr/bin/env python3
"""
Cisco FMC - NAT szabályok lekérdezése eszközönként
"""

import requests
import json
import urllib3
from getpass import getpass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FMC_HOST = "10.81.145.10"
FMC_PORT = 443
USERNAME = "admin"

BASE_URL = f"https://{FMC_HOST}:{FMC_PORT}/api/fmc_config/v1"


class FMCClient:
    def __init__(self, password):
        self.session     = requests.Session()
        self.session.verify = False
        self.token       = None
        self.domain_uuid = None
        self._authenticate(password)

    def _authenticate(self, password):
        url  = f"https://{FMC_HOST}:{FMC_PORT}/api/fmc_platform/v1/auth/generatetoken"
        resp = self.session.post(url, auth=(USERNAME, password))
        resp.raise_for_status()
        self.token       = resp.headers["X-auth-access-token"]
        self.domain_uuid = resp.headers["DOMAIN_UUID"]
        self.session.headers.update({
            "X-auth-access-token": self.token,
            "Content-Type": "application/json",
        })
        print(f"[OK] Autentikáció sikeres  |  Domain: {self.domain_uuid}\n")

    def get(self, path, params=None):
        url  = f"{BASE_URL}/domain/{self.domain_uuid}/{path}"
        resp = self.session.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def get_all(self, path):
        """Lapozást kezelő általános lekérdező (offset/limit)."""
        items, offset, limit = [], 0, 1000
        while True:
            data = self.get(path, params={"limit": limit, "offset": offset, "expanded": True})
            batch = data.get("items", [])
            items.extend(batch)
            paging = data.get("paging", {})
            if offset + limit >= paging.get("count", 0):
                break
            offset += limit
        return items

    # ── Eszközök ──────────────────────────────────────────────────────────────
    def get_devices(self):
        return self.get_all("devices/devicerecords")

    # ── NAT policy-k ─────────────────────────────────────────────────────────
    def get_nat_policies(self):
        return self.get_all("policy/ftdnatpolicies")

    # ── Auto NAT szabályok ────────────────────────────────────────────────────
    def get_auto_nat_rules(self, nat_policy_id):
        try:
            return self.get_all(f"policy/ftdnatpolicies/{nat_policy_id}/autonatrules")
        except Exception:
            return []

    # ── Manual NAT szabályok ──────────────────────────────────────────────────
    def get_manual_nat_rules(self, nat_policy_id):
        try:
            return self.get_all(f"policy/ftdnatpolicies/{nat_policy_id}/manualnatrules")
        except Exception:
            return []

    # ── Policy assignment-ek ──────────────────────────────────────────────────
    def get_policy_assignments(self):
        try:
            return self.get_all("assignment/policyassignments")
        except Exception:
            return []


# ── Formázó segédfüggvények ───────────────────────────────────────────────────

def obj_name(obj):
    """Kiveszi az objektum nevét vagy értékét."""
    if not obj:
        return "any"
    return obj.get("name") or obj.get("value") or obj.get("id", "?")

def port_str(port_obj):
    if not port_obj:
        return ""
    return f":{obj_name(port_obj)}"

def format_auto_nat(rule, idx):
    rtype       = rule.get("natType", "")
    enabled     = "" if rule.get("enabled", True) else " [DISABLED]"
    orig_net    = obj_name(rule.get("originalNetwork"))
    trans_net   = obj_name(rule.get("translatedNetwork"))
    iface_orig  = obj_name(rule.get("originalInterface"))
    iface_trans = obj_name(rule.get("translatedInterface"))

    extras = []
    if rule.get("noProxyArp"):        extras.append("no-proxy-arp")
    if rule.get("routeLookup"):       extras.append("route-lookup")
    if rule.get("dns"):               extras.append("dns")
    if rule.get("fallThrough"):       extras.append("fall-through")
    extra_str = f"  [{', '.join(extras)}]" if extras else ""

    return (
        f"  {idx:>3}. [{rtype:12s}]{enabled}\n"
        f"       Eredeti  : {orig_net}  (iface: {iface_orig})\n"
        f"       Lefordít.: {trans_net}  (iface: {iface_trans})"
        + (f"\n       Opciók   : {extra_str}" if extra_str else "")
    )

def format_manual_nat(rule, idx):
    rtype   = rule.get("natType", "")
    enabled = "" if rule.get("enabled", True) else " [DISABLED]"
    sect    = rule.get("natRuleSection", "")

    orig_src  = obj_name(rule.get("originalSource"))
    orig_dst  = obj_name(rule.get("originalDestination"))
    orig_sp   = port_str(rule.get("originalSourcePort"))
    orig_dp   = port_str(rule.get("originalDestinationPort"))

    trans_src = obj_name(rule.get("translatedSource"))
    trans_dst = obj_name(rule.get("translatedDestination"))
    trans_sp  = port_str(rule.get("translatedSourcePort"))
    trans_dp  = port_str(rule.get("translatedDestinationPort"))

    iface_orig  = obj_name(rule.get("originalInterface"))
    iface_trans = obj_name(rule.get("translatedInterface"))

    extras = []
    if rule.get("noProxyArp"):   extras.append("no-proxy-arp")
    if rule.get("routeLookup"):  extras.append("route-lookup")
    if rule.get("dns"):          extras.append("dns")
    if rule.get("unidirectional"): extras.append("unidirectional")
    extra_str = f"  [{', '.join(extras)}]" if extras else ""

    return (
        f"  {idx:>3}. [{rtype:12s}] {sect}{enabled}\n"
        f"       Eredeti  src: {orig_src}{orig_sp}  dst: {orig_dst}{orig_dp}  (iface: {iface_orig})\n"
        f"       Lefordít. src: {trans_src}{trans_sp}  dst: {trans_dst}{trans_dp}  (iface: {iface_trans})"
        + (f"\n       Opciók   : {extra_str}" if extra_str else "")
    )


# ── Fő logika ─────────────────────────────────────────────────────────────────

def main():
    print(f"Cisco FMC NAT Query  |  {FMC_HOST}")
    print("-" * 45)
    password = getpass(f"Jelszó ({USERNAME}): ")

    client = FMCClient(password)

    # 1. Eszközök
    print("[*] Eszközök lekérdezése...")
    devices = client.get_devices()
    device_map = {d["id"]: d["name"] for d in devices}
    print(f"    {len(devices)} eszköz találva: {', '.join(device_map.values())}\n")

    # 2. NAT policy-k
    print("[*] NAT policy-k lekérdezése...")
    nat_policies = client.get_nat_policies()
    print(f"    {len(nat_policies)} NAT policy találva.\n")

    # 3. Policy assignment: melyik policy melyik eszközhöz tartozik
    print("[*] Policy assignment-ek lekérdezése...")
    assignments = client.get_policy_assignments()

    # device_id -> [nat_policy_id, ...]
    device_nat_map: dict[str, list] = {}
    for a in assignments:
        policy = a.get("policy", {})
        if policy.get("type") not in ("FTDNatPolicy", "FtdNatPolicy", "ftdnatpolicies"):
            continue
        for target in a.get("targets", []):
            dev_id = target.get("id")
            if dev_id:
                device_nat_map.setdefault(dev_id, []).append(policy)

    # 4. Eszközönként kiírás
    export = {}

    for device in devices:
        dev_id   = device["id"]
        dev_name = device.get("name", dev_id)

        print(f"\n{'='*70}")
        print(f"  ESZKÖZ: {dev_name}")
        print(f"  Modell: {device.get('model','N/A')}  |  SW: {device.get('sw_version','N/A')}")
        print(f"{'='*70}")

        nat_policies_for_device = device_nat_map.get(dev_id, [])

        if not nat_policies_for_device:
            print("  Nincs hozzárendelt NAT policy.")
            export[dev_name] = {"nat_policies": []}
            continue

        export[dev_name] = {"nat_policies": []}

        for np_ref in nat_policies_for_device:
            np_id   = np_ref["id"]
            np_name = np_ref.get("name", np_id)

            print(f"\n  NAT Policy: {np_name}")
            print(f"  {'─'*60}")

            auto_rules   = client.get_auto_nat_rules(np_id)
            manual_rules = client.get_manual_nat_rules(np_id)

            # Auto NAT
            if auto_rules:
                print(f"\n  AUTO NAT szabályok ({len(auto_rules)} db):")
                for i, r in enumerate(auto_rules, 1):
                    print(format_auto_nat(r, i))
            else:
                print("\n  AUTO NAT: nincs szabály.")

            # Manual NAT
            if manual_rules:
                print(f"\n  MANUAL NAT szabályok ({len(manual_rules)} db):")
                for i, r in enumerate(manual_rules, 1):
                    print(format_manual_nat(r, i))
            else:
                print("  MANUAL NAT: nincs szabály.")

            export[dev_name]["nat_policies"].append({
                "policy_name":   np_name,
                "policy_id":     np_id,
                "auto_nat_rules":   auto_rules,
                "manual_nat_rules": manual_rules,
            })

    # 5. JSON export
    out_file = "fmc_nat_export.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Export mentve: {out_file}")


if __name__ == "__main__":
    main()
