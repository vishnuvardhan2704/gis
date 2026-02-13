"""
Flood Risk Model – BaseRisk × RainFactor with adaptive classification.

Model:
    BaseRisk(x) = w1·Elev + w2·Slope + w3·Soil + w4·River + w5·Flow
    RainFactor  = (Rain / RainMax) ^ alpha
    FSI(x)      = clamp(BaseRisk(x) × RainFactor, 0, 1)

Classification uses adaptive thresholds relative to the scenario's max risk,
so the gradient is always visible regardless of rainfall magnitude.
"""

import os
import ee
import config


def compute_base_risk(
    elevation_factor: ee.Image,
    slope_factor: ee.Image,
    soil_factor: ee.Image,
    river_factor: ee.Image = None,
    flow_accum_factor: ee.Image = None,
    weights: dict = None,
) -> ee.Image:
    """
    Compute spatial base susceptibility (5 factors, NO rainfall).

    BaseRisk = w1·Elev + w2·Slope + w3·Soil + w4·Flow + w5·RiverEffective

    where RiverEffective = RiverFactor × SlopeFactor
    (river influence is dampened on steep slopes – steep valleys drain fast).

    All inputs must be [0, 1].  Weights must sum to 1.
    """
    w = weights or config.WEIGHTS

    risk = (
        elevation_factor.multiply(w["elevation"])
        .add(slope_factor.multiply(w["slope"]))
        .add(soil_factor.multiply(w["soil"]))
    )

    if river_factor is not None:
        # Slope-dampened river: strong only where terrain is flat
        river_effective = river_factor.multiply(slope_factor)
        risk = risk.add(river_effective.multiply(w["river"]))
        print("[MODEL] River factor dampened by slope (RiverEffective = River × Slope)")

    if flow_accum_factor is not None:
        risk = risk.add(flow_accum_factor.multiply(w["flow_accum"]))

    risk = risk.rename("base_risk")

    print(f"[MODEL] Base susceptibility computed – weights: {w}")
    return risk


def apply_rainfall_multiplier(
    base_risk: ee.Image,
    rainfall_mm: float,
    rain_max: float = None,
    alpha: float = None,
) -> ee.Image:
    """
    Scale base susceptibility by a nonlinear rainfall multiplier.

    RainFactor = (Rain / RainMax) ^ alpha
    FSI = clamp(BaseRisk × RainFactor, 0, 1)
    """
    rain_max = rain_max or config.RAIN_MAX
    alpha = alpha or config.RAIN_ALPHA

    rain_ratio = min(rainfall_mm / rain_max, 1.0)
    rain_factor = rain_ratio ** alpha

    print(f"[MODEL] Rainfall multiplier: ({rainfall_mm}/{rain_max})^{alpha} = {rain_factor:.4f}")

    fsi = base_risk.multiply(rain_factor).min(1.0).max(0.0).rename("flood_risk")
    return fsi


def apply_water_mask(fsi: ee.Image, water_mask: ee.Image, rainfall_mm: float) -> ee.Image:
    """
    Force water body pixels to high risk ONLY if rainfall exceeds
    a meaningful threshold. Light rain over a lake isn't a flood.
    """
    extreme_threshold = config.RAIN_MAX * 0.3  # 30% of design storm
    if rainfall_mm >= extreme_threshold:
        forced = fsi.where(water_mask.gt(0), 1.0).rename("flood_risk")
        print(f"[MODEL] Water bodies forced to FSI=1.0 (rain {rainfall_mm}mm >= {extreme_threshold}mm threshold)")
    else:
        forced = fsi
        print(f"[MODEL] Water bodies NOT forced (rain {rainfall_mm}mm < {extreme_threshold}mm threshold)")
    return forced


def classify_risk_adaptive(fsi: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """
    Adaptive risk classification based on the scenario's actual FSI range.

    Low:    0           – 0.4 * MaxFSI
    Medium: 0.4 * MaxFSI – 0.7 * MaxFSI
    High:   0.7 * MaxFSI – MaxFSI

    This ensures a visible gradient regardless of rainfall magnitude.
    """
    # Compute max FSI in the AOI
    max_fsi_dict = fsi.reduceRegion(
        reducer=ee.Reducer.max(),
        geometry=aoi,
        scale=config.EXPORT_SCALE,
        maxPixels=config.MAX_PIXELS,
    )
    max_fsi = ee.Number(max_fsi_dict.values().get(0))

    # Adaptive thresholds
    low_max = max_fsi.multiply(0.4)
    medium_max = max_fsi.multiply(0.7)

    classified = (
        ee.Image(1)
        .where(fsi.gt(low_max), 2)
        .where(fsi.gt(medium_max), 3)
        .rename("risk_class")
    )

    # Print thresholds for debugging
    max_val = max_fsi.getInfo()
    print(f"[MODEL] Adaptive classification – MaxFSI={max_val:.4f}")
    print(f"        Low:    0 – {max_val * 0.4:.4f}")
    print(f"        Medium: {max_val * 0.4:.4f} – {max_val * 0.7:.4f}")
    print(f"        High:   {max_val * 0.7:.4f} – {max_val:.4f}")

    return classified


def classify_risk(risk: ee.Image) -> ee.Image:
    """
    Static classification fallback (for backward compatibility).
    Prefer classify_risk_adaptive() for rainfall-scaled FSI.
    """
    t = config.RISK_THRESHOLDS
    classified = (
        ee.Image(1)
        .where(risk.gt(t["low_max"]), 2)
        .where(risk.gt(t["medium_max"]), 3)
        .rename("risk_class")
    )
    print("[MODEL] Risk classified (static thresholds)")
    return classified


def export_geotiff(
    image: ee.Image,
    aoi: ee.Geometry,
    filename: str = None,
    scale: int = config.EXPORT_SCALE,
) -> str:
    """
    Export an EE image to a local GeoTIFF via geemap.
    Returns the output file path.
    """
    import geemap

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, filename or config.RISK_GEOTIFF)

    geemap.ee_export_image(
        image,
        filename=out_path,
        scale=scale,
        region=aoi,
        crs=config.CRS,
        file_per_band=False,
    )
    print(f"[EXPORT] GeoTIFF saved → {out_path}")
    return out_path
