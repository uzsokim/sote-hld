#!/usr/bin/env python3
"""
Cisco FMC Device Manager Query Script
Csatlakozik az FMC REST API-hoz és lekérdezi az összes eszközt és beállításukat.
"""

import requests
import json
import sys
import urllib3
from getpass import getpass

# SSL figyelmeztetés kikapcsolása (self-signed cert esetén)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── KONFIGURÁCIÓ ────────────────────────────────────────────────────────────
FMC_HOST   = "10.81.145.10"   # <-- FMC IP-cím
FMC_PORT   = 443
USERNAME   = "admin"
PASSWORD   = "Lab1%Dev2."            # Ha üres, futáskor kéri be
DOMAIN_UUID = "default"   # Felülírja az auth után az API-ból kapott értékkel
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = f"https://{FMC_HOST}:{FMC_PORT}/api/fmc_config/v1"


class FMCClient:
    def __init__(self, host, username, password):
        self.host      = host
        self.username  = username
        self.password  = password
        self.token     = None
        self.domain_uuid = None
        self.session   = requests.Session()
        self.session.verify = False

    # ── Autentikáció ──────────────────────────────────────────────────────────
    def authenticate(self):
        url = f"https://{self.host}:{FMC_PORT}/api/fmc_platform/v1/auth/generatetoken"
        resp = self.session.post(url, auth=(self.username, self.password))
        resp.raise_for_status()

        self.token = resp.headers.get("X-auth-access-token")
        self.domain_uuid = resp.headers.get("DOMAIN_UUID", DOMAIN_UUID)

        self.session.headers.update({
            "X-auth-access-token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        print(f"[OK] Autentikáció sikeres. Domain UUID: {self.domain_uuid}")

    # ── Általános GET ─────────────────────────────────────────────────────────
    def get(self, path, params=None):
        url = f"{BASE_URL}/domain/{self.domain_uuid}/{path}"
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Eszközlista ───────────────────────────────────────────────────────────
    def get_devices(self):
        data = self.get("devices/devicerecords", params={"limit": 1000, "expanded": True})
        return data.get("items", [])

    # ── Egy eszköz részletes adatai ───────────────────────────────────────────
    def get_device_detail(self, device_id):
        return self.get(f"devices/devicerecords/{device_id}")

    # ── Interfészek ───────────────────────────────────────────────────────────
    def get_interfaces(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/physicalinterfaces",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return [{"error": str(e)}]

    # ── Szub-interfészek ──────────────────────────────────────────────────────
    def get_subinterfaces(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/subinterfaces",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── Redundáns interfészek ─────────────────────────────────────────────────
    def get_redundant_interfaces(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/redundantinterfaces",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── EtherChannel interfészek ──────────────────────────────────────────────
    def get_etherchannel_interfaces(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/etherchannelinterfaces",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── Routing: statikus útvonalak ───────────────────────────────────────────
    def get_static_routes(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/routing/ipv4staticroutes",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return [{"error": str(e)}]

    # ── Routing: IPv6 statikus útvonalak ─────────────────────────────────────
    def get_static_routes_v6(self, device_id):
        try:
            data = self.get(f"devices/devicerecords/{device_id}/routing/ipv6staticroutes",
                            params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── Policy assignment ─────────────────────────────────────────────────────
    def get_policy_assignments(self):
        try:
            data = self.get("assignment/policyassignments", params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return [{"error": str(e)}]

    # ── HA párok ──────────────────────────────────────────────────────────────
    def get_ha_pairs(self):
        try:
            data = self.get("devicehapairs/ftddevicehapairs", params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── Cluster-ek ────────────────────────────────────────────────────────────
    def get_device_clusters(self):
        try:
            data = self.get("deviceclusters/ftddeviceclusters", params={"limit": 1000})
            return data.get("items", [])
        except Exception as e:
            return []

    # ── Deployable devices ────────────────────────────────────────────────────
    def get_deployable_devices(self):
        try:
            url = f"https://{self.host}:{FMC_PORT}/api/fmc_config/v1/domain/{self.domain_uuid}/deployment/deployabledevices"
            resp = self.session.get(url, params={"limit": 1000})
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as e:
            return []

    # ── Teljes eszközinformáció összegyűjtése ─────────────────────────────────
    def collect_all(self):
        result = {}

        print("\n[*] Eszközlista lekérdezése...")
        devices = self.get_devices()
        print(f"    {len(devices)} eszköz találva.")

        for dev in devices:
            dev_id   = dev.get("id")
            dev_name = dev.get("name", dev_id)
            print(f"\n[*] Feldolgozás: {dev_name} ({dev_id})")

            dev_data = {
                "alap_adatok":            self.get_device_detail(dev_id),
                "fizikai_interfeszek":    self.get_interfaces(dev_id),
                "szub_interfeszek":       self.get_subinterfaces(dev_id),
                "redundans_interfeszek":  self.get_redundant_interfaces(dev_id),
                "etherchannel_interfeszek": self.get_etherchannel_interfaces(dev_id),
                "statikus_utvonalak_v4":  self.get_static_routes(dev_id),
                "statikus_utvonalak_v6":  self.get_static_routes_v6(dev_id),
            }
            result[dev_name] = dev_data
            print(f"    Interfészek: {len(dev_data['fizikai_interfeszek'])} db fizikai")

        print("\n[*] Policy assignment-ek lekérdezése...")
        result["_policy_assignments"] = self.get_policy_assignments()

        print("[*] HA párok lekérdezése...")
        result["_ha_pairs"] = self.get_ha_pairs()

        print("[*] Device cluster-ek lekérdezése...")
        result["_device_clusters"] = self.get_device_clusters()

        print("[*] Deployable devices lekérdezése...")
        result["_deployable_devices"] = self.get_deployable_devices()

        return result


# ── Megjelenítő függvények ────────────────────────────────────────────────────

def print_device_summary(name, data):
    alap = data.get("alap_adatok", {})
    print(f"\n{'='*70}")
    print(f"  ESZKÖZ: {name}")
    print(f"{'='*70}")
    print(f"  ID          : {alap.get('id', 'N/A')}")
    print(f"  Hostname    : {alap.get('hostName', 'N/A')}")
    print(f"  Típus       : {alap.get('model', 'N/A')}")
    print(f"  SW verzió   : {alap.get('sw_version', 'N/A')}")
    print(f"  Teljesítmény: {alap.get('performanceTier', 'N/A')}")
    print(f"  Regisztrálva: {alap.get('registrationKey', 'N/A')}")
    print(f"  Nat ID      : {alap.get('natID', 'N/A')}")
    print(f"  Licence     : {alap.get('license_caps', 'N/A')}")

    # Access policy
    ap = alap.get("accessPolicy", {})
    if ap:
        print(f"  Access Policy: {ap.get('name', 'N/A')} ({ap.get('id', '')})")

    # Health policy
    hp = alap.get("healthPolicy", {})
    if hp:
        print(f"  Health Policy: {hp.get('name', 'N/A')}")

    # Interfészek
    ifaces = data.get("fizikai_interfeszek", [])
    if ifaces and "error" not in (ifaces[0] if ifaces else {}):
        print(f"\n  Fizikai interfészek ({len(ifaces)} db):")
        for iface in ifaces:
            enabled = "UP" if iface.get("enabled") else "DOWN"
            ip_info = ""
            ipv4 = iface.get("ipv4", {})
            if ipv4.get("static"):
                addr = ipv4["static"].get("address", {})
                ip_info = f"  {addr.get('value','')}/{addr.get('netmask','')}"
            elif ipv4.get("dhcp"):
                ip_info = "  DHCP"
            print(f"    [{enabled}] {iface.get('name','?'):20s} {ip_info}")

    # Szub-interfészek
    sub_ifaces = data.get("szub_interfeszek", [])
    if sub_ifaces:
        print(f"\n  Szub-interfészek ({len(sub_ifaces)} db):")
        for iface in sub_ifaces[:10]:  # max 10 sor
            vlan = iface.get("vlanId", "")
            print(f"    {iface.get('name','?'):20s}  VLAN: {vlan}")
        if len(sub_ifaces) > 10:
            print(f"    ... és még {len(sub_ifaces)-10} db")

    # Statikus útvonalak
    routes = data.get("statikus_utvonalak_v4", [])
    if routes and "error" not in (routes[0] if routes else {}):
        print(f"\n  IPv4 statikus útvonalak ({len(routes)} db):")
        for r in routes:
            nets = [n.get("value", "") for n in r.get("selectedNetworks", [])]
            gw   = r.get("gateway", {}).get("object", {}).get("value", "")
            iface_name = r.get("interfaceName", "")
            print(f"    {str(nets):30s}  GW: {gw:15s}  IF: {iface_name}")


def print_policy_assignments(assignments):
    if not assignments:
        return
    print(f"\n{'='*70}")
    print(f"  POLICY ASSIGNMENT-EK ({len(assignments)} db)")
    print(f"{'='*70}")
    for pa in assignments:
        policy = pa.get("policy", {})
        targets = pa.get("targets", [])
        print(f"  Policy: {policy.get('name', 'N/A')} ({policy.get('type', '')})")
        for t in targets:
            print(f"    -> {t.get('name', 'N/A')} ({t.get('type', '')})")


def print_ha_pairs(ha_pairs):
    if not ha_pairs:
        return
    print(f"\n{'='*70}")
    print(f"  HA PÁROK ({len(ha_pairs)} db)")
    print(f"{'='*70}")
    for ha in ha_pairs:
        primary   = ha.get("primary", {}).get("name", "N/A")
        secondary = ha.get("secondary", {}).get("name", "N/A")
        status    = ha.get("ftdHABootstrapData", {}).get("haRole", "")
        print(f"  {ha.get('name','?')}:  Primary: {primary}  |  Secondary: {secondary}  |  {status}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global PASSWORD
    print(f"Cisco FMC Device Query  |  {FMC_HOST}")
    print("-" * 40)

    password = PASSWORD or getpass(f"Jelszó ({USERNAME}): ")

    client = FMCClient(FMC_HOST, USERNAME, password)

    try:
        client.authenticate()
    except requests.exceptions.ConnectionError:
        print(f"[HIBA] Nem sikerült csatlakozni: {FMC_HOST}")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"[HIBA] Autentikáció sikertelen: {e}")
        sys.exit(1)

    all_data = client.collect_all()

    # ── Kiírás konzolra ───────────────────────────────────────────────────────
    for name, data in all_data.items():
        if name.startswith("_"):
            continue
        print_device_summary(name, data)

    print_policy_assignments(all_data.get("_policy_assignments", []))
    print_ha_pairs(all_data.get("_ha_pairs", []))

    # ── JSON mentése ──────────────────────────────────────────────────────────
    output_file = "fmc_devices_export.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Teljes adatexport mentve: {output_file}")


if __name__ == "__main__":
    main()
