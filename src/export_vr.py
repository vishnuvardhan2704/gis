"""
export_vr.py – Generate GLB (glTF-Binary) 3D terrain model for VR viewing.

Reads DEM + FSI GeoTIFFs, builds a textured mesh with vertex colors,
and exports as .glb for use with <model-viewer> / WebXR.

Key design: the mesh is built LARGE (100 m across) with strong vertical
exaggeration so model-viewer renders it as an immersive landscape you
look ACROSS, not a tiny object you look AT.
"""

import os
import numpy as np
import rasterio
from scipy.ndimage import zoom
import trimesh


def _fsi_color(fsi: float) -> list:
    """
    Return [R, G, B, A] (0-255) for a given FSI value using the
    professional green-yellow-red color ramp matching terrain3d.js.
    """
    t = max(0.0, min(1.0, fsi))

    if t < 0.33:
        s = t / 0.33
        r = 34 + s * 90
        g = 139 + s * 40
        b = 34 + s * 32
    elif t < 0.66:
        s = (t - 0.33) / 0.33
        r = 124 + s * 131
        g = 179 + s * 36
        b = 66 - s * 66
    else:
        s = (t - 0.66) / 0.34
        r = 255 - s * 77
        g = 215 - s * 181
        b = s * 34

    return [int(r), int(g), int(b), 255]


def build_terrain_glb(
    dem_tif_path: str,
    fsi_tif_path: str,
    output_path: str,
    grid_size: int = 256,
    terrain_size: float = 100.0,
) -> str:
    """
    Build a GLB terrain model from DEM + FSI GeoTIFFs.

    The mesh is 100 m across with aggressive vertical exaggeration
    so it looks like a real landscape in model-viewer / VR, not a
    flat thumbnail.
    """
    # ── Read rasters ────────────────────────────────────────────────────
    with rasterio.open(dem_tif_path) as src:
        dem_raw = src.read(1)
        bounds = src.bounds

    with rasterio.open(fsi_tif_path) as src:
        fsi_raw = src.read(1)

    # ── Resample to grid_size ───────────────────────────────────────────
    dem = zoom(dem_raw, (grid_size / dem_raw.shape[0], grid_size / dem_raw.shape[1]), order=3)
    fsi = zoom(fsi_raw, (grid_size / fsi_raw.shape[0], grid_size / fsi_raw.shape[1]), order=1)

    dem = np.nan_to_num(dem, nan=0.0)
    fsi = np.nan_to_num(fsi, nan=0.0)

    rows, cols = dem.shape

    # ── Elevation scaling ───────────────────────────────────────────────
    valid_mask = dem > 0
    dem_min = float(np.min(dem[valid_mask])) if np.any(valid_mask) else float(np.min(dem))
    dem_max = float(np.max(dem))
    dem_mean = float(np.mean(dem[valid_mask])) if np.any(valid_mask) else float(np.mean(dem))

    elev_range = dem_max - dem_min
    cell = terrain_size / max(rows, cols)  # spacing between vertices

    # Vertical exaggeration: we want relief to be clearly visible.
    # Target: the peak-to-valley height should be ~15-25% of terrain width.
    # With terrain_size=100 that means ~15-25 m of visual relief.
    target_relief = terrain_size * 0.20  # 20% of width
    if elev_range > 0:
        v_scale = target_relief / elev_range
    else:
        v_scale = 1.0

    print(f"[VR] DEM range: {dem_min:.0f}–{dem_max:.0f} m ({elev_range:.0f} m)")
    print(f"[VR] Terrain: {terrain_size}m, cell: {cell:.4f}m, V.exag: {v_scale:.3f}x")

    # ── Build vertex arrays (vectorized for speed) ──────────────────────
    r_idx, c_idx = np.meshgrid(np.arange(rows), np.arange(cols), indexing='ij')

    x = (c_idx - cols / 2.0) * cell
    z = (r_idx - rows / 2.0) * cell
    y = (dem - dem_mean) * v_scale

    vertices = np.stack([x, y, z], axis=-1).reshape(-1, 3).astype(np.float64)

    # Colors from FSI
    fsi_flat = fsi.ravel()
    colors = np.array([_fsi_color(float(v)) for v in fsi_flat], dtype=np.uint8)

    # ── Build face indices (two triangles per quad) ─────────────────────
    r_face, c_face = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing='ij')
    i = (r_face * cols + c_face).ravel()

    faces = np.column_stack([
        np.column_stack([i, i + cols, i + 1]),
        np.column_stack([i + 1, i + cols, i + cols + 1]),
    ]).reshape(-1, 3).astype(np.int64)

    # ── Create trimesh ──────────────────────────────────────────────────
    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        vertex_colors=colors,
        process=False,
    )

    # Center at origin
    mesh.vertices -= mesh.bounding_box.centroid
    mesh.fix_normals()

    # ── Export GLB ──────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    mesh.export(output_path, file_type="glb")

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    bbox = mesh.bounding_box.extents
    print(f"[VR] GLB exported: {output_path} ({file_size_mb:.1f} MB)")
    print(f"[VR] Bounding box: {bbox[0]:.1f} x {bbox[1]:.1f} x {bbox[2]:.1f} m")

    return os.path.abspath(output_path)
