# Project Context: Flood Susceptibility & Evacuation System

> **Purpose:** Drop this file into any AI agent's context window to give it full project understanding. Covers architecture, data flow, every module, every endpoint, every file, how to run, how to extend, and known issues.

---

## 1. Project Overview

**What it does:** Real-time flood susceptibility analysis for any location on Earth. User clicks a point on a map (or searches a place name), the system computes a 6-factor Flood Susceptibility Index (FSI), overlays it on the map, finds evacuation routes, and shows a 3D terrain visualization.

**Stack:**
- **Backend:** Python 3.11+, Flask (port 5050), Google Earth Engine (GEE), OSMnx
- **Frontend:** Vanilla JS + Leaflet (2D map) + Three.js r146 (3D view)
- **Hosting:** Local development server (`python app.py`)

**Key technical achievement:** The FSI model uses AHP (Analytic Hierarchy Process) with 5 spatial factors weighted by a mathematically consistent pairwise comparison matrix (CR = 0.006), multiplied by a nonlinear rainfall amplifier.

---

## 2. Directory Structure

```
gisproj/
├── app.py                  # Flask server (main entry point, all API routes)
├── config.py               # All constants: GEE project, AHP weights, thresholds
├── main.py                 # CLI version of the pipeline (alternative to web GUI)
├── requirements.txt        # Python dependencies
├── validate_model.py       # Model validation script
├── debug_factors.py        # Factor debugging/inspection script
│
├── src/                    # Core computation modules
│   ├── __init__.py
│   ├── gee_data.py         # GEE auth, AOI creation, DEM/slope/soil fetch
│   ├── preprocessing.py    # Factor normalization (elevation, slope, soil)
│   ├── hydrology.py        # River proximity, flow accumulation, numpy→EE
│   ├── flood_model.py      # BaseRisk computation, rainfall multiplier, classification
│   ├── ahp.py              # AHP weight derivation (Saaty matrix → eigenvector)
│   ├── road_network.py     # OSM road graph, flood risk sampling, safe-zone detection
│   ├── evacuation.py       # A* escape routing to nearest safe zone
│   ├── decision_support.py # Risk statistics, road counts, report generation
│   └── visualization.py    # Folium HTML map generation (standalone)
│
├── static/
│   ├── app.js              # Frontend: map init, search, building markers, 3D toggle
│   ├── terrain3d.js        # Three.js 3D engine: terrain, water, buildings, routes
│   └── style.css           # All CSS (dark theme, glassmorphism, responsive)
│
├── templates/
│   └── index.html          # Single-page app HTML (Leaflet + Three.js CDN)
│
├── output/                 # Generated files (GeoTIFFs, PNGs, JSONs)
│   ├── flood_risk.tif      # FSI raster (after analysis)
│   ├── dem_terrain.tif     # DEM raster (after analysis)
│   ├── risk_overlay_*.png  # Risk PNG overlays per job
│   └── situation_report.json
│
├── cache/                  # OSMnx road network cache
└── venv/                   # Python virtual environment
```

---

## 3. The FSI Model (Core Algorithm)

### Formula
```
FSI(x) = BaseRisk(x) × RainFactor
```

### BaseRisk — 5-Factor AHP Overlay
```
BaseRisk = w₁·Elevation + w₂·Slope + w₃·Soil + w₄·RiverEffective + w₅·FlowAccum
```

Where `RiverEffective = RiverProximity × SlopeFactor` (river influence dampened on steep slopes).

### AHP Weights (from `config.py`)
| Factor | Weight | Source |
|---|---|---|
| Elevation | 0.2319 | SRTM 30m DEM (downsampled to 250m) |
| Slope | 0.0906 | Derived from DEM |
| Soil | 0.0906 | OpenLandMap clay+sand (surface depth) |
| River proximity | 0.3912 | OSM waterways + Euclidean distance |
| Flow accumulation | 0.1956 | D8 algorithm on DEM |

**Consistency Ratio:** CR = 0.006 (threshold < 0.10 ✓)

### Rainfall Multiplier
```
RainFactor = (Rain / RainMax)^α
```
- `RainMax = 150 mm` (urban extreme threshold)
- `α = 1.2` (nonlinear amplification)

### Risk Classification
| Class | FSI Range | Interpretation |
|---|---|---|
| Low | 0.00 – 0.30 | Safe for travel |
| Medium | 0.30 – 0.60 | Caution advised |
| High | 0.60 – 1.00 | Dangerous, avoid |

---

## 4. Data Pipeline (what happens when user clicks "Analyse")

```
User clicks map → POST /api/analyze → background thread → _run_pipeline()
```

### Phase-by-phase:

1. **GEE Init** — `initialize_ee()` authenticates with Google Earth Engine
2. **DEM + Terrain** — `fetch_dem()` gets SRTM 30m, downsampled to 250m. `compute_slope()` derives slope.
3. **Soil** — `fetch_soil()` gets clay/sand from OpenLandMap. `compute_soil_index()` normalizes.
4. **Normalization** — `normalize_elevation()` and `normalize_slope()` invert/scale factors to [0,1]
5. **Hydrology** — `fetch_water_features()` from OSM via OSMnx, `compute_river_proximity()` rasterizes + distance transform, `compute_flow_accumulation()` D8 algorithm
6. **Base Risk** — `compute_base_risk()` weighted overlay of 5 factors
7. **Rainfall** — `apply_rainfall_multiplier()` scales by nonlinear rain factor
8. **Water Mask** — `apply_water_mask()` forces water bodies to FSI=1.0 in heavy rain
9. **Classification** — `classify_risk()` bins into Low/Medium/High
10. **Export** — `export_geotiff()` saves FSI and DEM as GeoTIFFs
11. **Overlay PNG** — `_create_risk_png()` upsamples + hillshade + color ramp
12. **Buildings** — `_fetch_buildings()` queries OSM Overpass for building footprints
13. **Roads** — `load_road_network()` gets drivable graph, `sample_risk_on_edges()` overlays FSI
14. **Evacuation** — `penalize_flooded_edges()` + `label_safe_nodes()` + `find_escape_route()` A*
15. **Impact Stats** — `_compute_impact_stats()` cross-references buildings with FSI raster
16. **Result** — JSON with bounds, overlay URL, stats, roads, route, buildings, impact

---

## 5. API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `index.html` |
| `POST` | `/api/analyze` | Starts analysis. Body: `{lat, lon, radius_km, rainfall_mm}`. Returns `{job_id}` |
| `GET` | `/api/status/<job_id>` | Poll for progress: `{status, progress, result, error}` |
| `GET` | `/api/overlay/<job_id>` | Serves the risk PNG overlay image |
| `GET` | `/api/terrain3d/<job_id>` | JSON with 100×100 grids of DEM + FSI for 3D view |

### `/api/analyze` request body:
```json
{
  "lat": 17.385,
  "lon": 78.487,
  "radius_km": 5,
  "rainfall_mm": 150
}
```

### `/api/status` result object (when complete):
```json
{
  "status": "done",
  "result": {
    "bounds": {"south": ..., "west": ..., "north": ..., "east": ...},
    "overlay_url": "/api/overlay/<job_id>",
    "risk_stats": {"low_risk": {...}, "medium_risk": {...}, "high_risk": {...}, ...},
    "road_stats": {"total_segments": ..., "high_risk_segments": ..., ...},
    "roads": {"type": "FeatureCollection", "features": [...]},
    "evacuation_route": {"type": "Feature", "geometry": {"coordinates": [...]}},
    "escape_destination": {"lat": ..., "lon": ..., "fsi": ...},
    "buildings": [{"lat": ..., "lon": ..., "type": "hospital", "floors": 3, "fsi": 0.4, ...}],
    "impact_stats": {"total_buildings": ..., "at_risk": ..., "high_risk": ..., "population_at_risk": ..., "critical_facilities": ...},
    "params": {"lat": ..., "lon": ..., "radius_km": ..., "rainfall_mm": ...}
  }
}
```

---

## 6. Module Reference

### `src/gee_data.py` — Earth Engine Interface
- `initialize_ee()` — Auth + init GEE with project ID
- `create_aoi(lat, lon, radius_km)` — Create circular AOI geometry
- `fetch_dem(aoi)` — SRTM 30m DEM, downsampled to 250m
- `compute_slope(dem)` — Slope in degrees from DEM
- `fetch_soil(aoi)` — (clay, sand) images from OpenLandMap
- `ee_image_to_numpy(image, aoi)` — Download EE image as numpy array via GeoTIFF

### `src/preprocessing.py` — Factor Normalization
- `normalize_elevation(dem)` — Higher elevation → lower risk (inverted)
- `normalize_slope(slope)` — Steeper → faster drainage → lower risk (inverted)
- `compute_soil_index(clay, sand)` — Clay-rich soil → higher runoff → higher risk

### `src/hydrology.py` — Water Features
- `fetch_water_features(lat, lon, radius_m)` — Download rivers/lakes from OSM
- `compute_river_proximity(gdf, bounds)` — Rasterize + EDT → proximity factor [0,1]
- `compute_flow_accumulation(dem_array)` — D8 flow accumulation from DEM
- `normalize_flow_accumulation(flow_accum)` — Log-normalize to [0,1]
- `numpy_to_ee_image(array, bounds, name)` — Upload numpy array to GEE as image

### `src/flood_model.py` — Risk Computation
- `compute_base_risk(elev, slope, soil, river, flow, weights)` — 5-factor weighted overlay
- `apply_rainfall_multiplier(base_risk, rainfall_mm)` — Nonlinear rain scaling
- `apply_water_mask(fsi, water_mask, rainfall_mm)` — Force water pixels to FSI=1.0
- `classify_risk(risk)` — Static 3-class classification
- `classify_risk_adaptive(fsi, aoi)` — Adaptive thresholds based on scenario max
- `export_geotiff(image, aoi, filename)` — Save EE image to local GeoTIFF

### `src/ahp.py` — Weight Derivation
- Saaty 5×5 pairwise comparison matrix
- Eigenvector method for weight extraction
- Consistency Index (CI) and Consistency Ratio (CR) validation

### `src/road_network.py` — Road Analysis
- `load_road_network(lat, lon, radius_m)` — OSMnx drivable road graph (cached)
- `sample_risk_on_edges(G, tif_path)` — Parallel FSI sampling at edge midpoints
- `penalize_flooded_edges(G)` — Remove high-risk edges, penalize risky ones
- `label_safe_nodes(G, tif_path)` — Tag nodes where FSI < 0.3 as safe zones

### `src/evacuation.py` — Escape Routing
- `find_escape_route(G, start_lat, start_lon)` — A* to nearest safe zone
  - Uses flood-penalized edge lengths
  - Haversine heuristic toward safe nodes
  - Returns route waypoints + destination info

### `src/decision_support.py` — Statistics
- `compute_risk_statistics(tif_path)` — Area percentages per risk class
- `count_affected_roads(G)` — Road segments by risk category
- `generate_report(stats, ...)` — JSON + plain-text situation report

---

## 7. Frontend Architecture

### `index.html`
- Single-page app with sidebar + map layout
- CDN dependencies: Leaflet 1.9.4, Three.js r148, Inter font
- Elements: search bar, coordinate inputs, radius/rainfall sliders, analyse button, results panel, 3D toggle, legend

### `app.js` (~530 lines) — Main Frontend Logic
- **Map init** — Leaflet dark theme (CartoDB dark_all tiles), zoom controls
- **Search** — Nominatim geocoding with 500ms debounce, dropdown results
- **Click handler** — Sets lat/lon, places marker, draws radius circle
- **Analysis** — POST to `/api/analyze`, polls `/api/status` every 1.5s
- **Display functions:**
  - `displayRiskOverlay()` — ImageOverlay of risk PNG
  - `displayRoads()` — GeoJSON polylines color-coded by risk
  - `displayEvacuation()` — Blue animated polyline for escape route
  - `displayEscapeDestination()` — Green marker at safe zone
  - `displayBuildings()` — CircleMarkers from Overpass data, colored by FSI
  - `displayImpactStats()` — Building impact grid (at-risk, high-risk, pop)
  - `displayStats()` — Risk area percentages
- **3D toggle** — Opens/closes full-screen 3D view
- **Clear** — Removes all overlays and markers

### `terrain3d.js` (~480 lines) — Three.js 3D Engine
- **Scene setup** — Dark background, fog, shadows, ACES filmic tone mapping
- **Terrain** — PlaneGeometry with vertex Z from DEM, vertex colors blending elevation + FSI
- **Water** — GLSL shader with:
  - Depth-based coloring (shallow=light blue → deep=navy)
  - Animated ripples (3 overlapping sine waves)
  - Caustic highlights
  - Edge foam
- **Buildings** — BoxGeometry with window strips, roof caps, hospital crosses
  - Colors: red (FSI>0.66), orange (FSI>0.33), type-default otherwise
- **Evacuation route** — CatmullRomCurve3 → TubeGeometry with glow effect
- **Camera presets** — Perspective/oblique/top with smoothstep transitions
- **HUD** — Impact stats + legend + building types + data source

### `style.css` (~960 lines)
- CSS variables for theming (dark mode: `--bg-primary: #0f1117`)
- Glassmorphism panels with `backdrop-filter: blur()`
- Search bar, dropdown results, impact stats grid
- 3D view container (full-screen fixed overlay, z-index: 2000)
- HUD panel (glassmorphic, positioned top-right)
- Camera preset buttons (centered bottom)
- Responsive breakpoints for mobile

---

## 8. How to Run

### Prerequisites
1. Python 3.11+
2. Google Earth Engine account + project
3. GEE authentication (run `earthengine authenticate` once)

### Setup
```bash
cd /Users/vishnu/gisproj
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
source venv/bin/activate
python app.py
# → Open http://localhost:5050
```

### Workflow
1. Search a location or click the map
2. Adjust radius (1-20 km) and rainfall (0-300 mm)
3. Click "Analyse" — takes 30-60 seconds
4. View results: risk overlay, evacuation route, building markers, impact stats
5. Click "Open 3D View" for immersive terrain visualization

---

## 9. External Services Used

| Service | What For | Rate Limits |
|---|---|---|
| Google Earth Engine | DEM, slope, soil data | Free with GEE account |
| OpenStreetMap (via OSMnx) | Road network, waterways | Overpass API limits apply |
| OSM Overpass API | Building footprints | Max 150 buildings per query |
| Nominatim | Location search/geocoding | 1 req/sec (frontend debounced) |
| CartoDB | Dark map tiles | Free CDN |

---

## 10. Configuration Reference (`config.py`)

| Constant | Value | Meaning |
|---|---|---|
| `GEE_PROJECT_ID` | `"gisproj-487215"` | Your GEE project |
| `EXPORT_SCALE` | `250` | Metres per pixel |
| `RAIN_MAX` | `150.0` | Design storm threshold (mm) |
| `RAIN_ALPHA` | `1.2` | Nonlinear exponent |
| `FLOOD_RISK_PENALTY_FACTOR` | `10` | Road weight multiplier for risky segments |
| `HIGH_RISK_ROAD_THRESHOLD` | `0.66` | Remove roads above this FSI |
| `RISK_THRESHOLDS` | `{low_max: 0.3, medium_max: 0.6}` | 3-class risk bins |

---

## 11. Known Issues & Gotchas

1. **Pyre lint errors** — All "Could not find import" errors are false positives because the linter doesn't see the virtualenv. The code runs fine.
2. **GEE authentication** — Must run `earthengine authenticate` before first use. The project ID in `config.py` must match your GEE project.
3. **Overpass API** — Rate limited. Building fetch is capped at 150 results. Can fail under heavy load.
4. **Three.js version** — Must use r148 (last version with `examples/js/controls/OrbitControls.js`). Version r152+ removed the non-module build.
5. **Road network cache** — OSMnx caches the graph for repeated queries with the same AOI. Set `force=True` to bypass.
6. **Large radius** — Radius > 15km can be slow (many GEE pixels + large road graph). Recommended: 3-10 km.
7. **Output directory** — All GeoTIFFs are written to `output/`. These are overwritten on each analysis.

---

## 12. Extending the Project

### Adding a new factor
1. Fetch data in `src/gee_data.py` (e.g., `fetch_landuse()`)
2. Normalize to [0,1] in `src/preprocessing.py`
3. Add weight in `config.py` WEIGHTS dict (must sum to 1)
4. Update `compute_base_risk()` in `src/flood_model.py`
5. Update AHP matrix in `src/ahp.py` and re-derive weights

### Adding a new API endpoint
1. Add route in `app.py` with `@app.route()`
2. Add corresponding frontend fetch call in `app.js`

### Modifying the 3D view
- Terrain rendering: `buildTerrain()` in `terrain3d.js`
- Water shader: `waterVertexShader` / `waterFragmentShader` GLSL strings
- Buildings: `buildBuildings()` — modify `typeColors`, sizes, visual details
- Add new 3D elements: add to `init3DScene()` or call from `load3DTerrain()`

### Changing the risk model
- Modify weights in `config.py`
- Or modify `compute_base_risk()` for factor interactions
- Or modify `apply_rainfall_multiplier()` for different rain behavior

---

## 13. Key Design Decisions

1. **AHP over ML** — AHP provides transparent, interpretable weights. Judges can understand the decision matrix. ML would be a black box.
2. **EE server-side computation** — All heavy raster math runs on Google's servers. Local machine only handles routing and visualization.
3. **Background threading** — Analysis runs in a `threading.Thread` so the UI stays responsive during the 30-60 second pipeline.
4. **A* over Dijkstra** — A* with haversine heuristic is faster for escape routing (single destination type: any safe node).
5. **Vanilla JS over React** — No build step needed. Single HTML page loads instantly. Judges don't need to wait for npm.
6. **Three.js r148 (non-module)** — Avoids ES module complexity. Just `<script>` tags with global `THREE` namespace.
7. **Overpass for buildings** — Gets real-world building data. We cross-reference each building with our FSI raster for accurate impact assessment.

---

## 14. Quick Reference: File Sizes

| File | Lines | Purpose |
|---|---|---|
| `app.py` | 596 | Flask server, all routes, pipeline orchestration |
| `static/app.js` | ~530 | Frontend logic, search, map, building markers |
| `static/terrain3d.js` | ~480 | Three.js 3D visualization engine |
| `static/style.css` | ~960 | All styling |
| `templates/index.html` | ~120 | HTML structure |
| `config.py` | 65 | Configuration constants |
| `src/flood_model.py` | 179 | Core risk model |
| `src/hydrology.py` | 227 | River proximity + flow accumulation |
| `src/road_network.py` | 197 | Road graph + risk sampling |
| `src/evacuation.py` | 128 | A* escape routing |
| `src/decision_support.py` | 150 | Statistics + reporting |
| `src/gee_data.py` | 102 | GEE data fetching |
| `src/preprocessing.py` | ~80 | Factor normalization |
| `src/ahp.py` | ~120 | AHP weight derivation |
