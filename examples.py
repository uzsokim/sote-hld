#!/usr/bin/env python3
"""
Quick Start Guide és Alternatív Felhasználási Módok
Site Hierarchy Visualizer-hez
"""

# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 1: Alap futtatás (javasolt)
# ═════════════════════════════════════════════════════════════════════════════
"""
PowerShell-ben futtasd:
    python site_hierarchy_visualizer.py

Ez megjeleníti:
  • A szöveges hierarchiát
  • Statisztikákat
  • Grafikus ábrát (PNG fájlban és ablakban)
"""


# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 2: Programozási módban használat
# ═════════════════════════════════════════════════════════════════════════════

from site_hierarchy_visualizer import (
    get_auth_token,
    get_site_hierarchy,
    build_site_tree,
    build_graph,
    get_hierarchy_layout,
    visualize_site_hierarchy,
    print_statistics,
    print_hierarchy_text,
    BASE_URL,
    DNAC_HOST,
)
import json

def example_programmatic_usage():
    """Példa: Szabad hozzáférés az API-hoz custom feldolgozáshoz."""
    
    try:
        # Step 1: Authentikáció
        token = get_auth_token()
        
        # Step 2: Site adatok lekérése
        data = get_site_hierarchy(token)
        
        # Step 3: Testreszabott feldolgozás
        sites = build_site_tree(data)
        
        # Saját szűrés: csak "Area" típusúak
        areas = {sid: s for sid, s in sites.items() 
                if s.get('type') == 'area'}
        print(f"\nTalált {len(areas)} Area:")
        for area_id, area in areas.items():
            print(f"  • {area['name']}")
        
        # Step 4: Graph és vizualizáció
        G = build_graph(sites)
        pos = get_hierarchy_layout(G)
        visualize_site_hierarchy(G, pos, "custom_hierarchy.png")
        
    except Exception as e:
        print(f"Hiba: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 3: Csak szöveges kimenet (képernyőre)
# ═════════════════════════════════════════════════════════════════════════════

def example_text_only():
    """Példa: Csak szöveges hierarchia, grafika nélkül."""
    
    try:
        token = get_auth_token()
        data = get_site_hierarchy(token)
        sites = build_site_tree(data)
        
        print("\n*** SITE HIERARCHIA ***\n")
        print_hierarchy_text(sites)
        
    except Exception as e:
        print(f"Hiba: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 4: JSON export
# ═════════════════════════════════════════════════════════════════════════════

def example_json_export():
    """Példa: Site hierarchy JSON fájlba mentése."""
    
    try:
        token = get_auth_token()
        data = get_site_hierarchy(token)
        sites = build_site_tree(data)
        
        # Konvertálás JSON-ővé
        export_data = {
            'dnac_host': DNAC_HOST,
            'site_count': len(sites),
            'sites': {
                site_id: {
                    'name': site['name'],
                    'type': site['type'],
                    'parent_id': site['parent_id']
                }
                for site_id, site in sites.items()
            }
        }
        
        # Mentés
        with open('site_hierarchy_export.json', 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        print(f"[✓] Exportálva: site_hierarchy_export.json")
        
    except Exception as e:
        print(f"Hiba: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 5: Egyedi grafikon beállítások
# ═════════════════════════════════════════════════════════════════════════════

def example_custom_visualization():
    """Példa: Testreszabott grafikális megjelenítés."""
    
    try:
        import networkx as nx
        import matplotlib.pyplot as plt
        
        token = get_auth_token()
        data = get_site_hierarchy(token)
        sites = build_site_tree(data)
        G = build_graph(sites)
        pos = get_hierarchy_layout(G)
        
        # Saját figura
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))
        
        # Bal oldal: Hierarchikus gráf
        nx.draw_networkx_edges(G, pos, ax=ax1, arrows=True)
        nx.draw_networkx_nodes(G, pos, node_color='lightblue', 
                              node_size=700, ax=ax1)
        nx.draw_networkx_labels(G, pos, font_size=8, ax=ax1)
        ax1.set_title('Site Hierarchy Graph')
        ax1.axis('off')
        
        # Jobb oldal: Statisztika
        types = {}
        for site in sites.values():
            t = site['type']
            types[t] = types.get(t, 0) + 1
        
        ax2.bar(types.keys(), types.values(), color='steelblue')
        ax2.set_title('Sites by Type')
        ax2.set_ylabel('Count')
        ax2.tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        plt.savefig('custom_visualization.png', dpi=300, bbox_inches='tight')
        plt.show()
        
    except Exception as e:
        print(f"Hiba: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  OPCIÓ 6: Topológia analízis
# ═════════════════════════════════════════════════════════════════════════════

def example_topology_analysis():
    """Példa: Hálózati topológia elemzése."""
    
    try:
        import networkx as nx
        
        token = get_auth_token()
        data = get_site_hierarchy(token)
        sites = build_site_tree(data)
        G = build_graph(sites)
        
        print("\n*** TOPOLÓGIA ANALÍZIS ***\n")
        
        # Csomópontok
        print(f"Csomópontok (Sites): {G.number_of_nodes()}")
        
        # Élek
        print(f"Élek (Hierarchia): {G.number_of_edges()}")
        
        # Mélység
        roots = [n for n in G.nodes() if G.in_degree(n) == 0]
        print(f"Gyökér csomópontok: {len(roots)}")
        
        if roots:
            for root in roots:
                descendants = nx.descendants(G, root)
                print(f"  • {sites[root]['name']}: {len(descendants)+1} csomópont")
        
        # Leghosszabb út
        try:
            longest_path = nx.dag_longest_path(G) if nx.is_directed_acyclic_graph(G) else []
            if longest_path:
                print(f"\nLeghosszabb hierarchia út ({len(longest_path)} csomópont):")
                for node in longest_path:
                    print(f"  → {sites[node]['name']}")
        except:
            pass
        
    except Exception as e:
        print(f"Hiba: {e}")


# ═════════════════════════════════════════════════════════════════════════════
#  FUTTATÁSI SABLONOK
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════════╗
║  SITE HIERARCHY VISUALIZER – QUICK START SABLONOK               ║
╚════════════════════════════════════════════════════════════════╝

Válassz egy opciót:

  1) example_text_only()           → Csak szöveges output
  2) example_json_export()         → JSON exportálás
  3) example_custom_visualization()→ Testreszabott grafika
  4) example_topology_analysis()   → Topológia analízis
  5) example_programmatic_usage()  → Saját feldolgozás

Interaktív Python REPL-ben használd őket:

    python -i examples.py
    >>> example_text_only()
    >>> example_json_export()

Vagy szerkeszd ezt a fájlt és futtasd:

    python examples.py
(Szerkeszd a main()-t és válaszd ki a kívánt opciót)

Visszatérés az alap futtatáshoz:
    python site_hierarchy_visualizer.py
    """)
    
    # Válaszd ki melyiket szeretnéd futtatni:
    # example_text_only()
    # example_json_export()
    # example_topology_analysis()
    # example_programmatic_usage()
    # example_custom_visualization()
