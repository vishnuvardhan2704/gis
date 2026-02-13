"""
GEE Data Module – Authentication, AOI creation, and remote-sensing data fetch.
"""

import ee
import config


def initialize_ee(project_id: str = config.GEE_PROJECT_ID) -> None:
    """Authenticate (if needed) and initialise Earth Engine."""
    try:
        ee.Initialize(project=project_id)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project_id)
    print(f"[GEE] Initialised with project: {project_id}")


def create_aoi(lat: float, lon: float, radius_km: float) -> ee.Geometry:
    """Return a circular AOI geometry centred on (lat, lon)."""
    point = ee.Geometry.Point([lon, lat])
    aoi = point.buffer(radius_km * 1000)
    print(f"[GEE] AOI created – centre ({lat}, {lon}), radius {radius_km} km")
    return aoi


# ── DEM ──────────────────────────────────────────────────────────────────────

def fetch_dem(aoi: ee.Geometry) -> ee.Image:
    """Fetch SRTM DEM clipped to AOI and downsampled to soil resolution."""
    dem = ee.Image(config.DEM_ASSET).clip(aoi)

    # Downsample from ~30 m to 250 m so it aligns with soil layers
    dem_250 = (
        dem
        .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
        .reproject(crs=config.CRS, scale=config.EXPORT_SCALE)
    )
    print("[GEE] DEM fetched and downsampled to 250 m")
    return dem_250


def compute_slope(dem: ee.Image) -> ee.Image:
    """Derive slope (degrees) from the DEM."""
    slope = ee.Terrain.slope(dem)
    print("[GEE] Slope computed from DEM")
    return slope


# ── Soil ─────────────────────────────────────────────────────────────────────

def fetch_soil(aoi: ee.Geometry) -> tuple[ee.Image, ee.Image]:
    """Return (clay, sand) images from OpenLandMap, surface depth, clipped."""
    clay = (
        ee.Image(config.CLAY_ASSET)
        .select(config.SOIL_BAND)
        .clip(aoi)
    )
    sand = (
        ee.Image(config.SAND_ASSET)
        .select(config.SOIL_BAND)
        .clip(aoi)
    )
    print("[GEE] Soil layers fetched (clay, sand)")
    return clay, sand


# ── Numpy export helper ─────────────────────────────────────────────────────

def ee_image_to_numpy(image: ee.Image, aoi: ee.Geometry, band: str = None):
    """
    Download a single-band EE image as a 2D NumPy array.
    Uses GeoTIFF download for reliable 2D shape.
    """
    import numpy as np
    import urllib.request, io, rasterio

    if band:
        image = image.select(band)

    try:
        url = image.getDownloadURL({
            "scale": config.EXPORT_SCALE,
            "crs": config.CRS,
            "region": aoi,
            "format": "GEO_TIFF",
        })
        response = urllib.request.urlopen(url)
        data = response.read()
        with rasterio.open(io.BytesIO(data)) as src:
            arr = src.read(1)
        print(f"[GEE] DEM downloaded as numpy – shape {arr.shape}")
        return arr
    except Exception as e:
        print(f"[GEE] GeoTIFF download failed ({e}); trying sampleRectangle")
        arr_info = image.sampleRectangle(region=aoi, defaultValue=0).getInfo()
        band_name = list(arr_info["properties"].keys())[0]
        arr = np.array(arr_info["properties"][band_name])
        print(f"[GEE] DEM via sampleRectangle – shape {arr.shape}")
        return arr

