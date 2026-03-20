#!/usr/bin/env python3
"""
Cisco Catalyst Center – USA Site Törlő
Törli az "USA" nevű site-ot és az összes alatta lévő gyermek site-ot.
A törlés alulról felfelé történik (leaf → root sorrendben).
"""

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
#  Konfiguráció
# ─────────────────────────────────────────────
DNAC_HOST     = "10.8.11.100"
DNAC_PORT     = 443
DNAC_USER     = "admin"
DNAC_PASSWORD = "Cisco123!"
BASE_URL      = f"https://{DNAC_HOST}:{DNAC_PORT}"
TARGET_SITE   = "USA"


# ─────────────────────────────────────────────
#  Authentikáció
# ─────────────────────────────────────────────
def get_auth_token() -> str:
    url = f"{BASE_URL}/dna/system/api/v1/auth/token"
    print(f"[*] Csatlakozás: {url}")
    resp = requests.post(url, auth=(DNAC_USER, DNAC_PASSWORD), verify=False, timeout=15)
    resp.raise_for_status()
    token = resp.json().get("Token")
    if not token:
        raise ValueError("Token nem érkezett a válaszban.")
    print("[✓] Authentikáció sikeres.\n")
    return token


# ─────────────────────────────────────────────
#  Site Hierarchy lekérése
# ─────────────────────────────────────────────
def get_all_sites(token: str) -> dict:
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    endpoints = [
        "/dna/intent/api/v1/site-hierarchy",
        "/dna/intent/api/v1/site",
        "/api/v1/sites",
    ]
    for path in endpoints:
        url = f"{BASE_URL}{path}"
        print(f"[*] Megpróbálom: {path}")
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=15)
            if resp.status_code == 200:
                print(f"[✓] Site adatok lekérve.\n")
                return resp.json()
            else:
                print(f"    → HTTP {resp.status_code}")
        except Exception as e:
            print(f"    → Hiba: {str(e)}")
    raise Exception("Nem sikerült lekérni a site hierarchiát.")


# ─────────────────────────────────────────────
#  Site-ok feldolgozása flat dict-be
# ─────────────────────────────────────────────
def build_site_dict(data: dict) -> dict:
    sites = {}
    site_list = data.get("response", data) if isinstance(data, dict) else data
    if not isinstance(site_list, list):
        site_list = [site_list]

    for site in site_list:
        if isinstance(site, dict):
            site_id   = site.get("id") or site.get("siteId")
            site_name = site.get("name") or site.get("siteName") or "Unknown"
            parent_id = site.get("parentId") or site.get("parent_id")
            if site_id:
                sites[site_id] = {
                    "name":      site_name,
                    "parent_id": parent_id,
                }
    return sites


# ─────────────────────────────────────────────
#  USA és gyermekeinek összegyűjtése
# ─────────────────────────────────────────────
def find_site_by_name(sites: dict, name: str) -> str | None:
    for site_id, info in sites.items():
        if info["name"].strip().lower() == name.strip().lower():
            return site_id
    return None


def collect_subtree(sites: dict, root_id: str) -> list[str]:
    """
    Visszaadja a root_id alatti összes site azonosítóját (beleértve root_id-t),
    post-order (leaf-first) sorrendben, hogy alulról felfelé lehessen törölni.
    """
    result = []
    children = [s_id for s_id, s in sites.items() if s.get("parent_id") == root_id]
    for child_id in children:
        result.extend(collect_subtree(sites, child_id))
    result.append(root_id)
    return result


# ─────────────────────────────────────────────
#  Site törlése
# ─────────────────────────────────────────────
def delete_site(token: str, site_id: str, site_name: str) -> bool:
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    url = f"{BASE_URL}/dna/intent/api/v1/site/{site_id}"
    print(f"[*] Törlés: {site_name} ({site_id})")
    try:
        resp = requests.delete(url, headers=headers, verify=False, timeout=15)
        if resp.status_code in (200, 202, 204):
            print(f"[✓] Sikeresen törölve: {site_name}")
            return True
        else:
            print(f"[✗] Sikertelen törlés ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        print(f"[✗] Hiba törlés közben: {e}")
        return False


# ─────────────────────────────────────────────
#  Főprogram
# ─────────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("  CISCO CATALYST CENTER – USA SITE TÖRLŐ")
    print("="*60 + "\n")

    try:
        token = get_auth_token()

        print("[*] Site hierarchia lekérése...")
        data  = get_all_sites(token)
        sites = build_site_dict(data)
        print(f"[✓] {len(sites)} site találva.\n")

        # USA megkeresése
        usa_id = find_site_by_name(sites, TARGET_SITE)
        if not usa_id:
            print(f"[!] Nem található '{TARGET_SITE}' nevű site. Nincs mit törölni.")
            return

        print(f"[✓] '{TARGET_SITE}' site azonosítója: {usa_id}")

        # Összes érintett site összegyűjtése (leaf-first sorrend)
        to_delete = collect_subtree(sites, usa_id)
        print(f"\n[*] Törlendő site-ok száma: {len(to_delete)}")
        print("    Törlési sorrend (alulról felfelé):")
        for sid in to_delete:
            print(f"      - {sites[sid]['name']} ({sid})")

        # Megerősítés
        print()
        confirm = input(f"[?] Biztosan törli az '{TARGET_SITE}' site-ot és az összes gyermekét? (igen/nem): ")
        if confirm.strip().lower() not in ("igen", "yes", "y", "i"):
            print("[!] Törlés megszakítva.")
            return

        # Törlés végrehajtása
        print("\n[*] Törlés megkezdése...\n")
        ok_count  = 0
        err_count = 0
        for sid in to_delete:
            success = delete_site(token, sid, sites[sid]["name"])
            if success:
                ok_count += 1
            else:
                err_count += 1

        print("\n" + "="*60)
        print(f"  KÉSZ – Sikeresen törölve: {ok_count}  |  Hiba: {err_count}")
        print("="*60 + "\n")

    except KeyboardInterrupt:
        print("\n[!] Felhasználó által leállítva.\n")
    except Exception as e:
        print(f"\n[✗] Hiba: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
