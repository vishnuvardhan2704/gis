"""
DEBUG v3 — Fixed physical thresholds 0.3 / 0.6, RainMax=150, alpha=1.2
Verify 10mm vs 150mm distributions.
"""
import sys, os
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

print("=" * 60)
print("  DEBUG v3 — Fixed thresholds 0.3 / 0.6")
print(f"  RainMax={config.RAIN_MAX}, alpha={config.RAIN_ALPHA}")
print(f"  Thresholds: {config.RISK_THRESHOLDS}")
print("=" * 60)

initialize_ee()
lat, lon, radius_km = 17.385, 78.487, 5
aoi = create_aoi(lat, lon, radius_km)
ahp_weights = get_validated_weights()

# Terrain
dem = fetch_dem(aoi)
slope = compute_slope(dem)
clay, sand = fetch_soil(aoi)
elev_factor = normalize_elevation(dem, aoi)
slope_factor = normalize_slope(slope, aoi)
soil_factor = compute_soil_index(clay, sand)

# Hydrology
water_gdf = fetch_water_features(lat, lon, radius_km * 1000)
aoi_bounds_info = aoi.bounds().getInfo()["coordinates"][0]
lons = [p[0] for p in aoi_bounds_info]
lats = [p[1] for p in aoi_bounds_info]
bounds = (min(lons), min(lats), max(lons), max(lats))

river_array, water_mask_np, river_meta = compute_river_proximity(water_gdf, bounds)
river_factor_ee = numpy_to_ee_image(river_array, bounds, "river_factor")
water_mask_ee = numpy_to_ee_image(water_mask_np.astype(float), bounds, "water_mask")

dem_np = ee_image_to_numpy(dem, aoi)
flow_accum_raw = compute_flow_accumulation(dem_np)
flow_accum_norm = normalize_flow_accumulation(flow_accum_raw)
flow_accum_ee = numpy_to_ee_image(flow_accum_norm, bounds, "flow_accum_factor")

# BaseRisk
base_risk = compute_base_risk(
    elev_factor, slope_factor, soil_factor,
    river_factor=river_factor_ee,
    flow_accum_factor=flow_accum_ee,
    weights=ahp_weights,
)

br_stats = base_risk.reduceRegion(
    reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), sharedInputs=True),
    geometry=aoi, scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
).getInfo()
print(f"\nBaseRisk: {br_stats}")

# Test both scenarios
for rain_mm in [10, 150]:
    rf = (min(rain_mm / config.RAIN_MAX, 1.0)) ** config.RAIN_ALPHA
    print(f"\n{'='*50}")
    print(f"  Rain = {rain_mm}mm  |  RainFactor = {rf:.4f}")
    print(f"{'='*50}")

    fsi = apply_rainfall_multiplier(base_risk, rain_mm)
    fsi = apply_water_mask(fsi, water_mask_ee, rain_mm)

    fsi_stats = fsi.reduceRegion(
        reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), sharedInputs=True),
        geometry=aoi, scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
    ).getInfo()
    print(f"  FSI: {fsi_stats}")

    risk_class = classify_risk(fsi)

    total_pixels = risk_class.gte(0).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi,
        scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
    )
    t = ee.Number(total_pixels.values().get(0)).getInfo()

    for cls_val, cls_name in [(1, "Low"), (2, "Medium"), (3, "High")]:
        count = risk_class.eq(cls_val).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=aoi,
            scale=config.EXPORT_SCALE, maxPixels=config.MAX_PIXELS,
        )
        c = ee.Number(count.values().get(0)).getInfo()
        pct = (c / t * 100) if t > 0 else 0
        print(f"  {cls_name:8s}: {pct:5.1f}%")

print(f"\n{'='*60}")
print("  END DEBUG v3")
print(f"{'='*60}")
