/**
 * app.js – Leaflet map, click-to-analyze, dynamic overlays.
 */

// ── State ──────────────────────────────────────────────────────────────────
let map;
let clickMarker = null;
let radiusCircle = null;
let riskOverlay = null;
let roadsLayer = null;
let evacLayer = null;
let escapeMarker = null;
let buildingsLayer = null;
let selectedLat = null;
let selectedLon = null;
let currentJobId = null;
let pollTimer = null;
let is3DOpen = false;

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    initControls();
    initSearch();
    initSidebarToggle();
    init3DToggle();
});


function initMap() {
    map = L.map('map', {
        center: [17.385, 78.4867],
        zoom: 11,
        zoomControl: false,
    });

    // Dark tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 19,
    }).addTo(map);

    L.control.zoom({ position: 'topright' }).addTo(map);

    // Click handler
    map.on('click', onMapClick);
}


function initControls() {
    const radiusSlider = document.getElementById('radiusSlider');
    const rainfallSlider = document.getElementById('rainfallInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const goBtn = document.getElementById('goToCoordBtn');

    radiusSlider.addEventListener('input', () => {
        document.getElementById('radiusValue').textContent = radiusSlider.value + ' km';
        updateRadiusCircle();
    });

    rainfallSlider.addEventListener('input', () => {
        document.getElementById('rainfallValue').textContent = rainfallSlider.value + ' mm';
    });

    analyzeBtn.addEventListener('click', startAnalysis);

    // Manual coordinate entry — "Go" button
    goBtn.addEventListener('click', () => {
        const lat = parseFloat(document.getElementById('latInput').value);
        const lon = parseFloat(document.getElementById('lonInput').value);
        if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
            alert('Enter valid latitude (-90 to 90) and longitude (-180 to 180)');
            return;
        }
        setLocation(lat, lon);
        map.setView([lat, lon], 12);
    });
}


function initSidebarToggle() {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    toggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
}


// ── Location Search (Nominatim) ───────────────────────────────────────────
function initSearch() {
    const input = document.getElementById('searchInput');
    const btn = document.getElementById('searchBtn');
    const resultsDiv = document.getElementById('searchResults');
    let debounceTimer = null;

    btn.addEventListener('click', () => doSearch(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch(input.value);
    });
    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            if (input.value.length >= 3) doSearch(input.value);
        }, 500);
    });

    // Close results on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-bar') && !e.target.closest('.search-results')) {
            resultsDiv.classList.add('hidden');
        }
    });
}

function doSearch(query) {
    if (!query || query.length < 2) return;
    const resultsDiv = document.getElementById('searchResults');
    resultsDiv.innerHTML = '<div class="search-loading">Searching...</div>';
    resultsDiv.classList.remove('hidden');

    fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5`)
        .then(r => r.json())
        .then(results => {
            if (!results.length) {
                resultsDiv.innerHTML = '<div class="search-loading">No results found</div>';
                return;
            }
            resultsDiv.innerHTML = results.map(r => `
                <div class="search-result-item" data-lat="${r.lat}" data-lon="${r.lon}">
                    <span class="search-result-name">${r.display_name.split(',').slice(0, 3).join(', ')}</span>
                    <span class="search-result-type">${r.type}</span>
                </div>
            `).join('');

            resultsDiv.querySelectorAll('.search-result-item').forEach(item => {
                item.addEventListener('click', () => {
                    const lat = parseFloat(item.dataset.lat);
                    const lon = parseFloat(item.dataset.lon);
                    setLocation(lat, lon);
                    map.setView([lat, lon], 13);
                    resultsDiv.classList.add('hidden');
                    document.getElementById('searchInput').value = item.querySelector('.search-result-name').textContent;
                });
            });
        })
        .catch(() => {
            resultsDiv.innerHTML = '<div class="search-loading">Search failed</div>';
        });
}


// ── 3D View toggle ───────────────────────────────────────────────────────
function init3DToggle() {
    const toggleBtn = document.getElementById('toggle3dBtn');
    const closeBtn = document.getElementById('close3dBtn');

    toggleBtn.addEventListener('click', () => {
        if (!currentJobId) return;
        open3DView();
    });

    closeBtn.addEventListener('click', () => {
        close3DView();
    });

    // VR button
    const vrBtn = document.getElementById('openVrBtn');
    if (vrBtn) {
        vrBtn.addEventListener('click', () => {
            if (!currentJobId) return;
            openVRViewer();
        });
    }
}

function open3DView() {
    is3DOpen = true;
    document.getElementById('view3d').classList.remove('hidden');
    document.getElementById('close3dBtn').classList.remove('hidden');
    document.getElementById('map').style.display = 'none';
    document.getElementById('sidebar').style.display = 'none';
    document.getElementById('sidebarToggle').style.display = 'none';

    // Show 3D HUD with camera controls
    const hud = document.getElementById('hud3d');
    hud.classList.remove('hidden');
    hud.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <h3 style="margin: 0 0 0.5rem 0; font-size: 0.9rem; font-weight: 600; color: #f8fafc;">📐 3D Terrain View</h3>
            <p style="margin: 0; font-size: 0.75rem; color: #94a3b8;">Professional topographic model with flood risk overlay</p>
        </div>
        
        <div style="margin-bottom: 1rem;">
            <div style="font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem;">Camera View</div>
            <div style="display: flex; gap: 0.5rem;">
                <button onclick="setCameraPreset('perspective')" class="btn-camera-preset" data-preset="perspective">Perspective</button>
                <button onclick="setCameraPreset('oblique')" class="btn-camera-preset" data-preset="oblique">Oblique</button>
                <button onclick="setCameraPreset('top')" class="btn-camera-preset" data-preset="top">Top</button>
            </div>
        </div>
        
        <div style="font-size: 0.75rem; color: #94a3b8; line-height: 1.5;">
            <div style="margin-bottom: 0.3rem;">🖱️ <strong>Left drag:</strong> Rotate</div>
            <div style="margin-bottom: 0.3rem;">🖱️ <strong>Right drag:</strong> Pan</div>
            <div>🖱️ <strong>Scroll:</strong> Zoom</div>
        </div>
    `;

    // Load 3D terrain
    if (typeof load3DTerrain === 'function') {
        load3DTerrain(currentJobId);
    }
}

function close3DView() {
    is3DOpen = false;
    document.getElementById('view3d').classList.add('hidden');
    document.getElementById('hud3d').classList.add('hidden');
    document.getElementById('close3dBtn').classList.add('hidden');
    document.getElementById('map').style.display = '';
    document.getElementById('sidebar').style.display = '';
    document.getElementById('sidebarToggle').style.display = '';

    if (typeof destroy3DScene === 'function') {
        destroy3DScene();
    }
    document.getElementById('view3d').innerHTML = '';
}


// ── VR Viewer ──────────────────────────────────────────────────────────────
function openVRViewer() {
    if (!currentJobId) return;

    // Open VR viewer in new tab (works on same machine)
    window.open(`/vr/${currentJobId}`, '_blank');

    // Show QR code panel for phone access
    const panel = document.getElementById('vrQrPanel');
    const qrImg = document.getElementById('vrQrImg');
    const urlText = document.getElementById('vrUrlText');

    qrImg.src = `/api/qr-vr/${currentJobId}`;
    panel.classList.remove('hidden');

    // Fetch the URL to display
    fetch(`/api/qr-vr/${currentJobId}`).then(r => r.ok && r).then(() => {
        // Show the URL text — fetch the real network IP from server
        fetch('/api/network-ip').then(r => r.json()).then(d => {
            urlText.textContent = `https://${d.ip}:5050/vr/${currentJobId}`;
        }).catch(() => {
            const host = window.location.hostname;
            const port = window.location.port || '5050';
            urlText.textContent = `https://${host}:${port}/vr/${currentJobId}`;
        });
    });
}


// ── Map Click ──────────────────────────────────────────────────────────────
function onMapClick(e) {
    setLocation(e.latlng.lat, e.latlng.lng);
}

// ── Set Location (from click or manual input) ──────────────────────────────
function setLocation(lat, lon) {
    selectedLat = lat;
    selectedLon = lon;

    // Update input fields
    document.getElementById('latInput').value = lat.toFixed(5);
    document.getElementById('lonInput').value = lon.toFixed(5);

    // Enable analyse button
    document.getElementById('analyzeBtn').disabled = false;

    // Place marker
    if (clickMarker) map.removeLayer(clickMarker);
    clickMarker = L.marker([selectedLat, selectedLon], {
        icon: L.divIcon({
            className: 'click-marker-wrapper',
            html: '<div class="click-marker"></div>',
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        }),
    }).addTo(map);

    updateRadiusCircle();
}


function updateRadiusCircle() {
    if (!selectedLat || !selectedLon) return;
    const radiusKm = parseInt(document.getElementById('radiusSlider').value);

    if (radiusCircle) map.removeLayer(radiusCircle);
    radiusCircle = L.circle([selectedLat, selectedLon], {
        radius: radiusKm * 1000,
        color: '#4fc3f7',
        weight: 2,
        dashArray: '8 6',
        fillColor: '#4fc3f7',
        fillOpacity: 0.04,
        className: 'radius-circle',
    }).addTo(map);
}


// ── Analysis ───────────────────────────────────────────────────────────────
function startAnalysis() {
    if (!selectedLat || !selectedLon) return;

    const radiusKm = parseInt(document.getElementById('radiusSlider').value);
    const rainfallMm = parseInt(document.getElementById('rainfallInput').value);

    // Clear previous results
    clearResults();

    // UI state
    const btn = document.getElementById('analyzeBtn');
    btn.classList.add('running');
    btn.querySelector('.btn-text').textContent = 'Analysing...';
    btn.querySelector('.btn-icon').textContent = '⏳';

    showProgress('Sending request...');

    // Start API call
    fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            lat: selectedLat,
            lon: selectedLon,
            radius_km: radiusKm,
            rainfall_mm: rainfallMm,
        }),
    })
        .then(r => r.json())
        .then(data => {
            currentJobId = data.job_id;
            pollProgress();
        })
        .catch(err => {
            showError('Failed to start analysis: ' + err.message);
        });
}


function pollProgress() {
    if (!currentJobId) return;

    fetch(`/api/status/${currentJobId}`)
        .then(r => r.json())
        .then(job => {
            updateProgressText(job.progress);

            if (job.status === 'done') {
                onAnalysisComplete(job.result);
            } else if (job.status === 'error') {
                showError(job.error);
            } else {
                // Keep polling
                pollTimer = setTimeout(pollProgress, 1500);
            }
        })
        .catch(() => {
            pollTimer = setTimeout(pollProgress, 2000);
        });
}


function onAnalysisComplete(result) {
    // Reset button
    const btn = document.getElementById('analyzeBtn');
    btn.classList.remove('running');
    btn.querySelector('.btn-text').textContent = 'Analyse';
    btn.querySelector('.btn-icon').textContent = '⚡';

    hideProgress();

    // Display results
    displayRiskOverlay(result);
    displayRoads(result);
    displayEvacuation(result);
    displayEscapeDestination(result);
    displayBuildings(result);
    displayImpactStats(result);
    displayStats(result);
}


// ── Overlays ───────────────────────────────────────────────────────────────
function displayRiskOverlay(result) {
    if (riskOverlay) map.removeLayer(riskOverlay);

    const b = result.bounds;
    riskOverlay = L.imageOverlay(
        result.overlay_url + '?t=' + Date.now(),
        [[b.south, b.west], [b.north, b.east]],
        { opacity: 0.65, interactive: false }
    ).addTo(map);

    // Fit map to bounds
    map.fitBounds([[b.south, b.west], [b.north, b.east]], { padding: [50, 50] });
}


function displayRoads(result) {
    if (!result.roads) return;
    if (roadsLayer) map.removeLayer(roadsLayer);

    roadsLayer = L.geoJSON(result.roads, {
        style: (feature) => {
            const risk = feature.properties.risk;
            let color = '#6b7280'; // grey
            if (risk > 0.66) color = '#e53935';
            else if (risk > 0.33) color = '#ffa726';

            return {
                color: color,
                weight: 2,
                opacity: 0.7,
            };
        },
        onEachFeature: (feature, layer) => {
            layer.bindTooltip(`Risk: ${feature.properties.risk}`, {
                sticky: true,
                className: 'risk-tooltip',
            });
        },
    }).addTo(map);
}


function displayEvacuation(result) {
    if (!result.evacuation_route) return;
    if (evacLayer) map.removeLayer(evacLayer);

    evacLayer = L.geoJSON(result.evacuation_route, {
        style: {
            color: '#42a5f5',
            weight: 5,
            opacity: 0.9,
            dashArray: '12 8',
        },
    }).addTo(map);
}


function displayEscapeDestination(result) {
    if (escapeMarker) { map.removeLayer(escapeMarker); escapeMarker = null; }

    if (!result.escape_destination) return;

    const dest = result.escape_destination;
    escapeMarker = L.circleMarker([dest.lat, dest.lon], {
        radius: 12,
        fillColor: '#66bb6a',
        color: '#fff',
        weight: 3,
        fillOpacity: 0.9,
        className: 'escape-destination-marker',
    }).addTo(map);

    escapeMarker.bindTooltip(
        `🛡️ Safe Zone (FSI=${(dest.fsi || 0).toFixed(3)})`,
        { permanent: true, direction: 'top', offset: [0, -14], className: 'escape-tooltip' }
    );
}


// ── Building markers on 2D map ─────────────────────────────────────────────
function displayBuildings(result) {
    if (buildingsLayer) { map.removeLayer(buildingsLayer); buildingsLayer = null; }
    const buildings = result.buildings;
    if (!buildings || !buildings.length) return;

    const typeIcons = {
        hospital: '🏥',
        school: '🏫',
        commercial: '🏢',
        residential: '🏠',
    };

    const markers = buildings.map(b => {
        const fsi = b.fsi || 0;
        let fillColor = '#66bb6a';
        if (fsi >= 0.66) fillColor = '#e53935';
        else if (fsi >= 0.33) fillColor = '#ffa726';

        const marker = L.circleMarker([b.lat, b.lon], {
            radius: b.type === 'hospital' || b.type === 'school' ? 7 : 4,
            fillColor: fillColor,
            color: '#fff',
            weight: 1,
            fillOpacity: 0.8,
        });

        const icon = typeIcons[b.type] || '🏠';
        const name = b.name ? `<strong>${b.name}</strong><br>` : '';
        marker.bindTooltip(
            `${icon} ${name}${b.type} (${b.floors}F)<br>FSI: ${fsi.toFixed(3)}<br>Est. Pop: ${b.pop}`,
            { sticky: true, className: 'building-tooltip' }
        );
        return marker;
    });

    buildingsLayer = L.layerGroup(markers).addTo(map);
}


// ── Impact stats display ──────────────────────────────────────────────────
function displayImpactStats(result) {
    const div = document.getElementById('impactStats');
    const impact = result.impact_stats;
    if (!impact || !impact.total_buildings) {
        div.innerHTML = '';
        return;
    }

    const riskPct = impact.total_buildings > 0
        ? ((impact.at_risk / impact.total_buildings) * 100).toFixed(0)
        : 0;

    div.innerHTML = `
        <h3>🏗️ Building Impact</h3>
        <div class="impact-grid">
            <div class="impact-item">
                <span class="impact-num">${impact.total_buildings}</span>
                <span class="impact-label">Buildings</span>
            </div>
            <div class="impact-item warn">
                <span class="impact-num">${impact.at_risk}</span>
                <span class="impact-label">At Risk (${riskPct}%)</span>
            </div>
            <div class="impact-item danger">
                <span class="impact-num">${impact.high_risk}</span>
                <span class="impact-label">High Risk</span>
            </div>
            <div class="impact-item">
                <span class="impact-num">${(impact.population_at_risk || 0).toLocaleString()}</span>
                <span class="impact-label">Pop. at Risk</span>
            </div>
        </div>
        ${impact.critical_facilities > 0 ? `
            <div class="impact-critical">
                ⚠️ <strong>${impact.critical_facilities}</strong> critical facilities (hospitals/schools) at risk
            </div>
        ` : ''}
    `;
}


// ── Stats display ──────────────────────────────────────────────────────────
function displayStats(result) {
    const stats = result.risk_stats;
    if (!stats) return;

    const grid = document.getElementById('statsGrid');
    grid.innerHTML = '';

    // Total area card
    grid.innerHTML += `
        <div class="stat-card total">
            <div>
                <div class="stat-label">Total Area</div>
                <div class="stat-value">${stats.total_area_km2} km²</div>
            </div>
            <div>
                <div class="stat-label">Mean FSI</div>
                <div class="stat-value">${stats.mean_risk}</div>
            </div>
        </div>
    `;

    // Risk class cards
    const classes = [
        { key: 'low_risk', label: 'Low', cls: 'low' },
        { key: 'medium_risk', label: 'Medium', cls: 'medium' },
        { key: 'high_risk', label: 'High', cls: 'high' },
    ];

    classes.forEach(c => {
        const d = stats[c.key] || {};
        grid.innerHTML += `
            <div class="stat-card ${c.cls}">
                <div class="stat-label">${c.label} Risk</div>
                <div class="stat-value">${d.pct || 0}%</div>
                <div class="stat-sub">${d.area_km2 || 0} km²</div>
            </div>
        `;
    });

    // Road stats
    const roadDiv = document.getElementById('roadStats');
    if (result.road_stats) {
        const rs = result.road_stats;
        roadDiv.innerHTML = `
            <h3>Road Segments</h3>
            <div class="road-stat-row">
                <span><span class="dot" style="background:#66bb6a"></span>Safe</span>
                <span class="count">${rs.safe_segments}</span>
            </div>
            <div class="road-stat-row">
                <span><span class="dot" style="background:#ffa726"></span>Medium</span>
                <span class="count">${rs.medium_risk_segments}</span>
            </div>
            <div class="road-stat-row">
                <span><span class="dot" style="background:#e53935"></span>High</span>
                <span class="count">${rs.high_risk_segments}</span>
            </div>
            <div class="road-stat-row" style="margin-top:4px;border-top:1px solid rgba(255,255,255,0.08);padding-top:6px">
                <span>Total</span>
                <span class="count">${rs.total_segments}</span>
            </div>
        `;
    } else {
        roadDiv.innerHTML = '';
    }

    // Escape destination info
    const shelterDiv = document.getElementById('shelterInfo');
    if (result.escape_destination) {
        const ed = result.escape_destination;
        shelterDiv.innerHTML = `
            🛡️ Escape to safe zone
            <span class="shelter-name">(FSI=${(ed.fsi || 0).toFixed(3)})</span>
        `;
    } else if (result.evacuation_route) {
        shelterDiv.innerHTML = '✅ Already in safe zone';
    } else {
        shelterDiv.innerHTML = '⚠️ No escape route found';
    }

    document.getElementById('resultsPanel').classList.remove('hidden');
}


// ── Progress UI ────────────────────────────────────────────────────────────
function showProgress(text) {
    const panel = document.getElementById('progressPanel');
    panel.classList.remove('hidden');
    document.getElementById('progressText').textContent = text;
    document.getElementById('progressBar').style.width = '30%';
    document.getElementById('resultsPanel').classList.add('hidden');
}

function updateProgressText(text) {
    document.getElementById('progressText').textContent = text;
    // Advance progress bar
    const bar = document.getElementById('progressBar');
    const current = parseFloat(bar.style.width) || 0;
    bar.style.width = Math.min(current + 8, 90) + '%';
}

function hideProgress() {
    document.getElementById('progressBar').style.width = '100%';
    setTimeout(() => {
        document.getElementById('progressPanel').classList.add('hidden');
    }, 500);
}

function showError(msg) {
    const btn = document.getElementById('analyzeBtn');
    btn.classList.remove('running');
    btn.querySelector('.btn-text').textContent = 'Analyse';
    btn.querySelector('.btn-icon').textContent = '⚡';

    document.getElementById('progressText').textContent = '❌ ' + msg;
    document.getElementById('progressBar').style.width = '100%';
    document.getElementById('progressBar').style.background = '#e53935';

    setTimeout(() => {
        document.getElementById('progressPanel').classList.add('hidden');
        document.getElementById('progressBar').style.background = '';
    }, 5000);
}


// ── Cleanup ────────────────────────────────────────────────────────────────
function clearResults() {
    if (riskOverlay) { map.removeLayer(riskOverlay); riskOverlay = null; }
    if (roadsLayer) { map.removeLayer(roadsLayer); roadsLayer = null; }
    if (evacLayer) { map.removeLayer(evacLayer); evacLayer = null; }
    if (escapeMarker) { map.removeLayer(escapeMarker); escapeMarker = null; }
    if (buildingsLayer) { map.removeLayer(buildingsLayer); buildingsLayer = null; }

    document.getElementById('resultsPanel').classList.add('hidden');
    document.getElementById('statsGrid').innerHTML = '';
    document.getElementById('roadStats').innerHTML = '';
    document.getElementById('shelterInfo').innerHTML = '';
    document.getElementById('impactStats').innerHTML = '';

    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
}
