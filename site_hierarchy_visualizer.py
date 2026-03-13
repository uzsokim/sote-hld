#!/usr/bin/env python3
"""
Cisco Catalyst Center (DNAC) Site Hierarchy Visualizer
Csatlakozik a Cisco Catalyst Center-hez és megjeleníti a Site hierarchiát grafikus formában.
"""

import requests
import json
import urllib3
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

# SSL figyelmeztetések kikapcsolása (self-signed cert esetén)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
#  Konfiguráció
# ─────────────────────────────────────────────
DNAC_HOST     = "10.8.11.100"
DNAC_PORT     = 443
DNAC_USER     = "admin"
DNAC_PASSWORD = "Cisco123!"
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
#  Site Hierarchy lekérése
# ─────────────────────────────────────────────
def get_site_hierarchy(token: str) -> dict:
    """Lekéri a site hierarchiát a DNAC-tól."""
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }
    
    # Próbáljuk meg több endpointot
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
                data = resp.json()
                print(f"[✓] Site adatok lekérve a {path} végpontról.\n")
                return data
            else:
                print(f"    → HTTP {resp.status_code}")
        except Exception as e:
            print(f"    → Hiba: {str(e)}")
    
    raise Exception("Nem sikerült lekérni a site hierarchiát egyik végpontról sem.")


# ─────────────────────────────────────────────
#  Site Hierarchy feldolgozása
# ─────────────────────────────────────────────
def build_site_tree(data: dict) -> dict:
    """
    Feldolgozza a DNAC Site hierarchiát és egy könnyen feldolgozható
    fa struktúrát hoz létre.
    """
    sites = {}
    
    # Keressünk "response" kulcsot (gyakori DNAC válasz formátum)
    if "response" in data:
        site_list = data["response"]
    else:
        site_list = data if isinstance(data, list) else [data]
    
    if not isinstance(site_list, list):
        site_list = [site_list]
    
    # Adatok normalizálása
    for site in site_list:
        if isinstance(site, dict):
            site_id = site.get("id") or site.get("siteId")
            site_name = site.get("name") or site.get("siteName") or "Unknown"
            parent_id = site.get("parentId") or site.get("parent_id")
            site_type = site.get("type") or site.get("siteType") or "Unknown"
            
            if site_id:
                sites[site_id] = {
                    "name": site_name,
                    "type": site_type,
                    "parent_id": parent_id,
                    "data": site
                }
    
    return sites


# ─────────────────────────────────────────────
#  NetworkX Graph felépítése
# ─────────────────────────────────────────────
def build_graph(sites: dict) -> nx.DiGraph:
    """Felépít egy NetworkX directed graphot a site estructura alapján."""
    G = nx.DiGraph()
    
    # Csomópontok hozzáadása
    for site_id, site_info in sites.items():
        label = f"{site_info['name']}\n({site_info['type']})"
        G.add_node(site_id, label=label, **site_info)
    
    # Élek hozzáadása (parent-child kapcsolatok)
    for site_id, site_info in sites.items():
        parent_id = site_info.get("parent_id")
        if parent_id and parent_id in sites:
            G.add_edge(parent_id, site_id)
    
    return G


# ─────────────────────────────────────────────
#  Hierarchikus elrendezés
# ─────────────────────────────────────────────
def get_hierarchy_layout(G: nx.DiGraph) -> dict:
    """
    Kiszámít egy hierarchikus (fa) elrendezést a graph számára.
    """
    pos = {}
    
    # Keressük meg a gyökér csomópontot(okat)
    if len(G.nodes()) == 0:
        return pos
    
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    
    if not roots:
        # Ha nincs gyökér, az első csomópontot használjuk
        roots = [list(G.nodes())[0]]
    
    def assign_positions(node, x=0, y=0, layer_distance=1.5, horizontal_distance=2):
        """Rekurzív pozíció hozzárendelés."""
        pos[node] = (x, -y)
        
        children = list(G.successors(node))
        if children:
            num_children = len(children)
            child_start_x = x - (num_children - 1) * horizontal_distance / 2
            for i, child in enumerate(children):
                child_x = child_start_x + i * horizontal_distance
                assign_positions(child, child_x, y + layer_distance, layer_distance, horizontal_distance)
    
    # Pozíciók hozzárendelése minden gyökérből kiindulva
    for i, root in enumerate(roots):
        assign_positions(root, x=i * 5, y=0)
    
    return pos


# ─────────────────────────────────────────────
#  Grafikus megjelenítés
# ─────────────────────────────────────────────
def visualize_site_hierarchy(G: nx.DiGraph, pos: dict, output_file: str = "site_hierarchy.png"):
    """
    Megjeleníti a site hierarchiát egy grafikus ábrán.
    """
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # Csomópontok szín kódolása típus alapján
    node_colors = []
    node_sizes = []
    type_colors = {
        "area": "#FF6B6B",
        "building": "#4ECDC4",
        "floor": "#45B7D1",
        "zone": "#96CEB4",
        "unknown": "#D3D3D3"
    }
    
    for node in G.nodes():
        node_type = G.nodes[node].get("type", "unknown").lower()
        color = type_colors.get(node_type, type_colors["unknown"])
        node_colors.append(color)
        
        # Csomópont mérete a kapcsolatok száma alapján
        degree = G.degree(node)
        size = 500 + degree * 300
        node_sizes.append(size)
    
    # Élek megrajzolása
    nx.draw_networkx_edges(
        G, pos,
        edge_color="gray",
        arrows=True,
        arrowsize=20,
        arrowstyle="->",
        width=2,
        ax=ax,
        connectionstyle="arc3,rad=0.1",
        alpha=0.6
    )
    
    # Csomópontok megrajzolása
    nx.draw_networkx_nodes(
        G, pos,
        node_color=node_colors,
        node_size=node_sizes,
        ax=ax,
        alpha=0.9,
        edgecolors="black",
        linewidths=2
    )
    
    # Feliratok
    labels = {node: G.nodes[node].get("label", node) for node in G.nodes()}
    nx.draw_networkx_labels(
        G, pos,
        labels=labels,
        font_size=8,
        font_weight="bold",
        ax=ax
    )
    
    # Címek és jelmagyarázat
    ax.set_title("Cisco Catalyst Center – Site Hierarchy", fontsize=16, fontweight="bold")
    
    # Jelmagyarázat
    legend_elements = [
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#FF6B6B', 
                   markersize=10, label='Area', markeredgecolor='black'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#4ECDC4', 
                   markersize=10, label='Building', markeredgecolor='black'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#45B7D1', 
                   markersize=10, label='Floor', markeredgecolor='black'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#96CEB4', 
                   markersize=10, label='Zone', markeredgecolor='black'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#D3D3D3', 
                   markersize=10, label='Other', markeredgecolor='black'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=10)
    
    ax.axis('off')
    plt.tight_layout()
    
    # Mentés és megjelenítés
    print(f"\n[*] Ábra mentése: {output_file}")
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print("[✓] Ábra mentve sikeresen.\n")
    
    print("[*] Ábra megjelenítése...")
    plt.show()


# ─────────────────────────────────────────────
#  Szöveges megjelenítés
# ─────────────────────────────────────────────

# ANSI színkódok
_C = {
    "area":     "\033[93m",   # sárga  – Area
    "building": "\033[96m",   # cián   – Building
    "floor":    "\033[92m",   # zöld   – Floor
    "zone":     "\033[95m",   # magenta – Zone
    "reset":    "\033[0m",
}

# Vizuális badge-ek típusonként
_BADGE = {
    "area":     "[ 🌐 AREA     ]",
    "building": "[ 🏢 BUILDING ]",
    "floor":    "[ 📋 FLOOR    ]",
    "zone":     "[ 🔷 ZONE     ]",
}

def print_hierarchy_text(sites: dict, parent_id: str = None, indent: int = 0):
    """
    Megjeleníti a site hierarchiát szöveges formában, típus szerinti jelöléssel.
    """
    children = [(s_id, s) for s_id, s in sites.items()
                if s.get("parent_id") == parent_id]

    for site_id, site in sorted(children, key=lambda x: x[1]['name']):
        site_type = site.get("type", "").lower()
        color  = _C.get(site_type, "")
        reset  = _C["reset"]
        badge  = _BADGE.get(site_type, f"[ {site_type.upper():10s} ]")
        connector = "  " * indent + "├── "
        print(f"{connector}{color}{badge}{reset}  {site['name']}")
        print_hierarchy_text(sites, site_id, indent + 1)


# ─────────────────────────────────────────────
#  Statisztika
# ─────────────────────────────────────────────
def print_statistics(sites: dict, G: nx.DiGraph):
    """Megjeleníti a site hierarchia statisztikáit."""
    print("\n" + "="*60)
    print("  SITE HIERARCHY STATISZTIKA")
    print("="*60)
    
    type_count = {}
    for site in sites.values():
        site_type = site.get("type", "unknown")
        type_count[site_type] = type_count.get(site_type, 0) + 1
    
    print(f"\nÖsszesen: {len(sites)} site")
    print("\nSite típusok szerinti bontás:")
    for site_type, count in sorted(type_count.items()):
        print(f"  • {site_type}: {count}")
    
    print(f"\nGraf csomópontok: {G.number_of_nodes()}")
    print(f"Graf élek: {G.number_of_edges()}")
    
    # Mélység számítása
    if G.number_of_nodes() > 0:
        roots = [n for n in G.nodes() if G.in_degree(n) == 0]
        max_depth = 0
        for root in roots:
            depth = nx.shortest_path_length(G, root, max(G.nodes(), key=lambda n: 0))
            max_depth = max(max_depth, len(nx.descendants(G, root)))
        print(f"Hierarchia maximális mélysége: ~{max_depth} level")
    
    print("="*60 + "\n")


# ─────────────────────────────────────────────
#  Főprogram
# ─────────────────────────────────────────────
def main():
    """Fő program flow."""
    try:
        print("\n" + "="*60)
        print("  CISCO CATALYST CENTER – SITE HIERARCHY VISUALIZER")
        print("="*60 + "\n")
        
        # 1. Authentikáció
        token = get_auth_token()
        
        # 2. Site adatok lekérése
        print("[*] Site hierarchia lekérése...")
        data = get_site_hierarchy(token)
        
        # 3. Site fa felépítése
        print("[*] Site fa feldolgozása...")
        sites = build_site_tree(data)
        
        if not sites:
            print("[!] Nem találtam site adatokat!\n")
            print("Raw adat preview:")
            print(json.dumps(data, indent=2)[:500])
            return
        
        print(f"[✓] {len(sites)} site feldolgozva.\n")
        
        # 4. Szöveges megjelenítés
        print("[*] Site hierarchia szöveges megjelenítése:\n")
        print_hierarchy_text(sites)
        
        # 5. Graph felépítése
        print("\n[*] Grafikon felépítése...")
        G = build_graph(sites)
        
        # 6. Elrendezés kiszámítása
        print("[*] Hierarchikus elrendezés kalkulálása...")
        pos = get_hierarchy_layout(G)
        
        # 7. Statisztika
        print_statistics(sites, G)
        
        # 8. Grafikus megjelenítés
        print("[*] Grafikus megjelenítés előkészítése...")
        visualize_site_hierarchy(G, pos, "site_hierarchy.png")
        
        print("[✓] Kész!\n")
        
    except KeyboardInterrupt:
        print("\n[!] Felhasználó által leállítva.\n")
    except Exception as e:
        print(f"\n[✗] Hiba: {str(e)}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
