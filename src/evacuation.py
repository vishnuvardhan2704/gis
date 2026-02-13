"""
Evacuation Routing Module – Flood Escape Routing.

Instead of routing to shelters, this module finds the shortest path
from the origin to the nearest SAFE ZONE (where FSI < 0.3).

This is physically correct: escape the flood boundary, don't search
for a specific building.
"""

import math
import heapq
import osmnx as ox
import networkx as nx


def _haversine_m(lat1, lon1, lat2, lon2):
    """Haversine distance in metres."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def find_escape_route(
    G: nx.MultiDiGraph,
    start_lat: float,
    start_lon: float,
) -> tuple[list[tuple[float, float]] | None, dict | None]:
    """
    A* from origin to the NEAREST safe-zone node (is_safe=True).

    Uses flood-penalised edge lengths as weights and haversine heuristic
    toward the nearest safe node.

    Returns:
        (route, safe_node_info)
        route: list of (lat, lon) waypoints, or None
        safe_node_info: {lat, lon, fsi} of the escape destination
    """
    start_node = ox.nearest_nodes(G, start_lon, start_lat)

    # Check if origin is already safe
    if G.nodes[start_node].get("is_safe", False):
        nd = G.nodes[start_node]
        print(f"[EVAC] Origin is already in safe zone (FSI={nd.get('fsi', 0):.3f})")
        return [(nd["y"], nd["x"])], {"lat": nd["y"], "lon": nd["x"], "fsi": nd.get("fsi", 0)}

    # Collect all safe-zone nodes for heuristic
    safe_nodes = [
        n for n, d in G.nodes(data=True) if d.get("is_safe", False)
    ]

    if not safe_nodes:
        print("[EVAC] No safe-zone nodes found in graph")
        return None, None

    # Pre-compute safe node positions for fast heuristic
    safe_positions = [
        (G.nodes[n]["y"], G.nodes[n]["x"]) for n in safe_nodes
    ]
    safe_set = set(safe_nodes)

    def heuristic(node):
        """Minimum haversine distance to any safe node."""
        nd = G.nodes[node]
        ny, nx_ = nd["y"], nd["x"]
        return min(
            _haversine_m(ny, nx_, sy, sx)
            for sy, sx in safe_positions
        )

    # ── A* with early termination at any safe node ──────────────────────
    # Standard A* but goal test is: node in safe_set
    open_set = [(heuristic(start_node), 0, start_node)]  # (f, g, node)
    g_scores = {start_node: 0}
    came_from = {}
    visited = set()

    while open_set:
        f, g, current = heapq.heappop(open_set)

        if current in visited:
            continue
        visited.add(current)

        # Goal: reached a safe zone
        if current in safe_set:
            # Reconstruct path
            path = []
            node = current
            while node in came_from:
                path.append(node)
                node = came_from[node]
            path.append(start_node)
            path.reverse()

            route = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]
            dest = G.nodes[current]
            dest_info = {
                "lat": dest["y"],
                "lon": dest["x"],
                "fsi": dest.get("fsi", 0),
            }

            dist = g_scores[current]
            print(
                f"[EVAC] Escape route found – {len(path)} nodes, "
                f"~{dist:.0f}m to safe zone (FSI={dest.get('fsi', 0):.3f})"
            )
            return route, dest_info

        # Expand neighbours
        for _, neighbour, edge_data in G.edges(current, data=True):
            if neighbour in visited:
                continue
            tentative_g = g + edge_data.get("length", 1)
            if tentative_g < g_scores.get(neighbour, float("inf")):
                g_scores[neighbour] = tentative_g
                came_from[neighbour] = current
                f_score = tentative_g + heuristic(neighbour)
                heapq.heappush(open_set, (f_score, tentative_g, neighbour))

    print("[EVAC] No escape route found – all paths blocked")
    return None, None
