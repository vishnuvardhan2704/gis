#!/usr/bin/env python3
"""
main.py – CLI entry point for the Flood Susceptibility & Evacuation System.

Usage:
    python main.py --lat 17.385 --lon 78.4867 --radius 10 --rainfall 150

The pipeline:
    1. Authenticate & initialise GEE
    2. Fetch DEM + soil data, preprocess terrain factors
    3. Fetch water features, compute river proximity & flow accumulation
    4. Compute 6-factor MCDA flood risk → export GeoTIFF
    5. Load OSM road network → overlay risk
    6. Find shelters → compute A* safe route
    7. Generate interactive Folium map
    8. Print situation report
"""

import argparse
import sys
import os
import copy

# Ensure project root is on the path so `import config` works
sys.path.insert(0, os.path.dirname(__file__))

import config
from src.gee_data import initialize_ee, create_aoi, fetch_dem, compute_slope, fetch_soil
from src.preprocessing import (
    normalize_elevation,
    normalize_slope,
    compute_soil_index,
    validate_range,
)
from src.hydrology import (
    fetch_water_features,
    compute_river_proximity,
    compute_flow_accumulation,
    normalize_flow_accumulation,
    numpy_to_ee_image,
)
from src.ahp import get_validated_weights
from src.flood_model import (
    compute_base_risk, apply_rainfall_multiplier, apply_water_mask,
    classify_risk, export_geotiff,
)
from src.road_network import load_road_network, sample_risk_on_edges, penalize_flooded_edges
from src.evacuation import find_shelters, find_best_route
from src.visualization import create_risk_map
from src.decision_support import compute_risk_statistics, count_affected_roads, generate_report


def parse_args():
    p = argparse.ArgumentParser(
        description="AI-Driven Flood Susceptibility & Evacuation Decision Support System",
    )
    p.add_argument("--lat", type=float, default=config.DEFAULT_LAT, help="Latitude of centre")
    p.add_argument("--lon", type=float, default=config.DEFAULT_LON, help="Longitude of centre")
    p.add_argument("--radius", type=float, default=config.DEFAULT_RADIUS_KM, help="Radius in km")
    p.add_argument("--rainfall", type=float, default=150.0, help="Rainfall scenario in mm")
    p.add_argument("--start-lat", type=float, default=None, help="Evacuation start latitude")
    p.add_argument("--start-lon", type=float, default=None, help="Evacuation start longitude")
    p.add_argument("--skip-roads", action="store_true", help="Skip road & evacuation analysis")
    return p.parse_args()


def main():
    args = parse_args()

    start_lat = args.start_lat or args.lat
    start_lon = args.start_lon or args.lon

    print("=" * 60)
    print("  FLOOD SUSCEPTIBILITY & EVACUATION SYSTEM  (AHP 6-Factor)")
    print("=" * 60)
    print(f"  Centre: ({args.lat}, {args.lon})")
    print(f"  Radius: {args.radius} km")
    print(f"  Rainfall scenario: {args.rainfall} mm")
    print("=" * 60)

    # ── Phase 0: AHP Weight Derivation ──────────────────────────────────
    print("\n▶ Phase 0 – AHP Weight Derivation")
    ahp_weights = get_validated_weights()

    # ── Phase 1: GEE Setup ──────────────────────────────────────────────
    print("\n▶ Phase 1 – GEE Initialisation")
    initialize_ee()
    aoi = create_aoi(args.lat, args.lon, args.radius)

    # ── Phase 2: Data Fetch + Terrain Preprocessing ─────────────────────
    print("\n▶ Phase 2 – Terrain Data & Preprocessing")
    dem = fetch_dem(aoi)
    slope = compute_slope(dem)
    clay, sand = fetch_soil(aoi)

    elev_factor = normalize_elevation(dem, aoi)
    slope_factor = normalize_slope(slope, aoi)
    soil_factor = compute_soil_index(clay, sand)

    # Validate each factor (Step A of debugging checklist)
    print("\n▶ Factor Validation (Step A)")
    validate_range(elev_factor, aoi, "elevation_factor")
    validate_range(slope_factor, aoi, "slope_factor")
    validate_range(soil_factor, aoi, "soil_factor")

    # ── Phase 3: Hydrology ──────────────────────────────────────────
    print("\n▶ Phase 3 – Hydrological Features")

    # 3A: River proximity + water mask
    water_gdf = fetch_water_features(args.lat, args.lon, args.radius * 1000)

    # Get AOI bounds for rasterization
    aoi_bounds_info = aoi.bounds().getInfo()["coordinates"][0]
    lons = [p[0] for p in aoi_bounds_info]
    lats = [p[1] for p in aoi_bounds_info]
    bounds = (min(lons), min(lats), max(lons), max(lats))

    river_array, water_mask_np, river_meta = compute_river_proximity(water_gdf, bounds)
    river_factor_ee = numpy_to_ee_image(river_array, bounds, "river_factor")
    water_mask_ee = numpy_to_ee_image(water_mask_np.astype(float), bounds, "water_mask")

    # 3B: Flow accumulation from DEM
    from src.gee_data import ee_image_to_numpy
    dem_np = ee_image_to_numpy(dem, aoi)
    flow_accum_raw = compute_flow_accumulation(dem_np)
    flow_accum_norm = normalize_flow_accumulation(flow_accum_raw)
    flow_accum_ee = numpy_to_ee_image(flow_accum_norm, bounds, "flow_accum_factor")

    # Validate hydrology factors
    validate_range(river_factor_ee, aoi, "river_factor")
    validate_range(flow_accum_ee, aoi, "flow_accum_factor")

    # ── Phase 4: Flood Risk Model (BaseRisk × RainFactor) ──────────────
    print("\n▶ Phase 4 – Flood Risk Model (BaseRisk × RainFactor)")

    # Step 1: Compute 5-factor base susceptibility (no rainfall)
    base_risk = compute_base_risk(
        elev_factor, slope_factor, soil_factor,
        river_factor=river_factor_ee,
        flow_accum_factor=flow_accum_ee,
        weights=ahp_weights,
    )
    validate_range(base_risk, aoi, "base_risk (before rain)")

    # Step 2: Apply rainfall multiplier
    fsi = apply_rainfall_multiplier(base_risk, args.rainfall)
    validate_range(fsi, aoi, f"FSI (rain={args.rainfall}mm)")

    # Step 3: Conditional water body forcing
    fsi = apply_water_mask(fsi, water_mask_ee, args.rainfall)

    # Adaptive classification (thresholds relative to MaxFSI)
    risk_classified = classify_risk(fsi)

    risk_tif = export_geotiff(fsi, aoi, config.RISK_GEOTIFF)
    export_geotiff(risk_classified, aoi, "flood_risk_classified.tif")

    # ── Phase 5-6: Roads & Evacuation ───────────────────────────────────
    road_graph = None
    shelters = []
    evac_route = None
    chosen_shelter = None
    road_stats = None

    if not args.skip_roads:
        print("\n▶ Phase 5 – Road Network Analysis")
        try:
            road_graph = load_road_network(args.lat, args.lon, args.radius * 1000)
            road_graph = sample_risk_on_edges(road_graph, risk_tif)

            print("\n▶ Phase 6 – Evacuation Routing")
            shelters = find_shelters(args.lat, args.lon, args.radius * 1000)

            # Penalise after sampling (for routing only, keep original for stats)
            road_graph_original = copy.deepcopy(road_graph)
            road_graph_safe = penalize_flooded_edges(copy.deepcopy(road_graph))

            if shelters:
                evac_route, chosen_shelter = find_best_route(
                    road_graph_safe, start_lat, start_lon, shelters
                )

            road_stats = count_affected_roads(road_graph_original)
        except Exception as e:
            print(f"[WARN] Road/evacuation analysis failed: {e}")
            print("       Continuing with risk map only...")

    # ── Phase 7: Visualization ──────────────────────────────────────────
    print("\n▶ Phase 7 – Visualization")
    map_path = create_risk_map(
        center_lat=args.lat,
        center_lon=args.lon,
        risk_tif_path=risk_tif,
        road_graph=road_graph,
        evac_route=evac_route,
        shelters=shelters,
        chosen_shelter=chosen_shelter,
        start_lat=start_lat,
        start_lon=start_lon,
    )

    # ── Phase 8: Decision Support ───────────────────────────────────────
    print("\n▶ Phase 8 – Decision Support Summary")
    risk_stats = compute_risk_statistics(risk_tif)
    report = generate_report(
        risk_stats=risk_stats,
        road_stats=road_stats,
        shelters=shelters,
        chosen_shelter=chosen_shelter,
        evac_route_len=len(evac_route) if evac_route else 0,
        params={
            "lat": args.lat,
            "lon": args.lon,
            "radius_km": args.radius,
            "rainfall_mm": args.rainfall,
        },
    )

    print("\n" + "=" * 60)
    print("  ✅  Pipeline complete!")
    print(f"  📄  GeoTIFF        → {risk_tif}")
    print(f"  🗺️   Interactive map → {map_path}")
    print(f"  📊  Report         → {os.path.join(config.OUTPUT_DIR, config.REPORT_JSON)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
