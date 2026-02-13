"""
Hydrology Module – River proximity and flow accumulation factors.
"""

import numpy as np
import osmnx as ox
import geopandas as gpd
from scipy import ndimage
from shapely.geometry import box
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds

import config


# ── River / Water Feature Proximity ─────────────────────────────────────────

def fetch_water_features(lat: float, lon: float, radius_m: float) -> gpd.GeoDataFrame:
    """
    Download rivers, streams, canals, lakes, and reservoirs from OSM
    within the given radius.
    """
    # Waterway lines (rivers, streams, canals, drains)
    waterway_tags = {"waterway": True}
    # Water polygons (lakes, reservoirs, ponds)
    water_tags = {"natural": "water"}

    gdfs = []
    for tags, label in [(waterway_tags, "waterways"), (water_tags, "water bodies")]:
        try:
            gdf = ox.features_from_point((lat, lon), tags=tags, dist=radius_m)
            gdfs.append(gdf)
            print(f"[HYDRO] Fetched {len(gdf)} {label} from OSM")
        except Exception as e:
            print(f"[HYDRO] No {label} found: {e}")

    if not gdfs:
        print("[HYDRO] ⚠ No water features found in AOI")
        return gpd.GeoDataFrame()

    combined = gpd.pd.concat(gdfs, ignore_index=True)
    print(f"[HYDRO] Total water features: {len(combined)}")
    return combined


def compute_river_proximity(
    water_gdf: gpd.GeoDataFrame,
    bounds: tuple,  # (west, south, east, north)
    scale: int = config.EXPORT_SCALE,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Rasterize water features → Euclidean distance transform → invert & normalise.

    Returns:
        (river_factor_array, water_mask, raster_meta)
        river_factor_array: 2D numpy array in [0, 1], higher = closer to water
        water_mask: 2D binary array (1 = water pixel, 0 = land)
        raster_meta: dict with transform, shape, bounds
    """
    import math

    west, south, east, north = bounds

    # Compute grid dimensions from bounds and scale
    mid_lat = (south + north) / 2
    deg_per_pixel_lon = scale / (111_320 * math.cos(math.radians(mid_lat)))
    deg_per_pixel_lat = scale / 111_320

    width = max(1, int((east - west) / deg_per_pixel_lon))
    height = max(1, int((north - south) / deg_per_pixel_lat))

    transform = from_bounds(west, south, east, north, width, height)

    if water_gdf.empty:
        river_factor = np.full((height, width), 0.0, dtype=np.float32)
        water_mask = np.zeros((height, width), dtype=np.uint8)
        print("[HYDRO] No water features → river factor = 0 everywhere")
    else:
        # Rasterize: 1 where water exists, 0 elsewhere
        geometries = [(geom, 1) for geom in water_gdf.geometry if geom is not None]
        water_raster = rasterize(
            geometries,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )

        # Keep binary water mask
        water_mask = water_raster.copy()

        # Euclidean distance from nearest water pixel
        dist = ndimage.distance_transform_edt(water_raster == 0)

        # Normalise to [0, 1] and invert (closer = higher risk)
        d_max = dist.max()
        if d_max > 0:
            river_factor = 1.0 - (dist / d_max)
        else:
            river_factor = np.ones_like(dist)

        river_factor = river_factor.astype(np.float32)
        print(f"[HYDRO] River proximity computed – grid {width}×{height}, "
              f"range [{river_factor.min():.3f}, {river_factor.max():.3f}]")
        print(f"[HYDRO] Water mask: {water_mask.sum()} water pixels out of {water_mask.size}")

    meta = {
        "transform": transform,
        "width": width,
        "height": height,
        "bounds": bounds,
    }
    return river_factor, water_mask, meta


# ── Flow Accumulation / TWI ─────────────────────────────────────────────────

def compute_flow_accumulation(dem_array: np.ndarray) -> np.ndarray:
    """
    Compute a simplified flow accumulation from a DEM using the D8 algorithm.

    For each cell, count how many upstream cells drain into it.
    This is a local approximation — for production use, consider
    pysheds or WhiteboxTools.

    Returns a 2D array of flow accumulation counts.
    """
    rows, cols = dem_array.shape
    flow_accum = np.ones((rows, cols), dtype=np.float64)

    # D8 direction offsets: (row_offset, col_offset)
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    # Compute flow direction for each cell (index of steepest downhill neighbour)
    flow_dir = np.full((rows, cols), -1, dtype=np.int8)
    for r in range(rows):
        for c in range(cols):
            steepest_drop = 0
            best_idx = -1
            for idx, (dr, dc) in enumerate(neighbors):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    drop = dem_array[r, c] - dem_array[nr, nc]
                    if drop > steepest_drop:
                        steepest_drop = drop
                        best_idx = idx
            flow_dir[r, c] = best_idx

    # Sort cells by elevation (highest first) and accumulate downstream
    flat_indices = np.argsort(-dem_array.ravel())
    for flat_idx in flat_indices:
        r, c = divmod(flat_idx, cols)
        d = flow_dir[r, c]
        if d >= 0:
            dr, dc = neighbors[d]
            nr, nc = r + dr, c + dc
            flow_accum[nr, nc] += flow_accum[r, c]

    print(f"[HYDRO] Flow accumulation computed – "
          f"max: {flow_accum.max():.0f}, mean: {flow_accum.mean():.1f}")
    return flow_accum


def normalize_flow_accumulation(flow_accum: np.ndarray) -> np.ndarray:
    """
    Log-normalise flow accumulation to [0, 1].
    Log transform compresses the extreme range of flow accumulation values.
    """
    log_fa = np.log1p(flow_accum)
    fa_min, fa_max = log_fa.min(), log_fa.max()
    if fa_max - fa_min > 0:
        normalised = (log_fa - fa_min) / (fa_max - fa_min)
    else:
        normalised = np.zeros_like(log_fa)

    print(f"[HYDRO] Flow accumulation normalised – "
          f"range [{normalised.min():.3f}, {normalised.max():.3f}]")
    return normalised.astype(np.float32)


# ── Convert numpy arrays to EE images ───────────────────────────────────────

def numpy_to_ee_image(
    array: np.ndarray,
    bounds: tuple,
    band_name: str = "factor",
) -> "ee.Image":
    """
    Convert a 2D numpy array to a GEE image by uploading as a constant
    raster aligned to the given bounds.

    Uses ee.Image.pixelLonLat() trick: build a lookup from the array
    and paint it onto the GEE grid.
    """
    import ee

    west, south, east, north = bounds
    rows, cols = array.shape

    # Flatten and create a list image
    flat = array.ravel().tolist()

    # Create a coordinate-based image
    lon_img = ee.Image.pixelLonLat().select("longitude")
    lat_img = ee.Image.pixelLonLat().select("latitude")

    # Map pixel coordinates to array indices
    col_idx = lon_img.subtract(west).divide(east - west).multiply(cols).floor().clamp(0, cols - 1)
    row_idx = lat_img.subtract(south).divide(north - south).multiply(rows).floor()
    # Flip rows (array row 0 = north)
    row_idx = ee.Image.constant(rows - 1).subtract(row_idx).clamp(0, rows - 1)

    # Linear index
    linear_idx = row_idx.multiply(cols).add(col_idx).toInt()

    # Create the image from the array
    array_img = ee.Image(ee.Array(flat)).arrayGet(linear_idx).rename(band_name)

    # Clip to bounds
    aoi = ee.Geometry.Rectangle([west, south, east, north])
    return array_img.clip(aoi)
