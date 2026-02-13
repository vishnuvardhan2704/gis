# AI-Driven Flood Susceptibility & Evacuation Decision Support System

> **Hackathon project** — A complete end-to-end GIS system that computes flood susceptibility for any location on Earth, visualises it on a 2D/3D map, routes evacuations, and supports immersive VR viewing on phone-based VR headsets.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & System Design](#2-architecture--system-design)
3. [Directory Structure](#3-directory-structure)
4. [Technical Stack](#4-technical-stack)
5. [Setup & Installation](#5-setup--installation)
6. [Running the Application](#6-running-the-application)
7. [Flood Susceptibility Model (FSI)](#7-flood-susceptibility-model-fsi)
8. [AHP Weight Derivation](#8-ahp-weight-derivation)
9. [Data Sources & Pipeline](#9-data-sources--pipeline)
10. [Backend API Reference](#10-backend-api-reference)
11. [Frontend Architecture](#11-frontend-architecture)
12. [3D Terrain Viewer](#12-3d-terrain-viewer)
13. [VR System](#13-vr-system)
14. [Module Reference](#14-module-reference)
15. [Configuration Reference](#15-configuration-reference)
16. [Output Files](#16-output-files)
17. [CLI Usage](#17-cli-usage)
18. [Validation & Debugging](#18-validation--debugging)
19. [Known Issues & Constraints](#19-known-issues--constraints)
20. [File-by-File Reference](#20-file-by-file-reference)

---

## 1. Project Overview

### What It Does

A user clicks any point on Earth on an interactive dark-themed map (or searches by place name). The system:

1. Fetches terrain data (DEM, slope, soil) from **Google Earth Engine**
2. Fetches water features (rivers, lakes) from **OpenStreetMap**
3. Computes a **5-factor AHP-weighted base susceptibility** map
4. Applies a **nonlinear rainfall multiplier** to produce the final **Flood Susceptibility Index (FSI)**
5. Overlays the FSI as a smooth green→yellow→red raster on the Leaflet map
6. Fetches **buildings from OSM**, cross-references with the FSI to estimate affected population
7. Loads the **OSM road network**, penalises flooded roads, and computes an **A\* escape route** to the nearest safe zone
8. Generates a **3D terrain visualization** with Three.js (orbit, zoom, pan)
9. Exports the terrain as a **GLB model** for **phone VR viewing** (A-Frame stereo + gyroscope)
10. Generates a **QR code** for quick phone access to the VR viewer

### Key Technical Achievement

The FSI model uses the **Analytic Hierarchy Process (AHP)** with a 5×5 Saaty pairwise comparison matrix that achieves a **Consistency Ratio (CR) of 0.006** (well below the 0.10 threshold), ensuring mathematically rigorous factor weighting.

---

## 2. Architecture & System Design

### High-Level Data Flow

```
User clicks map
    │
    ▼
POST /api/analyze  ──→  Background thread
    │                        │
    │                        ├─ GEE: fetch DEM, slope, soil
    │                        ├─ OSM: fetch rivers, water bodies
    │                        ├─ Compute river proximity (EDT)
    │                        ├─ Compute flow accumulation (D8)
    │                        ├─ AHP weights → 5-factor BaseRisk
    │                        ├─ Rainfall multiplier → FSI
    │                        ├─ Export GeoTIFF
    │                        ├─ Generate risk PNG overlay
    │                        ├─ Fetch buildings (Overpass API)
    │                        ├─ Load road graph (OSMnx)
    │                        ├─ Sample FSI on edges
    │                        ├─ A* escape routing
    │                        └─ Compute statistics
    │
    ▼
GET /api/status/<job_id>  ──→  Poll until done
    │
    ▼
Frontend renders:
    ├─ Risk overlay on Leaflet map
    ├─ Road network (color-coded by risk)
    ├─ Evacuation route (blue dashed)
    ├─ Building markers (risk-colored)
    ├─ Statistics sidebar
    └─ 3D terrain viewer (Three.js)
```

### Threading Model

- Flask runs with `threaded=True` on port **5050**, host **0.0.0.0**
- Each analysis runs in a **daemon thread** via `threading.Thread`
- Job state stored in an in-memory dict `jobs` protected by `threading.Lock`
- Frontend polls `GET /api/status/<job_id>` every 1.5 seconds

### HTTPS

The server runs with a **self-signed SSL certificate** (`cert.pem` + `key.pem`) to enable WebXR sensor access (gyroscope requires secure context on mobile browsers).

```python
app.run(ssl_context=('cert.pem', 'key.pem'))
```

---

## 3. Directory Structure

```
gisproj/
├── app.py                  # Flask server — all API routes, pipeline runner, helpers (697 lines)
├── config.py               # All constants: GEE project, AHP weights, thresholds (64 lines)
├── main.py                 # CLI entry point — full pipeline (228 lines)
├── requirements.txt        # Python dependencies
├── validate_model.py       # 7-location validation script (228 lines)
├── debug_factors.py        # Factor debugging/inspection (105 lines)
├── cert.pem                # Self-signed SSL certificate (for HTTPS)
├── key.pem                 # SSL private key
├── PROJECT_CONTEXT.md      # AI agent context document
├── README.md               # This file
├── .gitignore              # Excludes venv, output, cache, __pycache__
│
├── src/                    # Core computation modules (1,436 lines total)
│   ├── __init__.py         # Package marker (1 line)
│   ├── gee_data.py         # GEE auth, AOI, DEM/slope/soil fetch (101 lines)
│   ├── preprocessing.py    # Factor normalization: elevation, slope, soil (71 lines)
│   ├── hydrology.py        # River proximity (EDT), flow accumulation (D8), numpy→EE (226 lines)
│   ├── flood_model.py      # BaseRisk, rainfall multiplier, classification, GeoTIFF export (178 lines)
│   ├── ahp.py              # AHP Saaty matrix → eigenvector weights (113 lines)
│   ├── road_network.py     # OSM road graph, parallel risk sampling, safe-zone labeling (196 lines)
│   ├── evacuation.py       # A* escape routing to nearest safe zone (127 lines)
│   ├── export_vr.py        # GLB terrain mesh generation (trimesh) (140 lines)
│   ├── decision_support.py # Risk statistics, road counts, report generation (149 lines)
│   └── visualization.py    # Folium HTML map generation (134 lines)
│
├── static/                 # Frontend assets (2,130 lines total)
│   ├── app.js              # Map init, search, analysis, overlays, buildings, VR toggle (696 lines)
│   ├── terrain3d.js        # Three.js 3D terrain engine: mesh, water, routes, buildings (401 lines)
│   └── style.css           # Dark theme, glassmorphism, responsive layout (1,033 lines)
│
├── templates/              # Jinja2 HTML templates (910 lines total)
│   ├── index.html          # Main SPA: Leaflet + sidebar + 3D panel (150 lines)
│   └── vr_viewer.html      # VR viewer: Three.js canvas + A-Frame stereo (760 lines)
│
├── output/                 # Generated files (gitignored)
│   ├── dem_terrain.tif     # DEM GeoTIFF
│   ├── flood_risk.tif      # FSI GeoTIFF
│   ├── flood_risk_classified.tif
│   ├── risk_overlay_*.png  # Per-job risk overlay PNGs
│   ├── terrain_*.glb       # Per-job GLB terrain models
│   ├── flood_risk_map.html # Folium standalone map
│   └── situation_report.json
│
├── cache/                  # GEE response cache (gitignored)
├── venv/                   # Python virtual environment (gitignored)
└── test/                   # Test files
    ├── test.py
    └── test.ipynb
```

**Total codebase: ~5,464 lines** (Python + JS + HTML + CSS)

---

## 4. Technical Stack

### Backend

| Component | Technology | Version/Detail |
|-----------|-----------|----------------|
| Language | Python | 3.12+ |
| Web Framework | Flask | Latest, port 5050, HTTPS |
| Earth Engine | `earthengine-api` | GEE project: `gisproj-487215` |
| Geospatial | `rasterio`, `geopandas`, `shapely` | GeoTIFF I/O, geometry ops |
| Road Network | `osmnx`, `networkx` | OSM graph download + A* routing |
| 3D Export | `trimesh` | GLB/glTF-Binary mesh export |
| Image Processing | `scipy.ndimage`, `Pillow`, `matplotlib` | Upsampling, hillshade, colormaps |
| QR Codes | `qrcode` | Phone VR URL generation |
| Interpolation | `scipy.ndimage.zoom` | Bilinear/bicubic raster resampling |

### Frontend

| Component | Technology | Version/Detail |
|-----------|-----------|----------------|
| 2D Map | Leaflet.js | Via CDN, dark CartoDB tiles |
| 3D Terrain | Three.js | r146 from `unpkg.com/three@0.146.0` |
| 3D Controls | OrbitControls | Three.js r146 addon |
| 3D Loading | GLTFLoader | Three.js r146 addon |
| VR Stereo | A-Frame | v1.5.0 (bundles Three.js r158 internally) |
| Geocoding | Nominatim | OSM geocoding (free, no API key) |
| Styling | Vanilla CSS | Dark theme, glassmorphism, CSS Grid |

### THREE.js Version Conflict Resolution

A-Frame 1.5.0 bundles Three.js r158 and overwrites the `THREE` global. The system loads Three.js r146 + addons **first**, saves references, then loads A-Frame:

```html
<!-- Load Three.js r146 FIRST -->
<script src="https://unpkg.com/three@0.146.0/build/three.min.js"></script>
<script src="https://unpkg.com/three@0.146.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://unpkg.com/three@0.146.0/examples/js/loaders/GLTFLoader.js"></script>
<script>
    // Save references before A-Frame overwrites THREE
    window._THREE146 = THREE;
    window._OrbitControls = THREE.OrbitControls;
    window._GLTFLoader = THREE.GLTFLoader;
</script>
<!-- A-Frame loads AFTER (overwrites THREE with r158) -->
<script src="https://aframe.io/releases/1.5.0/aframe.min.js"></script>
```

The viewer code then uses `window._THREE146`, `window._OrbitControls`, `window._GLTFLoader` instead of the global `THREE`.

---

## 5. Setup & Installation

### Prerequisites

- **Python 3.12+** (tested on macOS with Apple Silicon)
- **Google Earth Engine account** with an authenticated project
- **Internet connection** (for GEE, OSM, CDN resources)
- **OpenSSL** (for generating self-signed SSL cert)

### Step-by-Step Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd gisproj

# 2. Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Additional dependencies not in requirements.txt
pip install trimesh qrcode

# 5. Authenticate Google Earth Engine
earthengine authenticate

# 6. Generate self-signed SSL certificate (required for phone VR)
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
    -days 365 -nodes -subj "/CN=localhost"

# 7. Verify setup
python -c "import ee; ee.Initialize(project='gisproj-487215'); print('GEE OK')"
```

### requirements.txt

```
earthengine-api
geemap
osmnx
networkx
folium
rasterio
numpy
geopandas
shapely
scipy
scikit-learn
flask
matplotlib
Pillow
requests
```

**Also needed** (install manually): `trimesh`, `qrcode`

### Virtual Environment

The project uses a venv at `/Users/vishnu/gisproj/venv`. Always activate it:

```bash
source venv/bin/activate
# Or use the full path:
/Users/vishnu/gisproj/venv/bin/python app.py
```

---

## 6. Running the Application

### Web GUI (Primary)

```bash
source venv/bin/activate
python app.py
```

Output:
```
🌊 Flood Susceptibility GUI starting...
   Local:   https://localhost:5050
   Network: https://192.168.29.185:5050
   Phone VR: connect to the same WiFi, then scan the QR code
   ⚠  Self-signed cert — accept the browser warning on phone
```

Open `https://localhost:5050` in a browser. Accept the self-signed certificate warning.

### CLI (Alternative)

```bash
python main.py --lat 17.385 --lon 78.4867 --radius 10 --rainfall 150
```

CLI arguments:
| Flag | Default | Description |
|------|---------|-------------|
| `--lat` | 17.385 | Centre latitude |
| `--lon` | 78.4867 | Centre longitude |
| `--radius` | 10 | Radius in km |
| `--rainfall` | 150 | Rainfall scenario in mm |
| `--start-lat` | same as `--lat` | Evacuation start latitude |
| `--start-lon` | same as `--lon` | Evacuation start longitude |
| `--skip-roads` | false | Skip road & evacuation analysis |

---

## 7. Flood Susceptibility Model (FSI)

### Mathematical Formulation

The FSI is a two-step model:

**Step 1: Base Susceptibility (5-factor AHP weighted overlay)**

$$\text{BaseRisk}(x) = \sum_{i=1}^{5} w_i \cdot F_i(x)$$

Where each factor $F_i(x) \in [0, 1]$ and weights $\sum w_i = 1$.

**Step 2: Rainfall Multiplier**

$$\text{FSI}(x) = \text{clamp}\left(\text{BaseRisk}(x) \times \left(\frac{R}{R_{\max}}\right)^\alpha, \; 0, \; 1\right)$$

Where:
- $R$ = rainfall scenario (mm)
- $R_{\max}$ = 150 mm (urban extreme rainfall threshold)
- $\alpha$ = 1.2 (nonlinear exponent)

### The 5 Spatial Factors

| # | Factor | Weight | Source | Normalization |
|---|--------|--------|--------|--------------|
| 1 | **Elevation** | 0.2319 | SRTM DEM (GEE) | Inverted min-max: lower = higher risk |
| 2 | **Slope** | 0.0906 | Derived from DEM | Inverted min-max: flatter = higher risk |
| 3 | **Soil** | 0.0906 | OpenLandMap clay/sand (GEE) | `(clay - sand)/100`, rescaled [-1,1]→[0,1] |
| 4 | **River proximity** | 0.3912 | OSM waterways (Overpass) | Euclidean distance transform, inverted |
| 5 | **Flow accumulation** | 0.1956 | D8 algorithm on DEM | Log-normalized to [0,1] |

**Note:** River Proximity is the strongest predictor (weight 0.3912). Additionally, in the implementation:

$$\text{RiverEffective} = \text{RiverFactor} \times \text{SlopeFactor}$$

This dampens river influence on steep slopes (steep valleys drain fast, reducing flood risk).

### Factor Preprocessing

| Factor | Raw Source | Processing Steps |
|--------|-----------|-----------------|
| Elevation | SRTM 30m DEM | Downsample to 250m → min-max normalize → invert |
| Slope | `ee.Terrain.slope(dem)` | Degrees → min-max normalize → invert |
| Soil | Clay/Sand weight fractions | `(clay/100 - sand/100)` → unitScale(-1, 1) |
| River | OSM waterways + water bodies | Rasterize → EDT (Euclidean Distance Transform) → invert → normalize |
| Flow Accum | DEM numpy array | D8 direction → topological sort → accumulate → log1p → normalize |

### Rainfall Multiplier Behavior

| Rainfall (mm) | Rain Factor | Effect |
|----------------|-------------|--------|
| 0 | 0.000 | No flood risk |
| 10 | 0.046 | Very low risk |
| 50 | 0.280 | Moderate |
| 100 | 0.617 | Significant |
| 150 | 1.000 | Maximum (design storm) |

### Water Body Forcing

Water body pixels (lakes, reservoirs) are forced to FSI = 1.0 **only** when rainfall exceeds 30% of the design storm (45mm). Light rain over a lake is not a flood event.

### Risk Classification

**Static thresholds** (used for GeoTIFF classification):
| Class | FSI Range | Code |
|-------|-----------|------|
| Low | 0.00 – 0.30 | 1 |
| Medium | 0.30 – 0.60 | 2 |
| High | 0.60 – 1.00 | 3 |

**Adaptive thresholds** (available for dynamic scenarios):
| Class | FSI Range |
|-------|-----------|
| Low | 0 – 0.4 × MaxFSI |
| Medium | 0.4 × MaxFSI – 0.7 × MaxFSI |
| High | 0.7 × MaxFSI – MaxFSI |

---

## 8. AHP Weight Derivation

### Saaty Pairwise Comparison Matrix (5×5)

```
              Elev   Slope  Soil   River  Flow
Elevation   [  1      3      3     1/2     1   ]
Slope       [ 1/3     1      1     1/4    1/2  ]
Soil        [ 1/3     1      1     1/4    1/2  ]
River       [  2      4      4      1      2   ]
Flow Accum  [  1      2      2     1/2     1   ]
```

### Physical Reasoning

- **River proximity** is the strongest flood predictor (receives highest weight)
- **Elevation** is strongly important (low-lying areas collect water)
- **Flow accumulation** captures drainage convergence
- **Slope** is moderate (flat terrain = slower drainage)
- **Soil** is moderate (clay resists infiltration → more runoff)

### Computation Method

1. **Column normalization**: Divide each element by its column sum
2. **Priority vector**: Row averages of the normalized matrix
3. **Consistency check**:
   - Compute $\lambda_{\max}$ (average of weighted sum ratios)
   - $\text{CI} = (\lambda_{\max} - n) / (n - 1)$
   - $\text{CR} = \text{CI} / \text{RI}$ where $\text{RI}(5) = 1.12$ (from Saaty's Random Index table)
4. **Validation**: CR must be < 0.10 for consistency

### Results

| Factor | Weight |
|--------|--------|
| Elevation | 0.2319 |
| Slope | 0.0906 |
| Soil | 0.0906 |
| River | 0.3912 |
| Flow Accum | 0.1956 |
| **Sum** | **1.0000** |

- $\lambda_{\max} = 5.027$
- $\text{CI} = 0.0067$
- $\text{CR} = 0.006$ ✅ (well below 0.10)

---

## 9. Data Sources & Pipeline

### Remote Data Sources

| Data | Source | API | Resolution |
|------|--------|-----|-----------|
| DEM | USGS SRTM | Google Earth Engine (`USGS/SRTMGL1_003`) | 30m (downsampled to 250m) |
| Clay fraction | OpenLandMap | GEE (`OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02`) | 250m |
| Sand fraction | OpenLandMap | GEE (`OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02`) | 250m |
| Rivers/Lakes | OpenStreetMap | Overpass API (via OSMnx) | Vector |
| Roads | OpenStreetMap | Overpass API (via OSMnx) | Vector |
| Buildings | OpenStreetMap | Overpass API (direct HTTP) | Vector |
| Geocoding | Nominatim | HTTP (free, no key) | N/A |

### GEE Configuration

```python
GEE_PROJECT_ID = "gisproj-487215"
DEM_ASSET = "USGS/SRTMGL1_003"
CLAY_ASSET = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
SAND_ASSET = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
SOIL_BAND = "b0"         # Surface depth band
EXPORT_SCALE = 250        # metres
CRS = "EPSG:4326"
MAX_PIXELS = 1e9
```

### Pipeline Phases (Web GUI)

| Phase | Description | Module | Progress Message |
|-------|-------------|--------|-----------------|
| 0 | AHP weight derivation | `src/ahp.py` | "Computing AHP weights..." |
| 1 | Create AOI geometry | `src/gee_data.py` | "Creating area of interest..." |
| 2 | Fetch DEM, slope, soil; normalize | `src/gee_data.py`, `src/preprocessing.py` | "Fetching terrain data from GEE..." |
| 3A | Fetch water features from OSM | `src/hydrology.py` | "Fetching river data from OpenStreetMap..." |
| 3B | Compute river proximity (EDT) | `src/hydrology.py` | "Computing river proximity & water mask..." |
| 3C | Compute flow accumulation (D8) | `src/hydrology.py` | "Computing flow accumulation..." |
| 4A | Compute 5-factor BaseRisk | `src/flood_model.py` | "Computing base susceptibility (5-factor)..." |
| 4B | Apply rainfall multiplier → FSI | `src/flood_model.py` | "Applying rainfall multiplier..." |
| 4C | Export GeoTIFFs | `src/flood_model.py` | — |
| 5A | Generate risk overlay PNG | `app.py` | "Generating risk map overlay..." |
| 5B | Fetch buildings from OSM | `app.py` | "Fetching buildings from OpenStreetMap..." |
| 6A | Load road graph (OSMnx) | `src/road_network.py` | "Analysing road network..." |
| 6B | Sample FSI on road edges | `src/road_network.py` | — |
| 6C | Penalise flooded edges | `src/road_network.py` | — |
| 6D | Label safe-zone nodes | `src/road_network.py` | — |
| 6E | A* escape routing | `src/evacuation.py` | "Computing escape route to safe zone..." |
| 7 | Compute risk statistics | `src/decision_support.py` | "Computing risk statistics..." |

---

## 10. Backend API Reference

### `GET /`

Serves the main single-page application (`templates/index.html`).

### `POST /api/analyze`

**Request body** (JSON):
```json
{
    "lat": 17.385,
    "lon": 78.4867,
    "radius_km": 5,
    "rainfall_mm": 150
}
```

**Response** (JSON):
```json
{
    "job_id": "a1b2c3d4"
}
```

Pipeline runs in a background thread. Poll status via `/api/status/<job_id>`.

### `GET /api/status/<job_id>`

**Response** (while running):
```json
{
    "status": "running",
    "progress": "Computing flow accumulation...",
    "result": null,
    "error": null
}
```

**Response** (when done):
```json
{
    "status": "done",
    "progress": "Complete",
    "result": {
        "bounds": { "south": 17.34, "west": 78.44, "north": 17.43, "east": 78.53 },
        "overlay_url": "/api/overlay/a1b2c3d4",
        "risk_stats": {
            "total_area_km2": 78.54,
            "low_risk": { "pct": 45.2, "area_km2": 35.5 },
            "medium_risk": { "pct": 32.1, "area_km2": 25.2 },
            "high_risk": { "pct": 22.7, "area_km2": 17.8 },
            "mean_risk": 0.3842,
            "max_risk": 0.9521
        },
        "road_stats": {
            "total_segments": 1234,
            "high_risk_segments": 89,
            "medium_risk_segments": 234,
            "safe_segments": 911
        },
        "roads": { "type": "FeatureCollection", "features": [...] },
        "evacuation_route": { "type": "Feature", "geometry": { "type": "LineString", ... } },
        "escape_destination": { "lat": 17.39, "lon": 78.47, "fsi": 0.12 },
        "buildings": [ { "lat": ..., "lon": ..., "type": "residential", "floors": 2, "fsi": 0.45, "pop": 8 }, ... ],
        "impact_stats": {
            "total_buildings": 150,
            "at_risk": 67,
            "high_risk": 23,
            "population_at_risk": 456,
            "critical_facilities": 2
        },
        "params": { "lat": 17.385, "lon": 78.4867, "radius_km": 5, "rainfall_mm": 150 }
    },
    "error": null
}
```

### `GET /api/overlay/<job_id>`

Returns the risk overlay as a **PNG image** (transparent, green→yellow→red gradient with hillshade).

The PNG is 4× bilinearly upsampled from the 250m GeoTIFF for smooth rendering. If DEM is available, a hillshade layer is blended at 35% opacity under the FSI colors at 65% opacity.

### `GET /api/terrain3d/<job_id>`

Returns high-resolution DEM + FSI grids as **JSON** for the Three.js 3D viewer:

```json
{
    "dem": [[...], ...],       // 256×256 grid (bicubic interpolated)
    "fsi": [[...], ...],       // 128×128 grid (bilinear interpolated)
    "dem_rows": 256, "dem_cols": 256,
    "fsi_rows": 128, "fsi_cols": 128,
    "dem_min": 400.2, "dem_max": 623.8,
    "dem_mean": 512.3, "dem_std": 45.6,
    "fsi_min": 0.0, "fsi_max": 0.95,
    "bounds": { "south": ..., "west": ..., "north": ..., "east": ... },
    "buildings": [...],
    "evacuation_route": { ... },
    "escape_destination": { ... },
    "resolution_meters": 250
}
```

### `GET /api/export-vr/<job_id>`

Generates and serves a **GLB (glTF-Binary)** terrain model. The model is:
- 256×256 vertex grid
- 100m × 100m horizontal extent
- 20% vertical exaggeration (peak-to-valley = 20m for 100m terrain)
- Vertex-colored with FSI (green→yellow→red)
- Typically ~2.5 MB

GLB files are cached at `output/terrain_<job_id>.glb`.

### `GET /api/qr-vr/<job_id>`

Returns a **QR code PNG** encoding the VR viewer URL: `https://<network_ip>:5050/vr/<job_id>`

### `GET /api/network-ip`

Returns the machine's local network IP:
```json
{ "ip": "192.168.29.185" }
```

### `GET /vr/<job_id>`

Serves the VR viewer HTML page (`templates/vr_viewer.html`). Injects `job_id` and `network_ip` via Jinja2.

---

## 11. Frontend Architecture

### Main Application (`index.html` + `app.js` + `style.css`)

#### Layout

- **Left sidebar** (collapsible): Location search, coordinate input, radius slider, rainfall slider, analyze button, results panel
- **Map area** (Leaflet): Dark CartoDB tiles, click-to-select, risk overlay, road network, evacuation route, building markers
- **3D panel** (toggleable): Three.js terrain viewer overlaid on the map
- **Status bar**: Progress messages during analysis

#### User Interaction Flow

1. **Search or click** to select a location → marker + radius circle placed
2. **Adjust** radius (1–50 km) and rainfall (0–300 mm) sliders
3. **Click Analyze** → `POST /api/analyze` → polling begins
4. **Results arrive**: overlay appears, statistics populate, roads render
5. **Toggle 3D**: terrain loads from `/api/terrain3d/<job_id>`, Three.js canvas appears
6. **VR button**: on desktop shows QR modal; on mobile opens VR setup overlay

#### Key Frontend Functions (`app.js`)

| Function | Purpose |
|----------|---------|
| `initMap()` | Create Leaflet map with dark tiles |
| `initSearch()` | Nominatim geocoding search bar |
| `onMapClick(e)` | Place marker + radius circle on click |
| `startAnalysis()` | POST to `/api/analyze`, begin polling |
| `pollStatus(jobId)` | Poll `/api/status/<job_id>` every 1.5s |
| `displayResults(result)` | Render overlay, roads, buildings, stats |
| `addRiskOverlay(result)` | Add FSI PNG as Leaflet ImageOverlay |
| `addRoads(result)` | Render road GeoJSON (color by risk) |
| `addBuildingMarkers(buildings)` | CircleMarkers colored by FSI |
| `addEvacuationRoute(result)` | Blue dashed polyline + destination marker |
| `openTerrain3D(jobId)` | Show Three.js panel, load terrain data |
| `openVRViewer(jobId)` | Fetch network IP, open VR page in new tab |

#### Building Classification

Buildings fetched from OSM are classified into types with estimated population:

| Type | Pop per Floor | Icon/Color |
|------|--------------|-----------|
| Residential | 4 | White |
| Commercial | 10 | Blue |
| Hospital | 50 | Red (critical facility) |
| School | 30 | Red (critical facility) |

---

## 12. 3D Terrain Viewer

### Technology

Three.js r146 with `OrbitControls` and `GLTFLoader`, loaded from unpkg CDN.

### Terrain Construction (`terrain3d.js`)

The 3D viewer receives DEM (256×256) and FSI (128×128) grids as JSON and constructs:

1. **Terrain mesh**: `PlaneGeometry(100, 100, 255, 255)` with Y-displacement from DEM
2. **Vertex coloring**: FSI values mapped to green→yellow→red ramp
3. **Water plane**: Semi-transparent blue plane at low-risk threshold elevation
4. **Building boxes**: Extruded `BoxGeometry` at building locations, colored by risk
5. **Evacuation route**: Blue `TubeGeometry` following the escape path
6. **Grid helper**: 200×40 grid for spatial reference
7. **Lighting**: Directional (sun) + ambient + hemisphere

### Camera & Controls

```javascript
camera = new THREE.PerspectiveCamera(60, aspect, 0.1, 2000);
controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 5;
controls.maxDistance = 400;
controls.maxPolarAngle = Math.PI / 2 - 0.05;
```

### Vertical Exaggeration

Elevation is exaggerated to make terrain relief visible at the 100m scale:

```javascript
const verticalScale = terrainWidth * 0.15 / elevRange;
```

---

## 13. VR System

### Architecture

The VR viewer (`vr_viewer.html`) uses a **dual-renderer architecture**:

1. **Three.js canvas** (`#viewer3d`): Main 3D viewer with OrbitControls — for interactive viewing on desktop and mobile
2. **A-Frame scene** (`#vrScene`): Hidden by default, activated only for VR stereo mode — provides stereoscopic rendering + gyroscope head tracking

### VR Workflow (Phone)

1. Run analysis on desktop → 3D viewer page has a **VR button**
2. Click VR → **QR code modal** appears with the URL
3. Scan QR on phone (same WiFi) → phone opens `https://<network_ip>:5050/vr/<job_id>`
4. Accept self-signed certificate warning
5. Phone shows the 3D terrain with **on-screen zoom/orbit buttons** on the right edge
6. Tap **Enter VR** → **VR Setup overlay** appears:
   - Adjust zoom, rotation, tilt with buttons
   - These controls manipulate the Three.js camera
7. Tap **Start VR** → camera position transfers to A-Frame → stereo mode activates → gyroscope enables
8. Place phone in VR box → head tracking works automatically

### Mobile Controls

On touch devices (`@media (hover: none) and (pointer: coarse)`), a column of control buttons appears on the right edge:

| Button | Action | Implementation |
|--------|--------|---------------|
| ＋ | Zoom in | Move camera toward target by 8 units |
| − | Zoom out | Move camera away from target by 8 units |
| ▲ | Tilt up | Decrease polar angle by 7.5° |
| ▼ | Tilt down | Increase polar angle by 7.5° |
| ◀ | Rotate left | Rotate camera +10° around Y axis |
| ▶ | Rotate right | Rotate camera -10° around Y axis |

### Camera Transfer (Three.js → A-Frame)

When entering VR mode, the camera position and look direction are transferred:

```javascript
function transferCameraToVR() {
    // Position: copy Three.js camera XYZ to A-Frame camera rig
    rig.setAttribute('position', { x, y, z });
    
    // Rotation: compute pitch/yaw from camera→target direction
    var dir = new T.Vector3().subVectors(target, camera.position).normalize();
    var pitch = Math.asin(-dir.y) * (180/Math.PI);  // degrees
    var yaw = Math.atan2(dir.x, dir.z) * (180/Math.PI);
    vrCam.setAttribute('rotation', { x: pitch, y: yaw, z: 0 });
}
```

### Touch Event Handling

The canvas has `touch-action: none` CSS and JavaScript `preventDefault()` on all touch events to prevent the browser from intercepting gestures:

```javascript
canvas.addEventListener('touchstart', e => { if (e.touches.length >= 1) e.preventDefault(); }, { passive: false });
canvas.addEventListener('touchmove', e => { e.preventDefault(); }, { passive: false });
canvas.addEventListener('touchend', e => { e.preventDefault(); }, { passive: false });
```

### GLB Model Specs

Generated by `src/export_vr.py`:
- Grid: 256×256 vertices
- Horizontal: 100m × 100m (centered at origin)
- Vertical: 20% relief ratio (peak-to-valley = 20m)
- Vertex colors: FSI green→yellow→red
- Y-up coordinate system
- File size: ~2.5 MB
- Bounding box: ~99.6 × 23.4 × 99.6 m

### A-Frame Scene Configuration

```html
<a-scene vr-mode-ui="enabled: true"
         device-orientation-permission-ui="enabled: true"
         renderer="antialias: true; colorManagement: true"
         embedded>
    <a-sky color="#1a1d2e"></a-sky>
    <a-entity light="type: ambient; intensity: 0.7"></a-entity>
    <a-entity light="type: directional; intensity: 0.9" position="50 100 50"></a-entity>
    <a-entity gltf-model="/api/export-vr/{{ job_id }}"></a-entity>
    <a-entity id="cameraRig" position="0 40 60">
        <a-camera look-controls="magicWindowTrackingEnabled: true"
                  fov="80" near="0.1" far="2000"
                  rotation="-30 0 0">
        </a-camera>
    </a-entity>
</a-scene>
```

---

## 14. Module Reference

### `src/gee_data.py` (101 lines)

| Function | Purpose |
|----------|---------|
| `initialize_ee(project_id)` | Authenticate (if needed) and init GEE |
| `create_aoi(lat, lon, radius_km)` | Create circular `ee.Geometry` buffer |
| `fetch_dem(aoi)` | Fetch SRTM DEM, downsample 30m→250m |
| `compute_slope(dem)` | `ee.Terrain.slope()` in degrees |
| `fetch_soil(aoi)` | Return (clay, sand) `ee.Image` pair |
| `ee_image_to_numpy(image, aoi)` | Download EE image as 2D numpy array |

### `src/preprocessing.py` (71 lines)

| Function | Purpose |
|----------|---------|
| `normalize_elevation(dem, aoi)` | Inverted min-max normalization → [0,1] |
| `normalize_slope(slope, aoi)` | Inverted min-max normalization → [0,1] |
| `compute_soil_index(clay, sand)` | `(clay-sand)/100` rescaled [-1,1]→[0,1] |
| `validate_range(image, aoi, label)` | Print min/max stats for debugging |

### `src/hydrology.py` (226 lines)

| Function | Purpose |
|----------|---------|
| `fetch_water_features(lat, lon, radius_m)` | Download waterways + water polygons from OSM |
| `compute_river_proximity(water_gdf, bounds)` | Rasterize water → EDT → invert → normalize; returns `(river_factor, water_mask, meta)` |
| `compute_flow_accumulation(dem_array)` | D8 algorithm: flow direction → topological sort → accumulate upstream cells |
| `normalize_flow_accumulation(flow_accum)` | `log1p()` → min-max normalize to [0,1] |
| `numpy_to_ee_image(array, bounds, band_name)` | Upload 2D numpy array to GEE via `pixelLonLat()` trick |

### `src/flood_model.py` (178 lines)

| Function | Purpose |
|----------|---------|
| `compute_base_risk(elev, slope, soil, river, flow, weights)` | 5-factor weighted sum; river dampened by slope |
| `apply_rainfall_multiplier(base_risk, rainfall_mm)` | `FSI = clamp(BaseRisk × (R/R_max)^α, 0, 1)` |
| `apply_water_mask(fsi, water_mask, rainfall_mm)` | Force water pixels to 1.0 if rain > 30% of R_max |
| `classify_risk(risk)` | Static 3-class classification (Low/Medium/High) |
| `classify_risk_adaptive(fsi, aoi)` | Adaptive thresholds relative to MaxFSI |
| `export_geotiff(image, aoi, filename)` | Export EE image to local GeoTIFF via `geemap` |

### `src/ahp.py` (113 lines)

| Function | Purpose |
|----------|---------|
| `compute_ahp_weights(matrix, names)` | Column normalize → row average → consistency check |
| `get_validated_weights()` | Compute + validate (raises if CR ≥ 0.1) |

**Constants:**
- `PAIRWISE_MATRIX`: 5×5 Saaty comparison matrix
- `FACTOR_NAMES`: `["elevation", "slope", "soil", "river", "flow_accum"]`
- `RI_TABLE`: Random Index for n=1..10

### `src/road_network.py` (196 lines)

| Function | Purpose |
|----------|---------|
| `load_road_network(lat, lon, radius_m)` | Download drivable road graph from OSM (cached, 3 retries) |
| `sample_risk_on_edges(G, risk_tif_path)` | Sample FSI at edge midpoints (parallel `ProcessPoolExecutor`) |
| `penalize_flooded_edges(G)` | Remove edges with FSI ≥ 0.66, scale others by `1 + risk × 10` |
| `label_safe_nodes(G, risk_tif_path)` | Tag nodes with `is_safe=True` where FSI < 0.3 |

### `src/evacuation.py` (127 lines)

| Function | Purpose |
|----------|---------|
| `find_escape_route(G, start_lat, start_lon)` | A* from origin to nearest safe-zone node; haversine heuristic; returns `(route_coords, dest_info)` |

The escape routing finds the shortest path to the nearest node with `is_safe=True` (FSI < 0.3), using flood-penalised edge lengths as weights. This is physically correct: escape the flood boundary rather than search for a specific building.

### `src/export_vr.py` (140 lines)

| Function | Purpose |
|----------|---------|
| `build_terrain_glb(dem_tif, fsi_tif, output, grid_size, terrain_size)` | Read GeoTIFFs → resample → build vertex mesh → color from FSI → export GLB |
| `_fsi_color(fsi)` | FSI value → [R,G,B,A] using green→yellow→red ramp |

### `src/decision_support.py` (149 lines)

| Function | Purpose |
|----------|---------|
| `compute_risk_statistics(risk_tif_path)` | Pixel counts/percentages/area per risk class |
| `count_affected_roads(G)` | Count road segments by risk category |
| `generate_report(...)` | Structured JSON report + plain-text summary |

### `src/visualization.py` (134 lines)

| Function | Purpose |
|----------|---------|
| `create_risk_map(...)` | Build Folium map with risk overlay, roads, evacuation, shelters |

---

## 15. Configuration Reference

All constants in `config.py`:

```python
# Google Earth Engine
GEE_PROJECT_ID = "gisproj-487215"

# Default AOI (Hyderabad, India)
DEFAULT_LAT = 17.3850
DEFAULT_LON = 78.4867
DEFAULT_RADIUS_KM = 10

# Data Sources
DEM_ASSET = "USGS/SRTMGL1_003"
CLAY_ASSET = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
SAND_ASSET = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
SOIL_BAND = "b0"

# Processing
EXPORT_SCALE = 250        # metres (matches soil resolution)
CRS = "EPSG:4326"
MAX_PIXELS = 1e9

# MCDA Weights (AHP-derived, CR = 0.006)
WEIGHTS = {
    "elevation":  0.2319,
    "slope":      0.0906,
    "soil":       0.0906,
    "river":      0.3912,
    "flow_accum": 0.1956,
}

# Rainfall Multiplier
RAIN_MAX = 150.0          # urban extreme rainfall threshold (mm)
RAIN_ALPHA = 1.2          # nonlinear exponent

# Risk Classification Thresholds
RISK_THRESHOLDS = {
    "low_max":    0.3,
    "medium_max": 0.6,
}

# Evacuation
FLOOD_RISK_PENALTY_FACTOR = 10
HIGH_RISK_ROAD_THRESHOLD = 0.66

# Output Paths
OUTPUT_DIR = "output"
RISK_GEOTIFF = "flood_risk.tif"
RISK_MAP_HTML = "flood_risk_map.html"
REPORT_JSON = "situation_report.json"
```

---

## 16. Output Files

| File | Format | Description |
|------|--------|-------------|
| `output/flood_risk.tif` | GeoTIFF | FSI raster (continuous 0–1) |
| `output/dem_terrain.tif` | GeoTIFF | DEM elevation raster |
| `output/flood_risk_classified.tif` | GeoTIFF | 3-class classified risk (1/2/3) |
| `output/risk_overlay_<job_id>.png` | PNG | 4× upsampled, hillshade-blended risk overlay |
| `output/terrain_<job_id>.glb` | GLB | 3D terrain model for VR |
| `output/flood_risk_map.html` | HTML | Standalone Folium map |
| `output/situation_report.json` | JSON | Structured risk report |

---

## 17. CLI Usage

### Basic

```bash
python main.py --lat 17.385 --lon 78.4867 --radius 10 --rainfall 150
```

### Pipeline Phases (CLI)

1. **Phase 0**: AHP weight derivation and validation
2. **Phase 1**: GEE initialization + AOI creation
3. **Phase 2**: Terrain data fetch + preprocessing (DEM, slope, soil)
4. **Phase 3**: Hydrology (water features, river proximity, flow accumulation)
5. **Phase 4**: Flood risk model (BaseRisk × RainFactor)
6. **Phase 5**: Road network analysis (load, sample risk, penalize)
7. **Phase 6**: Evacuation routing (find shelters, A* routing)
8. **Phase 7**: Visualization (Folium map)
9. **Phase 8**: Decision support (statistics, report)

### Output

```
══════════════════════════════════════════════════════════════
  ✅  Pipeline complete!
  📄  GeoTIFF        → output/flood_risk.tif
  🗺️   Interactive map → output/flood_risk_map.html
  📊  Report         → output/situation_report.json
══════════════════════════════════════════════════════════════
```

---

## 18. Validation & Debugging

### Multi-Location Validation (`validate_model.py`)

Tests 7 geographically distinct regions × 2 rainfall scenarios (10mm and 150mm):

| Location | Type |
|----------|------|
| Varanasi | River floodplain |
| Chennai | Coastal lowland |
| Dehradun | Mountain terrain |
| Kolkata | Delta system |
| Bengaluru | Urban plateau |
| Leh | High mountain desert |
| Aluva | Known flood region (Kerala) |

Run:
```bash
python validate_model.py
```

Outputs per-location: BaseRisk stats, FSI stats per rainfall, class percentages, and checks consistency across terrain types.

### Factor Debugging (`debug_factors.py`)

Quick inspection of the model internals for Hyderabad (default AOI):
- Prints BaseRisk min/max/mean
- Tests 10mm and 150mm rainfall scenarios
- Shows pixel percentages per class

```bash
python debug_factors.py
```

---

## 19. Known Issues & Constraints

### Technical Constraints

1. **EXPORT_SCALE = 250m**: All raster analysis is at 250m resolution (matching soil data). DEM is 30m native but downsampled.
2. **In-memory job store**: Job state is lost on server restart. No persistence layer.
3. **Single-threaded GEE**: GEE API calls are sequential (can't parallelize ee operations).
4. **Self-signed cert**: Browsers show security warning. Required for WebXR on mobile.
5. **OSM Overpass rate limits**: Heavy use may trigger rate limiting from Overpass API.
6. **Flow accumulation**: Uses simplified D8 algorithm (O(n) topological sort, but Python loops). For production, use pysheds or WhiteboxTools.

### VR-Specific

1. **Multiple THREE.js instances**: Console warning is expected (r146 + A-Frame's r158). Harmless.
2. **Pinch-to-zoom on mobile**: May not work reliably on all devices despite `touch-action: none` and `preventDefault()`. On-screen buttons are the reliable fallback.
3. **VR stereo on desktop**: Not supported; desktop shows QR code for phone access.
4. **A-Frame look-controls**: Intercepts all touch events when active. Cannot use custom orbit controls inside A-Frame — this is why the dual-renderer architecture exists.

### Model Limitations

1. **No temporal dynamics**: FSI is static (snapshot for given rainfall). No time-series simulation.
2. **Soil data resolution**: OpenLandMap soil is 250m — coarse for urban areas.
3. **No land use/land cover**: Urban vs. vegetation distinction not included as a factor.
4. **D8 flow direction**: Simplified — doesn't handle flat areas well. Multiple flow direction (MFD) would be more accurate.
5. **Rainfall is uniform**: Applied as a single multiplier across the entire AOI. No spatial precipitation gradient.

---

## 20. File-by-File Reference

### Root Files

| File | Lines | Purpose |
|------|-------|---------|
| `app.py` | 697 | Flask server: all routes, pipeline runner, risk PNG generation, building fetch, road-to-GeoJSON, impact statistics |
| `config.py` | 64 | All constants: GEE project, AHP weights, thresholds, paths |
| `main.py` | 228 | CLI entry point: args parsing, 8-phase pipeline, console output |
| `requirements.txt` | 15 | Python package dependencies |
| `validate_model.py` | 228 | 7-location × 2-rainfall validation harness |
| `debug_factors.py` | 105 | Quick factor inspection for default AOI |
| `cert.pem` | — | Self-signed SSL certificate |
| `key.pem` | — | SSL private key |
| `.gitignore` | 11 | Excludes `venv/`, `output/`, `cache/`, `__pycache__/`, `*.tif`, `.DS_Store` |

### `src/` Modules

| File | Lines | Key Functions |
|------|-------|--------------|
| `__init__.py` | 1 | Package marker |
| `gee_data.py` | 101 | `initialize_ee`, `create_aoi`, `fetch_dem`, `compute_slope`, `fetch_soil`, `ee_image_to_numpy` |
| `preprocessing.py` | 71 | `normalize_elevation`, `normalize_slope`, `compute_soil_index`, `validate_range` |
| `hydrology.py` | 226 | `fetch_water_features`, `compute_river_proximity`, `compute_flow_accumulation`, `normalize_flow_accumulation`, `numpy_to_ee_image` |
| `flood_model.py` | 178 | `compute_base_risk`, `apply_rainfall_multiplier`, `apply_water_mask`, `classify_risk`, `classify_risk_adaptive`, `export_geotiff` |
| `ahp.py` | 113 | `compute_ahp_weights`, `get_validated_weights`; contains `PAIRWISE_MATRIX`, `FACTOR_NAMES`, `RI_TABLE` |
| `road_network.py` | 196 | `load_road_network` (cached, 3 retries), `sample_risk_on_edges` (parallel), `penalize_flooded_edges`, `label_safe_nodes` |
| `evacuation.py` | 127 | `find_escape_route` (A* to nearest safe zone, haversine heuristic) |
| `export_vr.py` | 140 | `build_terrain_glb` (trimesh GLB), `_fsi_color` (green→yellow→red ramp) |
| `decision_support.py` | 149 | `compute_risk_statistics`, `count_affected_roads`, `generate_report` |
| `visualization.py` | 134 | `create_risk_map` (Folium), `_add_risk_overlay`, `_add_road_layer` |

### `static/` Frontend

| File | Lines | Purpose |
|------|-------|---------|
| `app.js` | 696 | Leaflet map init, Nominatim search, click handling, analysis polling, overlay rendering, building markers, evacuation route, 3D toggle, VR viewer launch |
| `terrain3d.js` | 401 | Three.js r146 3D terrain engine: mesh construction from DEM/FSI JSON, water plane, building boxes, evacuation tube, OrbitControls, lighting, animation |
| `style.css` | 1,033 | Full dark theme: glassmorphism sidebar, map controls, 3D panel, status bar, building popups, analysis button animations, responsive breakpoints |

### `templates/` HTML

| File | Lines | Purpose |
|------|-------|---------|
| `index.html` | 150 | Main SPA: Leaflet CDN, Three.js r146 CDN, sidebar structure, map div, 3D canvas container, script includes |
| `vr_viewer.html` | 760 | VR viewer: Three.js r146 + OrbitControls + GLTFLoader (saved to globals) → A-Frame 1.5.0 → dual-renderer viewer with mobile controls, VR setup overlay, QR modal, camera transfer |

---

## Appendix A: Risk Overlay PNG Generation

The risk overlay PNG (`_create_risk_png` in `app.py`) uses a multi-step process:

1. Read FSI GeoTIFF
2. **4× bilinear upsampling** (`scipy.ndimage.zoom`, order=1) — 250m pixels → ~63m visual
3. Normalize to [0,1]
4. Apply **custom 5-color ramp**: green(safe) → lime → yellow(moderate) → orange → red(danger)
5. If DEM available: compute **hillshade** (azimuth=315°, altitude=45°) from gradient
6. **Blend**: 65% FSI color + 35% hillshade
7. Set alpha: 65% where valid, 0% where NaN
8. Save as PNG

## Appendix B: Building Impact Assessment

Buildings fetched from OSM Overpass API are cross-referenced with the FSI raster:

```python
for building in buildings:
    col, row = ~transform * (building['lon'], building['lat'])
    fsi = band[int(row), int(col)]
    building['fsi'] = fsi
```

Population estimates use fixed per-floor multipliers:
- Residential: 4 people/floor
- Commercial: 10 people/floor
- Hospital: 50 people/floor
- School: 30 people/floor

Impact statistics: `at_risk` (FSI ≥ 0.33), `high_risk` (FSI ≥ 0.66), `population_at_risk`, `critical_facilities` (hospitals/schools at risk).

## Appendix C: Road Network Processing

1. **Download**: `osmnx.graph_from_point()` with `network_type="drive"`, cached by (lat, lon, radius)
2. **Risk sampling**: For each edge, compute midpoint, sample FSI at that coordinate using rasterio inverse transform. Parallelized with `ProcessPoolExecutor` for graphs > 500 edges.
3. **Penalization**: Edges with FSI ≥ 0.66 are **removed** (impassable). Remaining edges: `length *= (1 + risk × 10)`
4. **Safe zones**: Nodes with FSI < 0.3 are tagged `is_safe=True`
5. **Escape routing**: A* from origin to nearest `is_safe` node, using penalized lengths and haversine heuristic

## Appendix D: Flow Accumulation (D8 Algorithm)

```
For each cell:
    1. Find steepest downhill neighbor (D8 direction)
    2. Store flow direction index (0-7) or -1 (pit)

Sort all cells by elevation (highest first)

For each cell (high to low):
    If has flow direction:
        downstream.accumulation += this.accumulation
```

Result: each cell's value = number of upstream cells that drain through it. Log-transformed and normalized to [0,1].

## Appendix E: Network & HTTPS Setup for Phone VR

1. **Same WiFi**: Phone and computer must be on the same local network
2. **Network IP detection**: `socket.connect(("8.8.8.8", 80))` → `getsockname()[0]`
3. **HTTPS required**: WebXR sensors (gyroscope) require secure context
4. **Self-signed cert**: Generated with OpenSSL; phone must accept the certificate warning
5. **QR code**: Encodes `https://<network_ip>:5050/vr/<job_id>` for quick phone access

---

*Last updated: 14 February 2026*
