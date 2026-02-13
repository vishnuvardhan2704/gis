"""
Configuration constants for the Flood Susceptibility & Evacuation System.

Model: FSI(x) = BaseRisk(x) × RainFactor
  BaseRisk = 5-factor AHP-weighted overlay (no rainfall)
  RainFactor = (Rain / RainMax) ^ alpha

Weights derived via AHP in src/ahp.py (CR = 0.006).
"""

# ── Google Earth Engine ──────────────────────────────────────────────────────
GEE_PROJECT_ID = "gisproj-487215"

# ── Default Area of Interest (Hyderabad, India) ─────────────────────────────
DEFAULT_LAT = 17.3850
DEFAULT_LON = 78.4867
DEFAULT_RADIUS_KM = 10  # small default for fast testing

# ── Data Sources (GEE asset IDs) ────────────────────────────────────────────
DEM_ASSET = "USGS/SRTMGL1_003"
CLAY_ASSET = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
SAND_ASSET = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
SOIL_BAND = "b0"

# ── Processing ───────────────────────────────────────────────────────────────
EXPORT_SCALE = 250       # metres – match soil resolution
CRS = "EPSG:4326"
MAX_PIXELS = 1e9

# ── MCDA Weights (AHP-derived, 5 spatial factors, CR = 0.006) ───────────────
# Source: Saaty 5×5 pairwise comparison → eigenvector normalisation.
# Rainfall is NOT a factor — it is applied as a multiplier in Step 2.
# See src/ahp.py for full matrix and consistency check.
WEIGHTS = {
    "elevation":  0.2319,
    "slope":      0.0906,
    "soil":       0.0906,
    "river":      0.3912,
    "flow_accum": 0.1956,
}

# ── Rainfall Multiplier ─────────────────────────────────────────────────────
# FSI = BaseRisk × (Rain / RainMax) ^ alpha
# RainMax = design storm for the region (urban flooding threshold)
# alpha > 1 gives nonlinear amplification
RAIN_MAX = 150.0     # urban extreme rainfall threshold (mm)
RAIN_ALPHA = 1.2     # nonlinear exponent

# ── Risk Classification Thresholds (fixed physical thresholds) ───────────────
RISK_THRESHOLDS = {
    "low_max":    0.3,    # 0.00 – 0.30  → Low
    "medium_max": 0.6,    # 0.30 – 0.60  → Medium
                          # 0.60 – 1.00  → High
}

# ── Evacuation ──────────────────────────────────────────────────────────────
FLOOD_RISK_PENALTY_FACTOR = 10   # road-weight multiplier for risky segments
HIGH_RISK_ROAD_THRESHOLD  = 0.66 # remove road segments above this risk

# ── Output Paths ────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
RISK_GEOTIFF = "flood_risk.tif"
RISK_MAP_HTML = "flood_risk_map.html"
REPORT_JSON = "situation_report.json"
