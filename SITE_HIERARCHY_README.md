# Cisco Catalyst Center – Site Hierarchy Visualizer

## Leírás
Ez a Python script csatlakozik a Cisco Catalyst Center (DNAC) `10.8.11.100` címhez és megjeleníti a Site hierarchiát **grafikus formában**.

## Funkciók
- ✅ Automatikus authentikáció (JWT token alapú)
- ✅ Site hierarchia lekérése a DNAC API-ból
- ✅ Szöveges hierarchia megjelenítés
- ✅ **Grafikus megjelenítés** (NetworkX + Matplotlib)
- ✅ Site típusok szerinti szín-kódolás (Area, Building, Floor, Zone)
- ✅ Statisztikák és összefoglalás
- ✅ PNG formátumban ábra export

## Előfeltételek

1. **Python 3.8+** szükséges
2. **Csatlakozás** a DNAC rendszerhez (IP: `10.8.11.100`)
3. **Érvényes DNAC felhasználónév és jelszó**

## Telepítés

### 1. Függőségek telepítése
```powershell
pip install -r requirements.txt
```

Vagy manuálisan:
```powershell
pip install requests urllib3 networkx matplotlib numpy
```

### 2. Bejelentkezési adatok beállítása
Szerkeszd meg a `site_hierarchy_visualizer.py` fájl **16-19. sorait**:

```python
DNAC_HOST     = "10.8.11.100"      # Cisco Catalyst Center IP (változtatás lehetséges)
DNAC_PORT     = 443                # HTTPS port
DNAC_USER     = "admin"            # ← módosítsd a tényleges felhasználónévre
DNAC_PASSWORD = "Cisco123!"        # ← módosítsd a tényleges jelszóra
```

## Futtatás

### Windows PowerShell:
```powershell
python site_hierarchy_visualizer.py
```

### Vagy explicit Python3:
```powershell
python3 site_hierarchy_visualizer.py
```

## Kimenet

A script a következőket eredményezi:

### 1. **Konzol kimenet** (szöveges hierarchia + statisztika)
```
CISCO CATALYST CENTER – SITE HIERARCHY VISUALIZER

[*] Csatlakozás: https://10.8.11.100:443/dna/system/api/v1/auth/token
[✓] Authentikáció sikeres.

[*] Site hierarchia lekérése...
[*] Megpróbálom: /dna/intent/api/v1/site-hierarchy
[✓] Site adatok lekérve...

├── Global Site
    ├── Area 1
        ├── Building 1
            ├── Floor 1
                ├── Zone A
```

### 2. **Grafikus ábra** (`site_hierarchy.png`)
- Automtikus mentés a munkakönyvtárban
- 300 DPI PNG formátum
- Szín-kódolt csomópontok (Area, Building, Floor, Zone)
- Hierarchikus layout
- Automatikus megjelenítés az alapértelmezett böngészőben

## API Végpontok

A script az alábbi DNAC API végpontokat próbálja meg:

| Végpont | Leírás |
|---------|--------|
| `/dna/intent/api/v1/site-hierarchy` | Teljes site hierarchia |
| `/dna/intent/api/v1/site` | Einzelnes site adatok |
| `/api/v1/sites` | Alternatív site végpont |

## Hibaelhárítás

### "Kapcsolódási hiba: nem érhető el a 10.8.11.100 cím"
- Ellenőrizd az IP cím helyességét
- Ellenőrizd az HTTPS csatlakozást (port 443)
- Tűzfal/VPN beállítások ellenőrzése

### "HTTP hiba: 401"
- Ellenőrizd a felhasználónevet és jelszót
- Ellenőrizd a DNAC authentikációs engedélyeket

### "Nem sikerült lekérni a site hierarchiát"
- Előfordulhat, hogy még nincs site definiálva a DNAC-ben
- Ellenőrizd az API verzióját (a végpontok verziófüggőek lehetnek)

## Fejlesztési lehetőségek

- [ ] Interaktív grafikon (zoom, pan, node kattintás)
- [ ] Eszközök és interfészek hozzáadása
- [ ] CSV/JSON export
- [ ] Web alapú megjelenítés (Flask/Streamlit)
- [ ] Real-time frissítés
- [ ] Többnyelvű felület

## Szerzői jog

**SOTE DANC Project** | Cisco Catalyst Center Integráció

---

**Utolsó frissítés:** 2026. március  
**Verzió:** 1.0
