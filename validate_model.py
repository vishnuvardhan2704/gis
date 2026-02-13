"""
Multi-Location Flood Model Validation
======================================
Tests 7 geographically distinct regions × 2 rainfall scenarios.
Prints structured summary table + per-location diagnostics.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

import config
from src.gee_data import initialize_ee, create_aoi, fetch_dem, compute_slope, fetch_soil, ee_image_to_numpy
from src.preprocessing import normalize_elevation, normalize_slope, compute_soil_index
from src.hydrology import (
    fetch_water_features, compute_river_proximity,
    compute_flow_accumulation, normalize_flow_accumulation,
    numpy_to_ee_image,
)
from src.ahp import get_validated_weights
from src.flood_model import compute_base_risk, apply_rainfall_multiplier, apply_water_mask, classify_risk
import ee
import numpy as np

# ── Test Locations ──────────────────────────────────────────────────────────
LOCATIONS = [
    {"name": "Varanasi (River Floodplain)",   "lat": 25.3176, "lon": 82.9739},
    {"name": "Chennai (Coastal Lowland)",      "lat": 13.0827, "lon": 80.2707},
    {"name": "Dehradun (Mountain Terrain)",    "lat": 30.3165, "lon": 78.0322},
    {"name": "Kolkata (Delta System)",         "lat": 22.5726, "lon": 88.3639},
    {"name": "Bengaluru (Urban Plateau)",      "lat": 12.9716, "lon": 77.5946},
    {"name": "Leh (High Mountain Desert)",     "lat": 34.1526, "lon": 77.5770},
    {"name": "Aluva (Known Flood Region)",     "lat": 10.1004, "lon": 76.3570},
]

RAINFALL_SCENARIOS = [10, 150]
RADIUS_KM = 10


def get_stats(image, aoi, band_name=None):
    """Get min/max/mean from an EE image over an AOI."""
    stats = image.reduceRegion(
        reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), sharedInputs=True),
        geometry=aoi,
        scale=config.EXPORT_SCALE,
        maxPixels=config.MAX_PIXELS,
    ).getInfo()
    return stats


def get_class_pct(risk_class, aoi, cls_val):
    """Get percentage of pixels in a given class."""
    count = risk_class.eq(cls_val).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi,
        scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
    )
    total = risk_class.gte(0).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi,
        scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
    )
    c = ee.Number(count.values().get(0)).getInfo()
    t = ee.Number(total.values().get(0)).getInfo()
    return (c / t * 100) if t > 0 else 0


def validate_location(loc, ahp_weights):
    """Run full validation for one location, returns results dict."""
    name = loc["name"]
    lat, lon = loc["lat"], loc["lon"]

    print(f"\n{'='*70}")
    print(f"  📍 {name}  ({lat}, {lon})")
    print(f"{'='*70}")

    aoi = create_aoi(lat, lon, RADIUS_KM)

    # Terrain
    dem = fetch_dem(aoi)
    slope = compute_slope(dem)
    clay, sand = fetch_soil(aoi)
    elev_factor = normalize_elevation(dem, aoi)
    slope_factor = normalize_slope(slope, aoi)
    soil_factor = compute_soil_index(clay, sand)

    # Hydrology
    try:
        water_gdf = fetch_water_features(lat, lon, RADIUS_KM * 1000)
    except Exception as e:
        print(f"  ⚠️  Water features failed: {e}")
        water_gdf = None

    aoi_bounds_info = aoi.bounds().getInfo()["coordinates"][0]
    lons = [p[0] for p in aoi_bounds_info]
    lats = [p[1] for p in aoi_bounds_info]
    bounds = (min(lons), min(lats), max(lons), max(lats))

    if water_gdf is not None and not water_gdf.empty:
        river_array, water_mask_np, river_meta = compute_river_proximity(water_gdf, bounds)
    else:
        import math
        mid_lat = (bounds[1] + bounds[3]) / 2
        deg_per_pixel_lon = config.EXPORT_SCALE / (111_320 * math.cos(math.radians(mid_lat)))
        deg_per_pixel_lat = config.EXPORT_SCALE / 111_320
        width = max(1, int((bounds[2] - bounds[0]) / deg_per_pixel_lon))
        height = max(1, int((bounds[3] - bounds[1]) / deg_per_pixel_lat))
        river_array = np.zeros((height, width), dtype=np.float32)
        water_mask_np = np.zeros((height, width), dtype=np.uint8)

    river_factor_ee = numpy_to_ee_image(river_array, bounds, "river_factor")
    water_mask_ee = numpy_to_ee_image(water_mask_np.astype(float), bounds, "water_mask")

    dem_np = ee_image_to_numpy(dem, aoi)
    flow_accum_raw = compute_flow_accumulation(dem_np)
    flow_accum_norm = normalize_flow_accumulation(flow_accum_raw)
    flow_accum_ee = numpy_to_ee_image(flow_accum_norm, bounds, "flow_accum_factor")

    # Factor diagnostics
    print(f"\n  ── Factor Diagnostics ──")
    for factor, label in [
        (river_factor_ee, "RiverFactor"),
        (flow_accum_ee, "FlowFactor"),
    ]:
        s = get_stats(factor, aoi)
        vals = list(s.values())
        print(f"    {label:15s}: min={vals[0]:.4f}  max={vals[1]:.4f}  mean={vals[2]:.4f}"
              f"  {'⚠️ CONSTANT' if abs(vals[1] - vals[0]) < 0.001 else '✅ varies'}")

    # BaseRisk
    base_risk = compute_base_risk(
        elev_factor, slope_factor, soil_factor,
        river_factor=river_factor_ee,
        flow_accum_factor=flow_accum_ee,
        weights=ahp_weights,
    )
    br = get_stats(base_risk, aoi)
    br_vals = list(br.values())
    print(f"    {'BaseRisk':15s}: min={br_vals[0]:.4f}  max={br_vals[1]:.4f}  mean={br_vals[2]:.4f}")

    # Rainfall scenarios
    results = []
    for rain_mm in RAINFALL_SCENARIOS:
        rf = (min(rain_mm / config.RAIN_MAX, 1.0)) ** config.RAIN_ALPHA
        fsi = apply_rainfall_multiplier(base_risk, rain_mm)
        fsi = apply_water_mask(fsi, water_mask_ee, rain_mm)

        fsi_stats = get_stats(fsi, aoi)
        fsi_vals = list(fsi_stats.values())

        risk_class = classify_risk(fsi)
        pct_low = get_class_pct(risk_class, aoi, 1)
        pct_med = get_class_pct(risk_class, aoi, 2)
        pct_high = get_class_pct(risk_class, aoi, 3)

        print(f"\n  ── Rain = {rain_mm}mm  (RainFactor = {rf:.4f}) ──")
        print(f"    FSI: min={fsi_vals[0]:.4f}  max={fsi_vals[1]:.4f}  mean={fsi_vals[2]:.4f}")
        print(f"    Low:  {pct_low:5.1f}%  |  Medium: {pct_med:5.1f}%  |  High: {pct_high:5.1f}%")

        results.append({
            "location": name,
            "rain_mm": rain_mm,
            "fsi_min": fsi_vals[0],
            "fsi_max": fsi_vals[1],
            "fsi_mean": fsi_vals[2],
            "pct_low": pct_low,
            "pct_med": pct_med,
            "pct_high": pct_high,
        })

    return results


def main():
    print("=" * 70)
    print("  MULTI-LOCATION FLOOD MODEL VALIDATION")
    print(f"  RainMax={config.RAIN_MAX}, alpha={config.RAIN_ALPHA}")
    print(f"  Thresholds: {config.RISK_THRESHOLDS}")
    print(f"  Radius: {RADIUS_KM} km")
    print("=" * 70)

    initialize_ee()
    ahp_weights = get_validated_weights()

    all_results = []
    for loc in LOCATIONS:
        try:
            results = validate_location(loc, ahp_weights)
            all_results.extend(results)
        except Exception as e:
            print(f"\n  ❌ FAILED: {loc['name']} – {e}")
            import traceback
            traceback.print_exc()

    # ── Summary Table ───────────────────────────────────────────────────────
    print(f"\n\n{'='*90}")
    print("  SUMMARY TABLE")
    print(f"{'='*90}")
    header = f"{'Location':35s} | {'Rain':>4s} | {'Mean FSI':>8s} | {'% Low':>6s} | {'% Med':>6s} | {'% High':>6s}"
    print(header)
    print("-" * len(header))

    for r in all_results:
        print(f"{r['location']:35s} | {r['rain_mm']:>3d}mm | {r['fsi_mean']:>8.4f} | "
              f"{r['pct_low']:>5.1f}% | {r['pct_med']:>5.1f}% | {r['pct_high']:>5.1f}%")

    # ── Quick Sanity Checks ─────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  SANITY CHECKS")
    print(f"{'='*70}")

    for loc_name in set(r["location"] for r in all_results):
        r10 = [r for r in all_results if r["location"] == loc_name and r["rain_mm"] == 10]
        r150 = [r for r in all_results if r["location"] == loc_name and r["rain_mm"] == 150]
        if r10 and r150:
            r10, r150 = r10[0], r150[0]
            increase = r150["fsi_mean"] - r10["fsi_mean"]
            ok = increase > 0
            ten_mostly_low = r10["pct_low"] > 90
            low_pct = r10["pct_low"]
            low_msg = "All Low ✅" if ten_mostly_low else f"{low_pct:.0f}% Low ⚠️"
            print(f"  {loc_name:35s}: ΔMeanFSI={increase:+.4f} {'✅' if ok else '❌'}  "
                  f"10mm→{low_msg}")

    print(f"\n{'='*70}")
    print("  VALIDATION COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
