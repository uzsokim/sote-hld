#!/usr/bin/env python3
"""
Cisco Catalyst Center (DNAC) Release Information Script
Csatlakozik a Cisco Catalyst Center-hez és megjeleníti a release információkat táblázatos formában.
"""

import requests
import json
import urllib3
from datetime import datetime

# SSL figyelmeztetések kikapcsolása (self-signed cert esetén)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
#  Konfiguráció
# ─────────────────────────────────────────────
DNAC_HOST     = "10.8.11.100"
DNAC_PORT     = 443
DNAC_USER     = "admin"           # ← módosítsd szükség szerint
DNAC_PASSWORD = "your_password"   # ← módosítsd szükség szerint
BASE_URL      = f"https://{DNAC_HOST}:{DNAC_PORT}"


# ─────────────────────────────────────────────
#  Authentikáció – JWT token lekérése
# ─────────────────────────────────────────────
def get_auth_token() -> str:
    """Lekéri az authentikációs tokent a DNAC-tól."""
    url = f"{BASE_URL}/dna/system/api/v1/auth/token"
    print(f"[*] Csatlakozás: {url}")
    try:
        response = requests.post(
            url,
            auth=(DNAC_USER, DNAC_PASSWORD),
            verify=False,
            timeout=15
        )
        response.raise_for_status()
        token = response.json().get("Token")
        if not token:
            raise ValueError("Token nem érkezett a válaszban.")
        print("[✓] Authentikáció sikeres.\n")
        return token
    except requests.exceptions.ConnectionError:
        print(f"[✗] Kapcsolódási hiba: nem érhető el a {DNAC_HOST} cím.")
        raise
    except requests.exceptions.HTTPError as e:
        print(f"[✗] HTTP hiba: {e.response.status_code} – {e.response.text}")
        raise


# ─────────────────────────────────────────────
#  DNAC Release adatok lekérése
# ─────────────────────────────────────────────
def get_dnac_release_info(token: str) -> dict:
    """Lekéri a DNAC szoftver release információkat."""
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }
    endpoints = {
        "system_health":    "/dna/intent/api/v1/diagnostics/system/health",
        "system_version":   "/dna/intent/api/v1/dnacaap/management/executable/api/v1/dnac-release",
        "dnac_packages":    "/api/system/v1/maglev/packages",
        "about":            "/dna/system/api/v1/maglev/about",
    }

    results = {}
    for name, path in endpoints.items():
        url = f"{BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=15)
            if resp.status_code == 200:
                results[name] = resp.json()
            else:
                results[name] = {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            results[name] = {"error": str(e)}

    return results


# ─────────────────────────────────────────────
#  Táblázat segédfüggvények
# ─────────────────────────────────────────────
def print_separator(widths: list, char: str = "─", corner: tuple = ("├", "┼", "┤")):
    left, mid, right = corner
    parts = [char * (w + 2) for w in widths]
    print(left + mid.join(parts) + right)


def print_row(values: list, widths: list):
    cells = [f" {str(v):<{w}} " for v, w in zip(values, widths)]
    print("│" + "│".join(cells) + "│")


def print_table(title: str, headers: list, rows: list):
    """Szép Unicode box-drawing táblázatot nyomtat."""
    if not rows:
        print(f"\n  [!] '{title}' – Nincs adat.\n")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    total_width = sum(col_widths) + 3 * len(col_widths) + 1

    # Fejléc
    print(f"\n  ┌{'─' * (total_width - 2)}┐")
    title_line = f" {title} "
    print(f"  │{title_line:^{total_width - 2}}│")
    print_separator(col_widths, "═", ("  ╞", "╪", "╡"))
    print_row(headers, col_widths)
    print_separator(col_widths, "─", ("  ├", "┼", "┤"))

    for i, row in enumerate(rows):
        print_row(row, col_widths)
        if i < len(rows) - 1:
            print_separator(col_widths, "─", ("  ├", "┼", "┤"))

    print_separator(col_widths, "─", ("  └", "┴", "┘"))


# ─────────────────────────────────────────────
#  Adatok feldolgozása és megjelenítése
# ─────────────────────────────────────────────
def display_about_info(data: dict):
    """Megjeleníti az 'about' végpont adatait."""
    if "error" in data:
        print(f"\n  [!] About endpoint: {data['error']}")
        return

    rows = []
    # Különböző DNAC verziók eltérő struktúrát használnak
    if isinstance(data, dict):
        flat = data.get("response", data)
        if isinstance(flat, dict):
            for key, val in flat.items():
                if not isinstance(val, (dict, list)):
                    rows.append([key, str(val)])
        elif isinstance(flat, list):
            for item in flat:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if not isinstance(v, (dict, list)):
                            rows.append([k, str(v)])

    print_table("DNAC – Rendszer információk (About)", ["Tulajdonság", "Érték"], rows)


def display_packages(data: dict):
    """Megjeleníti a telepített csomagokat."""
    if "error" in data:
        print(f"\n  [!] Packages endpoint: {data['error']}")
        return

    packages = []
    raw = data.get("response", data)
    if isinstance(raw, list):
        packages = raw
    elif isinstance(raw, dict):
        packages = raw.get("packages", raw.get("items", []))

    if not packages:
        print("\n  [!] Nincs csomag adat.\n")
        return

    rows = []
    for pkg in packages:
        if isinstance(pkg, dict):
            name    = pkg.get("name", pkg.get("packageName", "N/A"))
            version = pkg.get("version", pkg.get("packageVersion", "N/A"))
            state   = pkg.get("state", pkg.get("status", "N/A"))
            rows.append([name, version, state])

    print_table(
        "DNAC – Telepített csomagok",
        ["Csomag neve", "Verzió", "Állapot"],
        rows[:50]  # max 50 sor a listázhatóság érdekében
    )
    if len(rows) > 50:
        print(f"  … és még {len(rows) - 50} csomag.\n")


def display_system_health(data: dict):
    """Megjeleníti a rendszer egészségi állapotát."""
    if "error" in data:
        print(f"\n  [!] System health endpoint: {data['error']}")
        return

    response = data.get("response", data)
    if not response:
        print("\n  [!] Nincs rendszerállapot adat.\n")
        return

    rows = []
    items = response if isinstance(response, list) else [response]
    for item in items:
        if isinstance(item, dict):
            name   = item.get("name", item.get("hostname", "N/A"))
            health = item.get("healthScore", item.get("health", "N/A"))
            status = item.get("condition", item.get("status", "N/A"))
            rows.append([name, str(health), str(status)])

    print_table(
        "DNAC – Rendszer egészségi állapot",
        ["Komponens", "Health score", "Állapot"],
        rows
    )


def display_version_info(data: dict):
    """Megjeleníti a verziószámot ha elérhető."""
    if "error" in data:
        print(f"\n  [!] Version endpoint: {data['error']}")
        return

    rows = []
    flat = data.get("response", data)
    if isinstance(flat, dict):
        for k, v in flat.items():
            if not isinstance(v, (dict, list)):
                rows.append([k, str(v)])
    elif isinstance(flat, str):
        rows.append(["release", flat])

    print_table("DNAC – Release verzió", ["Mező", "Érték"], rows)


# ─────────────────────────────────────────────
#  Fő belépési pont
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Cisco Catalyst Center – Release Info Lekérdező")
    print(f"  Cél: {DNAC_HOST}   |   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        token = get_auth_token()
        info  = get_dnac_release_info(token)
    except Exception:
        print("\n[✗] Nem sikerült adatot lekérni. Ellenőrizd a kapcsolatot és a hitelesítési adatokat.")
        return

    display_about_info(info.get("about", {"error": "nem érkezett adat"}))
    display_version_info(info.get("system_version", {"error": "nem érkezett adat"}))
    display_packages(info.get("dnac_packages", {"error": "nem érkezett adat"}))
    display_system_health(info.get("system_health", {"error": "nem érkezett adat"}))

    print("\n[✓] Lekérdezés kész.\n")


if __name__ == "__main__":
    main()
