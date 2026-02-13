"""
Road Network Module – Load OSM roads, overlay flood risk, detect safe zones.

Graph is built once per AOI and cached.  Risk sampling uses multiprocessing
for performance on multi-core machines (Apple M4, etc.).
"""

import os
import math
import osmnx as ox
import networkx as nx
import numpy as np
import rasterio
from concurrent.futures import ProcessPoolExecutor, as_completed

import config

# ── Module-level cache ──────────────────────────────────────────────────────
_cached_graph = None
_cached_key = None       # (lat, lon, radius_m)


def load_road_network(
    lat: float, lon: float, radius_m: float, force: bool = False
) -> nx.MultiDiGraph:
    """
    Download drivable road graph from OSM.  Cached by (lat, lon, radius_m)
    so repeated calls with the same AOI return instantly.

    Retries up to 3 times on transient Overpass API failures.
    """
    import time

    global _cached_graph, _cached_key
    key = (round(lat, 4), round(lon, 4), int(radius_m))

    if not force and _cached_key == key and _cached_graph is not None:
        print(f"[ROAD] Using cached graph ({_cached_graph.number_of_nodes()} nodes)")
        return _cached_graph

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            G = ox.graph_from_point(
                (lat, lon),
                dist=radius_m,
                network_type="drive",
                simplify=True,
            )
            print(f"[ROAD] Loaded {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
            _cached_graph = G
            _cached_key = key
            return G
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"[ROAD] Attempt {attempt}/{max_retries} failed: {e}")
                print(f"[ROAD] Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[ROAD] All {max_retries} attempts failed")
                raise


# ── Parallel risk sampling ──────────────────────────────────────────────────

def _sample_chunk(args):
    """Worker function: sample risk values for a chunk of edges."""
    risk_tif_path, edge_midpoints = args
    results = {}
    with rasterio.open(risk_tif_path) as src:
        transform = src.transform
        band = src.read(1)
        rows, cols = band.shape

        for edge_key, (mid_lon, mid_lat) in edge_midpoints.items():
            col_idx, row_idx = ~transform * (mid_lon, mid_lat)
            row_idx, col_idx = int(round(row_idx)), int(round(col_idx))
            if 0 <= row_idx < rows and 0 <= col_idx < cols:
                results[edge_key] = float(band[row_idx, col_idx])
            else:
                results[edge_key] = 0.0
    return results


def sample_risk_on_edges(
    G: nx.MultiDiGraph,
    risk_tif_path: str,
    n_workers: int = None,
) -> nx.MultiDiGraph:
    """
    Sample flood risk at each edge midpoint.  Uses multiprocessing
    to parallelise I/O across CPU cores.
    """
    if n_workers is None:
        n_workers = min(os.cpu_count() or 4, 8)

    # Collect all edge midpoints
    edge_midpoints = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        u_d, v_d = G.nodes[u], G.nodes[v]
        mid_lon = (u_d["x"] + v_d["x"]) / 2
        mid_lat = (u_d["y"] + v_d["y"]) / 2
        edge_midpoints[(u, v, k)] = (mid_lon, mid_lat)

    total = len(edge_midpoints)

    # For small graphs, just do it in-process (avoid IPC overhead)
    if total < 500 or n_workers <= 1:
        results = _sample_chunk((risk_tif_path, edge_midpoints))
        for (u, v, k), risk in results.items():
            G.edges[u, v, k]["flood_risk"] = risk
        print(f"[ROAD] Flood risk sampled on {total} edges (single-thread)")
        return G

    # Split into chunks for parallel workers
    keys = list(edge_midpoints.keys())
    chunk_size = math.ceil(total / n_workers)
    chunks = []
    for i in range(0, total, chunk_size):
        chunk_keys = keys[i : i + chunk_size]
        chunk_dict = {k: edge_midpoints[k] for k in chunk_keys}
        chunks.append((risk_tif_path, chunk_dict))

    # Execute in parallel
    all_results = {}
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_sample_chunk, c) for c in chunks]
        for f in as_completed(futures):
            all_results.update(f.result())

    for (u, v, k), risk in all_results.items():
        G.edges[u, v, k]["flood_risk"] = risk

    print(f"[ROAD] Flood risk sampled on {total} edges ({n_workers} workers)")
    return G


# ── Edge penalisation ───────────────────────────────────────────────────────

def penalize_flooded_edges(
    G: nx.MultiDiGraph,
    penalty_factor: float = config.FLOOD_RISK_PENALTY_FACTOR,
    remove_threshold: float = config.HIGH_RISK_ROAD_THRESHOLD,
) -> nx.MultiDiGraph:
    """
    - Remove edges with flood_risk >= remove_threshold (impassable).
    - Scale remaining risky edges: length *= (1 + risk * penalty_factor).
    """
    edges_to_remove = []
    for u, v, k, data in G.edges(keys=True, data=True):
        risk = data.get("flood_risk", 0.0)
        if risk >= remove_threshold:
            edges_to_remove.append((u, v, k))
        elif risk > 0:
            data["length"] = data.get("length", 1) * (1 + risk * penalty_factor)

    G.remove_edges_from(edges_to_remove)
    print(
        f"[ROAD] Removed {len(edges_to_remove)} impassable edges; "
        f"penalised remaining risky edges (x{penalty_factor})"
    )
    return G


# ── Safe-zone detection ─────────────────────────────────────────────────────

def label_safe_nodes(
    G: nx.MultiDiGraph,
    risk_tif_path: str,
    safe_threshold: float = 0.3,
) -> nx.MultiDiGraph:
    """
    Tag each node with is_safe=True if the FSI at its location < safe_threshold.
    These are candidate escape destinations.
    """
    with rasterio.open(risk_tif_path) as src:
        transform = src.transform
        band = src.read(1)
        rows, cols = band.shape

    n_safe = 0
    for node, data in G.nodes(data=True):
        col_idx, row_idx = ~transform * (data["x"], data["y"])
        row_idx, col_idx = int(round(row_idx)), int(round(col_idx))
        if 0 <= row_idx < rows and 0 <= col_idx < cols:
            fsi = float(band[row_idx, col_idx])
        else:
            fsi = 0.0
        data["fsi"] = fsi
        data["is_safe"] = fsi < safe_threshold
        if data["is_safe"]:
            n_safe += 1

    print(f"[ROAD] Safe-zone nodes: {n_safe}/{G.number_of_nodes()} (FSI < {safe_threshold})")
    return G
