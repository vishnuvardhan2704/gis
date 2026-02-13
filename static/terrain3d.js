/**
 * terrain3d.js – Professional 3D Terrain Visualization
 * 
 * Renders realistic topographic model with DEM geometry and FSI color draping.
 * Aesthetic: ArcGIS Pro / QGIS 3D View style (scientific, not cartoon)
 */

// ── Global State ────────────────────────────────────────────────────────────
let scene, camera, renderer, controls;
let terrainMesh = null;
let isRendering = false;
let currentData = null;

// ── Professional GIS Color Scheme ───────────────────────────────────────────

/**
 * Professional FSI color ramp (inspired by Esri's Green-Yellow-Red scheme)
 * Smooth gradients, muted tones, suitable for scientific presentation
 */
function getFSIColor(fsi) {
    // Clamp FSI to [0, 1]
    const t = Math.max(0, Math.min(1, fsi));
    
    let r, g, b;
    
    if (t < 0.33) {
        // Low risk: Forest green (34,139,34) → Lime green (124,179,66)
        const s = t / 0.33;
        r = 34 + s * 90;
        g = 139 + s * 40;
        b = 34 + s * 32;
    } else if (t < 0.66) {
        // Medium risk: Lime green → Gold (255,215,0)
        const s = (t - 0.33) / 0.33;
        r = 124 + s * 131;
        g = 179 + s * 36;
        b = 66 - s * 66;
    } else {
        // High risk: Gold → Fire brick (178,34,34)
        const s = (t - 0.66) / 0.34;
        r = 255 - s * 77;
        g = 215 - s * 181;
        b = s * 34;
    }
    
    return {
        r: r / 255,
        g: g / 255,
        b: b / 255
    };
}

/**
 * Bilinear interpolation from lower-res FSI grid to high-res DEM vertices
 */
function sampleFSI(row, col, demRows, demCols, fsiGrid, fsiRows, fsiCols) {
    // Map DEM coordinates to FSI grid coordinates
    const fsiRow = (row / (demRows - 1)) * (fsiRows - 1);
    const fsiCol = (col / (demCols - 1)) * (fsiCols - 1);
    
    const r0 = Math.floor(fsiRow);
    const r1 = Math.min(r0 + 1, fsiRows - 1);
    const c0 = Math.floor(fsiCol);
    const c1 = Math.min(c0 + 1, fsiCols - 1);
    
    const dr = fsiRow - r0;
    const dc = fsiCol - c0;
    
    // Bilinear interpolation
    const v00 = fsiGrid[r0][c0];
    const v01 = fsiGrid[r0][c1];
    const v10 = fsiGrid[r1][c0];
    const v11 = fsiGrid[r1][c1];
    
    const v0 = v00 * (1 - dc) + v01 * dc;
    const v1 = v10 * (1 - dc) + v11 * dc;
    
    return v0 * (1 - dr) + v1 * dr;
}

/**
 * Compute hillshade factor for realistic terrain shading
 * Simulates sun at azimuth 315° (northwest), altitude 45°
 */
function computeHillshade(demGrid, row, col, rows, cols, cellSize) {
    // Get neighboring elevations (handling edges)
    const getZ = (r, c) => {
        r = Math.max(0, Math.min(rows - 1, r));
        c = Math.max(0, Math.min(cols - 1, c));
        return demGrid[r][c];
    };
    
    const z = getZ(row, col);
    const zLeft = getZ(row, col - 1);
    const zRight = getZ(row, col + 1);
    const zUp = getZ(row - 1, col);
    const zDown = getZ(row + 1, col);
    
    // Compute slope and aspect
    const dzdx = (zRight - zLeft) / (2 * cellSize);
    const dzdy = (zDown - zUp) / (2 * cellSize);
    
    const slope = Math.atan(Math.sqrt(dzdx * dzdx + dzdy * dzdy));
    const aspect = Math.atan2(-dzdy, dzdx);
    
    // Sun angles (azimuth 315° = -45° from north, altitude 45°)
    const azimuthRad = (315 - 90) * Math.PI / 180;  // Convert to math convention
    const altitudeRad = 45 * Math.PI / 180;
    
    // Hillshade formula
    const hillshade = Math.cos(altitudeRad) * Math.sin(slope) * Math.cos(azimuthRad - aspect)
                    + Math.sin(altitudeRad) * Math.cos(slope);
    
    return Math.max(0, Math.min(1, hillshade));
}

// ── 3D Scene Initialization ─────────────────────────────────────────────────

function init3DScene() {
    const container = document.getElementById('view3d');
    if (!container) {
        console.error('[3D] Container #view3d not found');
        return;
    }
    
    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f1117);  // Dark theme background
    scene.fog = new THREE.Fog(0x0f1117, 80, 250);
    
    // Camera (oblique view - classic GIS 3D perspective)
    const aspect = container.clientWidth / container.clientHeight;
    camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 500);
    camera.position.set(60, 40, 80);
    camera.lookAt(0, 0, 0);
    
    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    container.appendChild(renderer.domElement);
    
    // Orbit controls (smooth camera interaction)
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 20;
    controls.maxDistance = 200;
    controls.maxPolarAngle = Math.PI / 2 - 0.05;  // Prevent going underground
    controls.target.set(0, 0, 0);
    
    // Lighting (realistic outdoor illumination)
    
    // 1. Sun (directional light from northwest at 45°)
    const sunLight = new THREE.DirectionalLight(0xfff4e6, 1.3);
    sunLight.position.set(-80, 60, 80);
    sunLight.castShadow = true;
    sunLight.shadow.camera.left = -100;
    sunLight.shadow.camera.right = 100;
    sunLight.shadow.camera.top = 100;
    sunLight.shadow.camera.bottom = -100;
    sunLight.shadow.camera.near = 0.5;
    sunLight.shadow.camera.far = 300;
    sunLight.shadow.mapSize.width = 2048;
    sunLight.shadow.mapSize.height = 2048;
    sunLight.shadow.bias = -0.0001;
    scene.add(sunLight);
    
    // 2. Sky ambient (soft blue-gray fill light)
    const ambient = new THREE.AmbientLight(0xa0b0c0, 0.5);
    scene.add(ambient);
    
    // 3. Subtle hemisphere light (sky → ground gradient)
    const hemiLight = new THREE.HemisphereLight(0x87ceeb, 0x4a4a3a, 0.3);
    scene.add(hemiLight);
    
    // Grid helper (optional reference grid)
    const gridHelper = new THREE.GridHelper(120, 24, 0x404050, 0x202028);
    gridHelper.position.y = -0.5;
    scene.add(gridHelper);
    
    // Handle window resize
    window.addEventListener('resize', onWindowResize);
    
    console.log('[3D] Scene initialized');
}

function onWindowResize() {
    if (!camera || !renderer) return;
    const container = document.getElementById('view3d');
    if (!container) return;
    
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
}

// ── Terrain Construction ────────────────────────────────────────────────────

function buildTerrain(data) {
    console.log('[3D] Building terrain mesh...');
    
    const { dem, fsi, dem_rows, dem_cols, fsi_rows, fsi_cols, dem_min, dem_max, dem_mean, dem_std, bounds } = data;
    
    currentData = data;
    
    // Remove old terrain
    if (terrainMesh) {
        scene.remove(terrainMesh);
        terrainMesh.geometry.dispose();
        terrainMesh.material.dispose();
        terrainMesh = null;
    }
    
    const rows = dem_rows;
    const cols = dem_cols;
    
    // Physical size (scale to fit nicely in view)
    const terrainSize = 80;  // World units
    const cellSize = terrainSize / Math.max(rows, cols);
    
    // Vertical exaggeration (enhance relief for visibility)
    // Auto-scale based on terrain variation
    const elevRange = dem_max - dem_min;
    const verticalScale = elevRange > 0 ? Math.min(0.5, 30 / elevRange) : 1.0;
    
    console.log(`[3D] DEM: ${rows}×${cols}, Elevation: ${dem_min.toFixed(1)} - ${dem_max.toFixed(1)}m, V.Scale: ${verticalScale.toFixed(2)}x`);
    
    // Create high-resolution plane geometry
    const geometry = new THREE.PlaneGeometry(
        terrainSize,
        terrainSize,
        cols - 1,
        rows - 1
    );
    
    const position = geometry.attributes.position;
    const colors = new Float32Array(position.count * 3);
    
    // Apply elevations and colors
    for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
            const i = row * cols + col;
            
            // Set vertex Z from DEM (apply vertical exaggeration)
            const elevation = dem[row][col];
            const z = (elevation - dem_mean) * verticalScale;
            position.setZ(i, z);
            
            // Sample FSI for this vertex (bilinear interpolation)
            const fsiValue = sampleFSI(row, col, rows, cols, fsi, fsi_rows, fsi_cols);
            
            // Get base FSI color
            const fsiColor = getFSIColor(fsiValue);
            
            // Compute hillshade for realistic shading
            const hillshade = computeHillshade(dem, row, col, rows, cols, cellSize / verticalScale);
            
            // Blend FSI color with hillshade (darker in valleys, lighter on ridges)
            const hillshadeStrength = 0.35;  // How much hillshade affects color
            const shadeFactor = 1 - hillshadeStrength + hillshade * hillshadeStrength;
            
            colors[i * 3]     = fsiColor.r * shadeFactor;
            colors[i * 3 + 1] = fsiColor.g * shadeFactor;
            colors[i * 3 + 2] = fsiColor.b * shadeFactor;
        }
    }
    
    // Set vertex colors
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    
    // Compute smooth normals for realistic lighting
    geometry.computeVertexNormals();
    
    // Professional material (matte earth surface)
    const material = new THREE.MeshStandardMaterial({
        vertexColors: true,      // Use our computed colors
        roughness: 0.95,         // Very matte (not shiny)
        metalness: 0.0,          // No metallic reflection
        flatShading: false,      // Smooth shading
        side: THREE.DoubleSide,
        shadowSide: THREE.DoubleSide
    });
    
    terrainMesh = new THREE.Mesh(geometry, material);
    terrainMesh.rotation.x = -Math.PI / 2;  // Rotate to horizontal
    terrainMesh.receiveShadow = true;
    terrainMesh.castShadow = true;
    
    scene.add(terrainMesh);
    
    // Reset camera to good viewing angle
    camera.position.set(terrainSize * 0.75, terrainSize * 0.5, terrainSize);
    controls.target.set(0, 0, 0);
    controls.update();
    
    console.log('[3D] Terrain mesh built successfully');
}

// ── Animation Loop ──────────────────────────────────────────────────────────

function animate() {
    if (!isRendering) return;
    
    requestAnimationFrame(animate);
    
    if (controls) controls.update();
    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

// ── Public API ──────────────────────────────────────────────────────────────

function load3DTerrain(jobId) {
    console.log(`[3D] Loading terrain data for job ${jobId}...`);
    
    if (!scene) {
        init3DScene();
    }
    
    isRendering = true;
    animate();
    
    // Fetch high-resolution terrain data
    fetch(`/api/terrain3d/${jobId}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                console.error('[3D] Error:', data.error);
                return;
            }
            buildTerrain(data);
        })
        .catch(err => {
            console.error('[3D] Failed to load terrain:', err);
        });
}

function destroy3DScene() {
    console.log('[3D] Destroying scene...');
    
    isRendering = false;
    
    if (terrainMesh) {
        scene.remove(terrainMesh);
        terrainMesh.geometry.dispose();
        terrainMesh.material.dispose();
        terrainMesh = null;
    }
    
    if (renderer) {
        renderer.dispose();
        const container = document.getElementById('view3d');
        if (container && renderer.domElement.parentNode === container) {
            container.removeChild(renderer.domElement);
        }
    }
    
    scene = null;
    camera = null;
    renderer = null;
    controls = null;
    currentData = null;
}

// ── Camera Presets ──────────────────────────────────────────────────────────

function setCameraPreset(preset) {
    if (!camera || !controls) return;
    
    const distance = 100;
    
    switch (preset) {
        case 'perspective':
            camera.position.set(distance * 0.6, distance * 0.4, distance * 0.8);
            break;
        case 'oblique':
            camera.position.set(distance * 0.7, distance * 0.35, distance * 0.7);
            break;
        case 'top':
            camera.position.set(0, distance * 0.9, distance * 0.2);
            break;
    }
    
    controls.target.set(0, 0, 0);
    controls.update();
}

// ── Export functions ────────────────────────────────────────────────────────
// These are called from app.js

if (typeof window !== 'undefined') {
    window.load3DTerrain = load3DTerrain;
    window.destroy3DScene = destroy3DScene;
    window.setCameraPreset = setCameraPreset;
}
