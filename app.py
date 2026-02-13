#!/usr/bin/env python3
"""
app.py – Flask web server for the Interactive Flood Susceptibility GUI.

Endpoints:
    GET  /                      → serves the single-page Leaflet app
    POST /api/analyze           → runs the 6-factor pipeline, returns results
    GET  /api/overlay/<job_id>  → serves the risk raster as a PNG
"""

import os
import sys
import json
import uuid
import copy
import traceback
import io
import base64
import threading
import requests as http_requests

import numpy as np
from flask import Flask, render_template, request, jsonify, send_file

# Ensure project root on path
sys.path.insert(0, os.path.dirname(__file__))

import config

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True


# Custom JSON encoder for numpy types
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, float) and np.isnan(obj):
            return None
        return super().default(obj)


app.json_encoder = NumpyEncoder


def _sanitize_for_json(obj):
    """Recursively convert numpy types to native Python for JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(i) for i in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if np.isnan(v) else v
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj

# In-memory job store  { job_id: { status, progress, result, error } }
jobs = {}
jobs_lock = threading.Lock()

# GEE initialised flag
_gee_ready = False


def _ensure_gee():
    """Lazy-init GEE once."""
    global _gee_ready
    if not _gee_ready:
        from src.gee_data import initialize_ee
        initialize_ee()
        _gee_ready = True


# ── Routes ──────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    Accepts JSON: { lat, lon, radius_km, rainfall_mm }
    Returns: { job_id } immediately, pipeline runs in background.
    """
    data = request.get_json(force=True)
    lat = float(data.get("lat", config.DEFAULT_LAT))
    lon = float(data.get("lon", config.DEFAULT_LON))
    radius_km = float(data.get("radius_km", 5))
    rainfall_mm = float(data.get("rainfall_mm", 150))

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {"status": "running", "progress": "Initialising...", "result": None, "error": None}

    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, lat, lon, radius_km, rainfall_mm),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    """Poll job progress."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Use json.dumps with NumpyEncoder for safety
    try:
        return app.response_class(
            response=json.dumps(job, cls=NumpyEncoder),
            mimetype='application/json',
        )
    except Exception as e:
        return jsonify({"status": job.get("status"), "progress": job.get("progress"), "error": str(e)})


@app.route("/api/overlay/<job_id>")
def risk_overlay(job_id):
    """Serve the risk PNG overlay for the given job."""
    png_path = os.path.join(config.OUTPUT_DIR, f"risk_overlay_{job_id}.png")
    if os.path.exists(png_path):
        return send_file(png_path, mimetype="image/png")
    return jsonify({"error": "Overlay not ready"}), 404


@app.route("/api/terrain3d/<job_id>")
def terrain3d_data(job_id):
    """Serve high-resolution DEM + FSI grids as JSON for professional 3D view."""
    import rasterio
    from scipy.ndimage import zoom

    risk_tif = os.path.join(config.OUTPUT_DIR, config.RISK_GEOTIFF)
    dem_tif = os.path.join(config.OUTPUT_DIR, "dem_terrain.tif")

    if not os.path.exists(risk_tif) or not os.path.exists(dem_tif):
        return jsonify({"error": "Data not ready"}), 404

    # High-resolution grid for smooth 3D terrain (professional GIS quality)
    DEM_GRID = 256  # 256×256 for smooth terrain surface
    FSI_GRID = 128  # 128×128 for color overlay (lower res is fine)

    with rasterio.open(dem_tif) as src:
        dem_band = src.read(1)
        bounds = src.bounds
        transform = src.transform

    with rasterio.open(risk_tif) as src:
        fsi_band = src.read(1)

    # High-res DEM with bicubic interpolation for smooth terrain
    dem_highres = zoom(dem_band, (DEM_GRID / dem_band.shape[0], DEM_GRID / dem_band.shape[1]), order=3)
    
    # Medium-res FSI with bilinear interpolation
    fsi_midres = zoom(fsi_band, (FSI_GRID / fsi_band.shape[0], FSI_GRID / fsi_band.shape[1]), order=1)

    # Replace NaN with 0
    dem_highres = np.nan_to_num(dem_highres, nan=0.0)
    fsi_midres = np.nan_to_num(fsi_midres, nan=0.0)

    # Compute elevation statistics for vertical scale reference
    dem_mean = float(np.mean(dem_highres[dem_highres > 0]))
    dem_std = float(np.std(dem_highres[dem_highres > 0]))

    # Get buildings + evac from the job result
    with jobs_lock:
        job = jobs.get(job_id, {})
    result = job.get("result", {}) or {}

    return app.response_class(
        response=json.dumps({
            "dem": dem_highres.tolist(),
            "fsi": fsi_midres.tolist(),
            "dem_rows": DEM_GRID,
            "dem_cols": DEM_GRID,
            "fsi_rows": FSI_GRID,
            "fsi_cols": FSI_GRID,
            "dem_min": float(np.nanmin(dem_highres)),
            "dem_max": float(np.nanmax(dem_highres)),
            "dem_mean": dem_mean,
            "dem_std": dem_std,
            "fsi_min": float(np.nanmin(fsi_midres)),
            "fsi_max": float(np.nanmax(fsi_midres)),
            "bounds": {
                "south": bounds.bottom, "west": bounds.left,
                "north": bounds.top, "east": bounds.right,
            },
            "buildings": result.get("buildings", []),
            "evacuation_route": result.get("evacuation_route"),
            "escape_destination": result.get("escape_destination"),
            "resolution_meters": config.EXPORT_SCALE,
        }, cls=NumpyEncoder),
        mimetype='application/json',
    )


# ── Pipeline runner ─────────────────────────────────────────────────────────


def _update_progress(job_id, msg):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["progress"] = msg


def _run_pipeline(job_id, lat, lon, radius_km, rainfall_mm):
    """Run the full 6-factor pipeline and store results."""
    try:
        _update_progress(job_id, "Connecting to Google Earth Engine...")
        _ensure_gee()

        import ee
        from src.gee_data import create_aoi, fetch_dem, compute_slope, fetch_soil, ee_image_to_numpy
        from src.preprocessing import (
            normalize_elevation, normalize_slope,
            compute_soil_index,
        )
        from src.hydrology import (
            fetch_water_features, compute_river_proximity,
            compute_flow_accumulation, normalize_flow_accumulation,
            numpy_to_ee_image,
        )
        from src.ahp import get_validated_weights
        from src.flood_model import (
            compute_base_risk, apply_rainfall_multiplier, apply_water_mask,
            classify_risk, export_geotiff,
        )
        from src.road_network import load_road_network, sample_risk_on_edges, penalize_flooded_edges, label_safe_nodes
        from src.evacuation import find_escape_route
        from src.decision_support import compute_risk_statistics, count_affected_roads

        # Phase 0: AHP Weights
        _update_progress(job_id, "Computing AHP weights...")
        ahp_weights = get_validated_weights()

        # Phase 1: AOI
        _update_progress(job_id, "Creating area of interest...")
        aoi = create_aoi(lat, lon, radius_km)

        # Phase 2: Terrain
        _update_progress(job_id, "Fetching terrain data from GEE...")
        dem = fetch_dem(aoi)
        slope = compute_slope(dem)
        clay, sand = fetch_soil(aoi)

        _update_progress(job_id, "Preprocessing terrain factors...")
        elev_factor = normalize_elevation(dem, aoi)
        slope_factor = normalize_slope(slope, aoi)
        soil_factor = compute_soil_index(clay, sand)

        # Phase 3: Hydrology
        _update_progress(job_id, "Fetching river data from OpenStreetMap...")
        water_gdf = fetch_water_features(lat, lon, radius_km * 1000)

        aoi_bounds_info = aoi.bounds().getInfo()["coordinates"][0]
        lons = [p[0] for p in aoi_bounds_info]
        lats = [p[1] for p in aoi_bounds_info]
        bounds = (min(lons), min(lats), max(lons), max(lats))

        _update_progress(job_id, "Computing river proximity & water mask...")
        river_array, water_mask_np, river_meta = compute_river_proximity(water_gdf, bounds)
        river_factor_ee = numpy_to_ee_image(river_array, bounds, "river_factor")
        water_mask_ee = numpy_to_ee_image(water_mask_np.astype(float), bounds, "water_mask")

        _update_progress(job_id, "Computing flow accumulation...")
        dem_np = ee_image_to_numpy(dem, aoi)
        flow_accum_raw = compute_flow_accumulation(dem_np)
        flow_accum_norm = normalize_flow_accumulation(flow_accum_raw)
        flow_accum_ee = numpy_to_ee_image(flow_accum_norm, bounds, "flow_accum_factor")

        # Phase 4: BaseRisk × RainFactor
        _update_progress(job_id, "Computing base susceptibility (5-factor)...")
        base_risk = compute_base_risk(
            elev_factor, slope_factor, soil_factor,
            river_factor=river_factor_ee,
            flow_accum_factor=flow_accum_ee,
            weights=ahp_weights,
        )

        _update_progress(job_id, f"Applying rainfall multiplier ({rainfall_mm}mm)...")
        fsi = apply_rainfall_multiplier(base_risk, rainfall_mm)
        fsi = apply_water_mask(fsi, water_mask_ee, rainfall_mm)
        risk_classified = classify_risk(fsi)

        risk_tif = export_geotiff(fsi, aoi, config.RISK_GEOTIFF)
        dem_tif = export_geotiff(dem, aoi, "dem_terrain.tif")
        export_geotiff(risk_classified, aoi, "flood_risk_classified.tif")

        # Generate risk overlay PNG
        _update_progress(job_id, "Generating risk map overlay...")
        overlay_data = _create_risk_png(risk_tif, job_id, dem_tif_path=dem_tif)

        # Phase 5: Fetch buildings from OSM Overpass
        _update_progress(job_id, "Fetching buildings from OpenStreetMap...")
        buildings_data = []
        try:
            buildings_data = _fetch_buildings(bounds)
            print(f"[APP] Fetched {len(buildings_data)} buildings from OSM")
        except Exception as e:
            print(f"[APP] Building fetch failed: {e}")

        # Phase 6: Roads + Flood Escape Routing
        _update_progress(job_id, "Analysing road network...")
        road_geojson = None
        evac_geojson = None
        escape_dest = None
        road_stats = None

        try:
            road_graph = load_road_network(lat, lon, radius_km * 1000)
            road_graph = sample_risk_on_edges(road_graph, risk_tif)

            # Extract road GeoJSON for frontend
            road_geojson = _roads_to_geojson(road_graph)
            road_stats = count_affected_roads(road_graph)

            _update_progress(job_id, "Computing escape route to safe zone...")
            road_graph_safe = penalize_flooded_edges(copy.deepcopy(road_graph))
            road_graph_safe = label_safe_nodes(road_graph_safe, risk_tif)

            evac_route, escape_dest = find_escape_route(
                road_graph_safe, lat, lon
            )
            if evac_route:
                evac_geojson = _route_to_geojson(evac_route)
        except Exception as e:
            print(f"[APP] Road analysis failed: {e}")
            import traceback; traceback.print_exc()

        # Phase 7: Statistics + Impact
        _update_progress(job_id, "Computing risk statistics...")
        risk_stats = compute_risk_statistics(risk_tif)
        impact_stats = _compute_impact_stats(buildings_data, risk_tif)

        # Assemble result
        result = {
            "bounds": {
                "south": bounds[1], "west": bounds[0],
                "north": bounds[3], "east": bounds[2],
            },
            "overlay_url": f"/api/overlay/{job_id}",
            "risk_stats": risk_stats,
            "road_stats": road_stats,
            "roads": road_geojson,
            "evacuation_route": evac_geojson,
            "escape_destination": escape_dest,
            "buildings": buildings_data,
            "impact_stats": impact_stats,
            "params": {
                "lat": lat, "lon": lon,
                "radius_km": radius_km,
                "rainfall_mm": rainfall_mm,
            },
        }

        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = "Complete"
            jobs[job_id]["result"] = _sanitize_for_json(result)

    except Exception as e:
        traceback.print_exc()
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["progress"] = f"Error: {e}"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_risk_png(risk_tif_path, job_id, dem_tif_path=None):
    """
    Convert risk GeoTIFF to a smooth, high-quality PNG overlay.

    Enhancements (visualization only – model stays at 250m):
    1. Bilinear 4× upsampling for smooth pixels
    2. Hillshade underlay from DEM for terrain context
    3. Custom green → yellow → red color ramp
    4. 65% FSI opacity blended over hillshade
    """
    import rasterio
    from matplotlib.colors import LinearSegmentedColormap
    from PIL import Image
    from scipy.ndimage import zoom

    UPSAMPLE = 4  # 4× bilinear upsampling (250m → ~63m visual)

    # ── Read risk raster ────────────────────────────────────────────────
    with rasterio.open(risk_tif_path) as src:
        band = src.read(1)
        bounds = src.bounds

    # Bilinear upsample
    band_up = zoom(band, UPSAMPLE, order=1)  # order=1 = bilinear

    # Normalize FSI to [0, 1]
    vmin, vmax = np.nanmin(band_up), np.nanmax(band_up)
    if vmax - vmin > 0:
        norm = (band_up - vmin) / (vmax - vmin)
    else:
        norm = np.zeros_like(band_up)

    # ── Smooth green → yellow → red color ramp ─────────────────────────
    colors = [
        (0.18, 0.80, 0.25),   # green  (safe)
        (0.55, 0.90, 0.20),   # lime
        (1.00, 0.92, 0.23),   # yellow (moderate)
        (1.00, 0.60, 0.15),   # orange
        (0.90, 0.20, 0.15),   # red    (danger)
    ]
    cmap = LinearSegmentedColormap.from_list("flood_risk", colors, N=256)
    rgba = cmap(norm)

    # ── Hillshade from DEM ──────────────────────────────────────────────
    if dem_tif_path and os.path.exists(dem_tif_path):
        try:
            with rasterio.open(dem_tif_path) as src:
                dem_band = src.read(1)

            dem_up = zoom(dem_band, UPSAMPLE, order=1)

            # Compute hillshade (azimuth=315°, altitude=45°)
            dy, dx = np.gradient(dem_up)
            slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
            aspect = np.arctan2(-dy, dx)
            az = np.radians(315)
            alt = np.radians(45)
            hillshade = (
                np.sin(alt) * np.cos(slope_rad)
                + np.cos(alt) * np.sin(slope_rad) * np.cos(az - aspect)
            )
            hillshade = np.clip(hillshade, 0, 1)

            # Blend: FSI color at 65% over hillshade at 35%
            fsi_opacity = 0.65
            for c in range(3):
                rgba[..., c] = (
                    fsi_opacity * rgba[..., c]
                    + (1 - fsi_opacity) * hillshade
                )
            print("[VIZ] Hillshade blended with risk overlay")
        except Exception as e:
            print(f"[VIZ] Hillshade skipped: {e}")

    # Set alpha: transparent where NaN, 65% elsewhere
    rgba[..., 3] = np.where(np.isnan(band_up), 0, 0.65)

    img = Image.fromarray((rgba * 255).astype(np.uint8))

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    png_path = os.path.join(config.OUTPUT_DIR, f"risk_overlay_{job_id}.png")
    img.save(png_path, format="PNG")
    print(f"[VIZ] Overlay PNG saved ({img.size[0]}×{img.size[1]}) → {png_path}")
    return png_path


def _roads_to_geojson(G):
    """Convert networkx road graph to GeoJSON FeatureCollection."""
    features = []
    for u, v, data in G.edges(data=True):
        risk = data.get("flood_risk", 0.0)
        feat = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [G.nodes[u]["x"], G.nodes[u]["y"]],
                    [G.nodes[v]["x"], G.nodes[v]["y"]],
                ],
            },
            "properties": {"risk": round(risk, 3)},
        }
        features.append(feat)
    return {"type": "FeatureCollection", "features": features}


def _fetch_buildings(bounds):
    """
    Fetch building footprints from OSM Overpass API within the given bounds.
    Returns list of {lat, lon, type, floors, name}.
    """
    south, west, north, east = bounds[1], bounds[0], bounds[3], bounds[2]
    query = f'[out:json][timeout:15];(way["building"]({south},{west},{north},{east}););out center qt 150;'
    try:
        resp = http_requests.get(
            f'https://overpass-api.de/api/interpreter?data={query}',
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[BLDG] Overpass query failed: {e}")
        return []

    pop_per_floor = {'residential': 4, 'commercial': 10, 'hospital': 50, 'school': 30}
    buildings = []
    for el in data.get('elements', []):
        center = el.get('center')
        if not center or 'lat' not in center or 'lon' not in center:
            continue
        tags = el.get('tags', {})
        bt = tags.get('building', '')
        am = tags.get('amenity', '')
        # Classify type
        if am == 'hospital' or bt == 'hospital':
            btype = 'hospital'
        elif am in ('school', 'university', 'college') or bt == 'school':
            btype = 'school'
        elif bt in ('commercial', 'retail', 'office', 'industrial', 'warehouse'):
            btype = 'commercial'
        else:
            btype = 'residential'
        floors = 1
        try:
            floors = int(tags.get('building:levels', '1'))
        except (ValueError, TypeError):
            floors = {'commercial': 3, 'hospital': 4, 'school': 2}.get(btype, 1)
        pop = pop_per_floor.get(btype, 4) * floors
        buildings.append({
            'lat': center['lat'],
            'lon': center['lon'],
            'type': btype,
            'floors': floors,
            'name': tags.get('name'),
            'pop': pop,
        })
    return buildings


def _compute_impact_stats(buildings, risk_tif_path):
    """Cross-reference buildings with FSI raster to compute impact stats."""
    import rasterio

    if not buildings or not os.path.exists(risk_tif_path):
        return {'total_buildings': len(buildings), 'at_risk': 0, 'high_risk': 0,
                'population_at_risk': 0, 'critical_facilities': 0}

    with rasterio.open(risk_tif_path) as src:
        transform = src.transform
        band = src.read(1)
        rows, cols = band.shape

    at_risk = 0
    high_risk = 0
    pop_at_risk = 0
    critical = 0

    for b in buildings:
        col_idx, row_idx = ~transform * (b['lon'], b['lat'])
        row_idx, col_idx = int(round(row_idx)), int(round(col_idx))
        if 0 <= row_idx < rows and 0 <= col_idx < cols:
            fsi = float(band[row_idx, col_idx])
        else:
            fsi = 0.0
        b['fsi'] = round(fsi, 3)
        if fsi >= 0.33:
            at_risk += 1
            pop_at_risk += b.get('pop', 0)
            if fsi >= 0.66:
                high_risk += 1
        if b['type'] in ('hospital', 'school') and fsi >= 0.33:
            critical += 1

    return {
        'total_buildings': len(buildings),
        'at_risk': at_risk,
        'high_risk': high_risk,
        'population_at_risk': pop_at_risk,
        'critical_facilities': critical,
    }


def _route_to_geojson(route_coords):
    """Convert evacuation route [(lat,lon), ...] to GeoJSON."""
    coords = [[lon, lat] for lat, lon in route_coords]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"type": "evacuation_route"},
    }


if __name__ == "__main__":
    print("🌊 Flood Susceptibility GUI starting...")
    print("   Open http://localhost:5050 in your browser")
    app.run(debug=False, port=5050, threaded=True)
