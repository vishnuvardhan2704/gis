"""
Visualization Module – Interactive Folium/Leaflet 2D risk map.
"""

import os
import folium
import rasterio
import numpy as np
from folium.plugins import MiniMap

import config


def create_risk_map(
    center_lat: float,
    center_lon: float,
    risk_tif_path: str,
    road_graph=None,
    evac_route: list[tuple[float, float]] = None,
    shelters: list[dict] = None,
    chosen_shelter: dict = None,
    start_lat: float = None,
    start_lon: float = None,
) -> str:
    """
    Build a Folium map with:
      1. Flood risk raster overlay (green → yellow → red)
      2. Road network (grey lines)
      3. Evacuation route (blue dashed)
      4. Shelter markers
    Saves to output/ and returns the file path.
    """
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="CartoDB positron",
    )

    # ── 1. Risk raster overlay ───────────────────────────────────────────────
    _add_risk_overlay(m, risk_tif_path)

    # ── 2. Road network ─────────────────────────────────────────────────────
    if road_graph is not None:
        _add_road_layer(m, road_graph)

    # ── 3. Evacuation route ──────────────────────────────────────────────────
    if evac_route:
        folium.PolyLine(
            evac_route,
            color="#2196F3",
            weight=5,
            opacity=0.9,
            dash_array="10",
            tooltip="Safe Evacuation Route",
        ).add_to(m)

    # ── 4. Start point ───────────────────────────────────────────────────────
    if start_lat and start_lon:
        folium.Marker(
            [start_lat, start_lon],
            icon=folium.Icon(color="blue", icon="user", prefix="fa"),
            tooltip="Evacuation Start",
        ).add_to(m)

    # ── 5. Shelter markers ───────────────────────────────────────────────────
    if shelters:
        for sh in shelters:
            colour = "red" if (chosen_shelter and sh == chosen_shelter) else "green"
            folium.Marker(
                [sh["lat"], sh["lon"]],
                icon=folium.Icon(color=colour, icon="plus-sign"),
                tooltip=f"{sh['name']} ({sh['type']})",
            ).add_to(m)

    # ── Extras ───────────────────────────────────────────────────────────────
    MiniMap(toggle_display=True).add_to(m)
    folium.LayerControl().add_to(m)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, config.RISK_MAP_HTML)
    m.save(out_path)
    print(f"[VIS] Map saved → {out_path}")
    return out_path


# ── Private helpers ──────────────────────────────────────────────────────────

def _add_risk_overlay(m: folium.Map, tif_path: str):
    """Render the flood risk GeoTIFF as an ImageOverlay."""
    from matplotlib import cm
    from PIL import Image
    import io, base64

    with rasterio.open(tif_path) as src:
        band = src.read(1)
        bounds = src.bounds  # left, bottom, right, top

    # Normalise to [0, 1]
    vmin, vmax = np.nanmin(band), np.nanmax(band)
    if vmax - vmin > 0:
        norm = (band - vmin) / (vmax - vmin)
    else:
        norm = np.zeros_like(band)

    # Apply RdYlGn_r colourmap (red = high risk)
    cmap = cm.get_cmap("RdYlGn_r")
    rgba = cmap(norm)
    rgba[..., 3] = np.where(np.isnan(band), 0, 0.6)  # transparency

    img = Image.fromarray((rgba * 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()

    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{encoded}",
        bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
        opacity=0.6,
        name="Flood Risk",
    ).add_to(m)


def _add_road_layer(m: folium.Map, G):
    """Draw road edges as thin grey lines."""
    road_group = folium.FeatureGroup(name="Roads")
    for u, v, data in G.edges(data=True):
        pts = [
            (G.nodes[u]["y"], G.nodes[u]["x"]),
            (G.nodes[v]["y"], G.nodes[v]["x"]),
        ]
        risk = data.get("flood_risk", 0)
        color = "#e53935" if risk > 0.7 else "#ff9800" if risk > 0.4 else "#9e9e9e"
        folium.PolyLine(pts, color=color, weight=2, opacity=0.7).add_to(road_group)
    road_group.add_to(m)
