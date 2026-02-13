"""
Preprocessing Module – Normalise elevation, slope, and soil into [0, 1] factors.
"""

import ee
import config


def normalize_elevation(dem: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """
    Lower elevation → higher flood risk.
    Returns inverted min-max normalisation in [0, 1].
    """
    stats = dem.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=aoi,
        scale=config.EXPORT_SCALE,
        maxPixels=config.MAX_PIXELS,
    )
    elev_min = ee.Number(stats.get("elevation_min"))
    elev_max = ee.Number(stats.get("elevation_max"))

    normalized = dem.subtract(elev_min).divide(elev_max.subtract(elev_min))
    inverted = ee.Image(1).subtract(normalized).rename("elevation_factor")
    print("[PRE] Elevation normalised (inverted)")
    return inverted


def normalize_slope(slope: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """
    Flatter terrain → higher flood accumulation risk.
    Returns inverted min-max normalisation in [0, 1].
    """
    stats = slope.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=aoi,
        scale=config.EXPORT_SCALE,
        maxPixels=config.MAX_PIXELS,
    )
    slope_min = ee.Number(stats.get("slope_min"))
    slope_max = ee.Number(stats.get("slope_max"))

    normalized = slope.subtract(slope_min).divide(slope_max.subtract(slope_min))
    inverted = ee.Image(1).subtract(normalized).rename("slope_factor")
    print("[PRE] Slope normalised (inverted)")
    return inverted


def compute_soil_index(clay: ee.Image, sand: ee.Image) -> ee.Image:
    """
    Soil runoff index: higher clay fraction → more runoff → higher risk.
    soil_index = (clay/100 - sand/100) rescaled from [-1, 1] to [0, 1].
    """
    clay_norm = clay.divide(100)
    sand_norm = sand.divide(100)
    soil_factor = clay_norm.subtract(sand_norm).unitScale(-1, 1).rename("soil_factor")
    print("[PRE] Soil index computed")
    return soil_factor



def validate_range(image: ee.Image, aoi: ee.Geometry, label: str) -> dict:
    """Check that an image's values lie in [0, 1]."""
    stats = image.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=aoi,
        scale=config.EXPORT_SCALE,
        maxPixels=config.MAX_PIXELS,
    ).getInfo()
    print(f"[VAL] {label}: {stats}")
    return stats
