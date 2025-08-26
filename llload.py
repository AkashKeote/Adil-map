#!/usr/bin/env python3
"""
llload.py — Integrated Mumbai evacuation map (final)

Requirements:
  pip install osmnx networkx pandas numpy geopandas folium shapely rapidfuzz

Place in same folder:
  - roads_all.graphml
  - mumbai_ward_area_floodrisk.csv  (columns like: Ward Code, Areas, Latitude, Longitude, Flood-risk_level)

Output:
  - mumbai_evacuation_routes.html
"""

# ----------------------------
# Imports (all at top)
# ----------------------------
import os
import json
import math
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox
import folium
from folium import GeoJson, PolyLine, CircleMarker
from folium.plugins import (
    MarkerCluster, MiniMap, Fullscreen, MeasureControl,
    MousePosition, LocateControl
)
from shapely.geometry import Point

# Fuzzy matching: rapidfuzz preferred, fallback to fuzzywuzzy, then difflib
try:
    from rapidfuzz import process as fuzzy_process  # preferred
except Exception:
    try:
        from fuzzywuzzy import process as fuzzy_process
    except Exception:
        import difflib
        class _DLProcess:
            @staticmethod
            def extractOne(query, choices):
                matches = difflib.get_close_matches(query, choices, n=1, cutoff=0)
                if matches:
                    score = int(difflib.SequenceMatcher(None, query, matches[0]).ratio() * 100)
                    return matches[0], score
                return None, 0
        fuzzy_process = _DLProcess()

# ----------------------------
# Config
# ----------------------------
GRAPHML = "roads_all.graphml"
CSV = "mumbai_ward_area_floodrisk.csv"
OUT_HTML = "mumbai_evacuation_routes.html"
PLACE = "Mumbai, India"
ASSUMED_SPEED_KMPH = 25.0       # for ETA
SAMPLE_FACTOR = 5               # sample 1/N edges for lighter HTML
MAX_POIS_PER_CAT = 500          # cap per category to keep HTML smaller
ROUTE_COUNT = 5                 # how many evacuation routes to draw

# Risk color map
RISK_COLOR = {
    "low": "#1a9850",
    "moderate": "#fc8d59",
    "high": "#d73027",
    "unknown": "#aaaaaa",
}

# POI categories: OSM tag -> (FontAwesome icon, folium color)
POI_CATEGORIES = {
    "hospital":       ({"amenity": "hospital"},       "plus-square",   "red"),
    "police":         ({"amenity": "police"},         "shield",        "darkblue"),
    "fire_station":   ({"amenity": "fire_station"},   "fire",          "orange"),
    "pharmacy":       ({"amenity": "pharmacy"},       "medkit",        "purple"),
    "school":         ({"amenity": "school"},         "graduation-cap","cadetblue"),
    "university":     ({"amenity": "university"},     "university",    "darkgreen"),
    "fuel":           ({"amenity": "fuel"},           "gas-pump",      "lightgray"),
    "shelter":        ({"emergency": "shelter"},      "home",          "green"),
    "bank":           ({"amenity": "bank"},           "bank",          "darkred"),
    "atm":            ({"amenity": "atm"},            "money-bill",    "darkred"),
    "restaurant":     ({"amenity": "restaurant"},     "utensils",      "beige"),
    "market":         ({"shop": "supermarket"},       "shopping-cart", "brown"),
    "water_tower":    ({"man_made": "water_tower"},   "tint",          "blue"),
    "bus_station":    ({"amenity": "bus_station"},    "bus",           "darkblue"),
    "train_station":  ({"railway": "station"},        "train",         "black"),
}

# ----------------------------
# Helpers
# ----------------------------
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    aliases = {
        "ward": "areas", "area": "areas", "region": "areas",
        "flood-risk_level": "flood_risk_level", "flood_risk": "flood_risk_level",
        "risk_level": "flood_risk_level", "risk": "flood_risk_level",
        "lat": "latitude", "y": "latitude",
        "lon": "longitude", "lng": "longitude", "x": "longitude",
    }
    for old, new in aliases.items():
        if old in df.columns and new not in df.columns:
            df.rename(columns={old: new}, inplace=True)
    required = ["areas", "latitude", "longitude", "flood_risk_level"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}. Found: {list(df.columns)}")
    df["areas"] = df["areas"].astype(str).str.strip().str.lower()
    df["flood_risk_level"] = df["flood_risk_level"].astype(str).str.strip().str.lower()
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    return df

def extract_best_match(query: str, choices):
    res = fuzzy_process.extractOne(query, choices)
    if res is None:
        return None, 0
    if isinstance(res, (tuple, list)) and len(res) >= 2:
        return res[0], int(res[1])
    return res, 100

def haversine_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    lon1 = np.radians(lon1); lat1 = np.radians(lat1)
    lon2 = np.radians(lon2); lat2 = np.radians(lat2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    return R * c

def route_length_m(G: nx.MultiDiGraph, route):
    # Robust length summation
    total = 0.0
    for u, v in zip(route[:-1], route[1:]):
        data = G.get_edge_data(u, v)
        if not data:
            continue
        best = min(data.values(), key=lambda d: d.get("length", float("inf")))
        total += float(best.get("length", 0.0))
    return total

def nearest_node(G, lon, lat):
    try:
        return ox.distance.nearest_nodes(G, X=lon, Y=lat)
    except Exception:
        # older alias
        return ox.nearest_nodes(G, X=lon, Y=lat)

# ----------------------------
# Load graph & CSV (once)
# ----------------------------
if not os.path.exists(GRAPHML):
    raise SystemExit(f"❌ Missing {GRAPHML} in current folder.")
if not os.path.exists(CSV):
    raise SystemExit(f"❌ Missing {CSV} in current folder.")

print("🚀 Loading road network (graphml)...")
G = ox.load_graphml(GRAPHML)
# ensure we work on the largest *weakly* connected component (so routes exist)
largest_cc_nodes = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest_cc_nodes).copy()
print(f"✅ Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

print("📄 Loading flood/regions CSV...")
flood_df_raw = pd.read_csv(CSV)
flood_df = normalize_columns(flood_df_raw)
regions = flood_df["areas"].tolist()
region_lons = flood_df["longitude"].to_numpy()
region_lats = flood_df["latitude"].to_numpy()
region_risks = flood_df["flood_risk_level"].tolist()
n_regions = len(regions)
print(f"✅ Regions: {n_regions}")

# ----------------------------
# Map: node -> nearest region (vectorized)
# ----------------------------
print("🔎 Assigning each graph node to nearest region...")
node_ids = np.array(list(G.nodes))
node_lons = np.array([G.nodes[n].get("x", G.nodes[n].get("lon")) for n in node_ids], dtype=float)
node_lats = np.array([G.nodes[n].get("y", G.nodes[n].get("lat")) for n in node_ids], dtype=float)

# distance matrix (regions x nodes)
dist_stack = np.empty((n_regions, len(node_ids)), dtype=float)
for i in range(n_regions):
    dist_stack[i] = haversine_m(region_lons[i], region_lats[i], node_lons, node_lats)

nearest_region_idx_per_node = np.argmin(dist_stack, axis=0)
nodeid_to_region_idx = dict(zip(node_ids.tolist(), nearest_region_idx_per_node.tolist()))

# ----------------------------
# Build sampled edges GeoJSON colored by risk (by origin node’s region)
# ----------------------------
print("🧱 Preparing risk-colored road layer...")
edges_gdf = ox.graph_to_gdfs(G, nodes=False, edges=True, fill_edge_geometry=True)
if "u" not in edges_gdf.columns or "v" not in edges_gdf.columns:
    edges_gdf = edges_gdf.reset_index()

edges_gdf["_u"] = edges_gdf["u"].astype(int)
edges_gdf["region_idx"] = edges_gdf["_u"].map(nodeid_to_region_idx)
edges_gdf["region_name"] = edges_gdf["region_idx"].apply(
    lambda i: regions[i] if (isinstance(i, (int, np.integer)) and 0 <= i < n_regions) else "unknown"
)
edges_gdf["risk_level"] = edges_gdf["region_idx"].apply(
    lambda i: region_risks[i] if (isinstance(i, (int, np.integer)) and 0 <= i < n_regions) else "unknown"
)

edges_gdf_sampled = edges_gdf.iloc[::SAMPLE_FACTOR].copy()
def edge_style(feature):
    risk = str(feature["properties"].get("risk_level", "unknown")).lower()
    color = RISK_COLOR.get(risk, RISK_COLOR["unknown"])
    return {"color": color, "weight": 1.2, "opacity": 0.8}

# ----------------------------
# Fetch POIs (cap per category)
# ----------------------------
print("📍 Fetching POIs (capped per category)...")
pois_by_cat = {}
for cat, (tag, icon, color) in POI_CATEGORIES.items():
    try:
        gdf = ox.features_from_place(PLACE, tag)
        if gdf is None or gdf.empty:
            pois_by_cat[cat] = None
            continue
        gdf = gdf.to_crs(epsg=4326)
        gdf["geometry"] = gdf.geometry.centroid
        if len(gdf) > MAX_POIS_PER_CAT:
            gdf = gdf.sample(MAX_POIS_PER_CAT, random_state=1)
        pois_by_cat[cat] = gdf
        print(f"  • {cat}: {len(gdf)}")
    except Exception as e:
        print(f"  ⚠️ {cat}: {e}")
        pois_by_cat[cat] = None
print("✅ POIs ready.")

# ----------------------------
# Route finder (k nearest low-risk)
# ----------------------------
def get_k_nearest_low_risk_routes(user_area: str, G, flood_df, k=ROUTE_COUNT):
    all_areas = flood_df["areas"].unique().tolist()
    best_match, score = extract_best_match(user_area.strip().lower(), all_areas)
    if not best_match or score < 50:
        return None, score, []

    start_row = flood_df[flood_df["areas"] == best_match].iloc[0]
    start_lat, start_lon = float(start_row["latitude"]), float(start_row["longitude"])
    orig_node = nearest_node(G, start_lon, start_lat)

    low_df = flood_df[flood_df["flood_risk_level"] == "low"]
    if low_df.empty:
        return best_match, score, []

    # precompute dijkstra distances
    try:
        dists = nx.single_source_dijkstra_path_length(G, orig_node, weight="length")
    except Exception:
        dists = {}

    # candidate destinations sorted by path distance
    candidates = []
    for _, row in low_df.iterrows():
        node = nearest_node(G, float(row["longitude"]), float(row["latitude"]))
        d = dists.get(node, None)
        if d is not None:
            candidates.append((row["areas"], node, d))
    if not candidates:
        return best_match, score, []

    candidates.sort(key=lambda x: x[2])

    # choose up to k distinct regions
    picked = []
    seen = set()
    for area, node, d in candidates:
        if area in seen:
            continue
        seen.add(area)
        picked.append((area, node, d))
        if len(picked) >= k:
            break

    routes = []
    for area, node, d in picked:
        try:
            path = nx.shortest_path(G, orig_node, node, weight="length")
            length_m = route_length_m(G, path)
            eta_min = (length_m / 1000.0) / max(ASSUMED_SPEED_KMPH, 1) * 60.0
            routes.append({
                "dest_region": area,
                "dest_node": int(node),
                "path": path,
                "distance_km": round(length_m / 1000.0, 3),
                "eta_min": round(eta_min, 1)
            })
        except Exception:
            continue

    return best_match, score, routes

# ----------------------------
# Map builder and saver
# ----------------------------
def build_and_save_map(start_region_name: str, routes: list, out_file: str):
    # center on start region
    idx = int(flood_df.index[flood_df["areas"] == start_region_name][0])
    center = [float(region_lats[idx]), float(region_lons[idx])]
    m = folium.Map(location=center, zoom_start=12, tiles=None, control_scale=True)

    # Base layers (enhanced tile options from alit.py)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer("cartodbpositron", name="Light", attr="© OpenStreetMap contributors © CARTO").add_to(m)
    folium.TileLayer("cartodbdark_matter", name="Dark", attr="© OpenStreetMap contributors © CARTO").add_to(m)
    folium.TileLayer("Stamen Terrain", name="Terrain", attr="Map tiles by Stamen Design, © OpenStreetMap").add_to(m)
    folium.TileLayer("Stamen Toner", name="Toner", attr="Map tiles by Stamen Design, © OpenStreetMap").add_to(m)

    # Enhanced map controls (from alit.py)
    MiniMap(toggle_display=True).add_to(m)
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="kilometers").add_to(m)
    MousePosition(position="bottomright", prefix="Lat/Lon: ").add_to(m)
    LocateControl(auto_start=False).add_to(m)

    # Risk-colored road layer (enhanced styling from alit.py)
    gj = GeoJson(
        data=edges_gdf_sampled.__geo_interface__,
        name="Roads (risk-colored, sampled)",
        style_function=lambda f: {"color": RISK_COLOR.get(str(f["properties"].get("risk_level","unknown")).lower(), "#9e9e9e"),
                                  "weight":1.2, "opacity":0.9},
        tooltip=folium.GeoJsonTooltip(
            fields=["region_name", "risk_level"],
            aliases=["Region", "Risk"],
            sticky=True
        ),
    )
    gj.add_to(m)

    # Region markers clustered (enhanced from alit.py)
    rc = MarkerCluster(name=f"Regions ({len(flood_df)})")
    for i, nm in enumerate(regions):
        color = RISK_COLOR.get(str(region_risks[i]).lower(), RISK_COLOR["unknown"])
        CircleMarker(
            location=[float(region_lats[i]), float(region_lons[i])],
            radius=5,
            color=color, fill=True, fill_opacity=0.9,
            tooltip=f"{nm.title()} — Risk: {str(region_risks[i]).title()}",
        ).add_to(rc)
    m.add_child(rc)

    # POI clusters (enhanced from alit.py)
    for cat, gdf in pois_by_cat.items():
        if gdf is None or gdf.empty:
            continue
        icon = POI_CATEGORIES[cat][1]
        color = POI_CATEGORIES[cat][2]
        cluster = MarkerCluster(name=f"{cat.replace('_',' ').title()} ({len(gdf)})")
        for _, row in gdf.iterrows():
            try:
                lat = float(row.geometry.y); lon = float(row.geometry.x)
            except Exception:
                continue
            popup_txt = str(row.get("name") or cat.replace("_", " ").title())
            folium.Marker(
                location=[lat, lon],
                icon=folium.Icon(color=color, icon=icon, prefix="fa"),
                popup=popup_txt
            ).add_to(cluster)
        m.add_child(cluster)

    # Draw routes (enhanced colors and styling from alit.py)
    colors = ["#0066ff","#00cc44","#ff8800","#aa00ff","#0099cc"]
    for i, r in enumerate(routes):
        coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in r["path"]]
        PolyLine(
            coords,
            color=colors[i % len(colors)],
            weight=6, opacity=0.9,
            tooltip=f"Route {i+1}: {r['distance_km']:.2f} km • {r['eta_min']:.0f} min → {r['dest_region'].title()}",
        ).add_to(m)

        # Add start marker for first route only
        if i == 0:
            start_node = r["path"][0]
            folium.CircleMarker(
                location=(G.nodes[start_node]["y"], G.nodes[start_node]["x"]),
                radius=7, color="#000", fill=True, fill_color="#ffffff",
                tooltip=f"Start: {start_region_name.title()}",
            ).add_to(m)

        # Add destination marker for each route
        dest_node = r["path"][-1]
        folium.CircleMarker(
            location=(G.nodes[dest_node]["y"], G.nodes[dest_node]["x"]),
            radius=7, color="#000", fill=True, fill_color="#ffd24d",
            tooltip=f"Destination: {r['dest_region'].title()}",
        ).add_to(m)

    # Calculate totals for summary panel
    totals = {"distance": 0.0, "eta": 0.0}
    for r in routes:
        totals["distance"] += r["distance_km"]
        totals["eta"] += r["eta_min"]

    # On-map summary panel
    routes_info = [{
        "dest_region": r["dest_region"].title(),
        "distance_km": round(r["distance_km"], 3),
        "eta_min": round(r["eta_min"], 1),
    } for r in routes]
    panel_html = (
        '<div id="evac-panel" style="position: fixed; bottom: 18px; left: 18px; z-index:9999;'
        'background: rgba(255,255,255,0.95); padding: 12px; border-radius:8px;'
        'box-shadow: 0 1px 8px rgba(0,0,0,0.2); max-width:340px; font-family: Arial, sans-serif;">'
        '<h4 style="margin:0 0 6px 0;">Evacuation Summary</h4>'
        '<div id="routes-list" style="font-size:13px; line-height:1.4;"></div>'
        '<hr style="margin:8px 0;">'
        '<div style="font-weight:600;">Totals:</div>'
        '<div id="totals" style="font-size:13px;"></div>'
        '<div style="margin-top:8px; font-size:12px; color:#444;">(ETA assumes ~25 km/h)</div>'
        '</div>'
        '<script>'
        'const routes = ' + json.dumps(routes_info) + ';'
        'function renderPanel(){'
        '  const el = document.getElementById("routes-list");'
        '  const t  = document.getElementById("totals");'
        '  el.innerHTML = "";'
        '  let d=0, e=0;'
        '  routes.forEach((r,i)=>{'
        '    d += r.distance_km; e += r.eta_min;'
        '    const div = document.createElement("div");'
        '    div.innerHTML = "<strong>Route "+(i+1)+":</strong> "+r.distance_km.toFixed(2)+" km — " +'
        '                    r.eta_min.toFixed(0)+" min → <em>"+r.dest_region+"</em>";'
        '    el.appendChild(div);'
        '  });'
        '  t.innerHTML = "<div>Total distance: <strong>"+d.toFixed(2)+" km</strong></div>" +'
        '                "<div>Combined ETA: <strong>"+e.toFixed(0)+" min</strong></div>";'
        '}'
        'renderPanel();'
        '</script>'
    )
    m.get_root().html.add_child(folium.Element(panel_html))

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_file)
    print(f"✅ Map saved to: {out_file}")

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    try:
        user_region = input("🏠 Enter your region name (area): ").strip()
    except EOFError:
        raise SystemExit("❌ No input provided.")
    if not user_region:
        raise SystemExit("❌ Empty input.")

    matched, score, routes = get_k_nearest_low_risk_routes(user_region, G, flood_df, k=ROUTE_COUNT)
    if not matched:
        print(f"❌ Could not match '{user_region}'. Try a different area name.")
        raise SystemExit(1)
    if not routes:
        print("⚠️ No safe evacuation routes found.")
        raise SystemExit(2)

    print(f"✅ Using region: {matched.title()} (match score {score}%)")
    for i, r in enumerate(routes, 1):
        print(f"  • Route {i}: to {r['dest_region'].title()} — {r['distance_km']:.2f} km, {r['eta_min']:.0f} min")

    build_and_save_map(matched, routes, OUT_HTML)
