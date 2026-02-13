"""
Decision Support Module – Risk statistics and situation-report generation.
"""

import os
import json
import numpy as np
import rasterio

import config


def compute_risk_statistics(risk_tif_path: str) -> dict:
    """
    Compute area percentages per risk class from the GeoTIFF.
    Returns dict with pixel counts and percentages.
    """
    with rasterio.open(risk_tif_path) as src:
        band = src.read(1)
        bounds = src.bounds
        # For EPSG:4326, pixel size is in degrees – convert to metres
        import math
        mid_lat = (bounds.bottom + bounds.top) / 2
        deg_to_m_lat = 111_320  # metres per degree latitude
        deg_to_m_lon = 111_320 * math.cos(math.radians(mid_lat))
        pixel_w_m = abs(src.transform.a) * deg_to_m_lon
        pixel_h_m = abs(src.transform.e) * deg_to_m_lat
        pixel_area_m2 = pixel_w_m * pixel_h_m

    valid = band[~np.isnan(band)]
    total = len(valid)
    if total == 0:
        return {"error": "No valid pixels"}

    t = config.RISK_THRESHOLDS
    low = np.sum(valid <= t["low_max"])
    medium = np.sum((valid > t["low_max"]) & (valid <= t["medium_max"]))
    high = np.sum(valid > t["medium_max"])

    def _class_stats(count):
        return {
            "pixels": int(count),
            "pct": round(count / total * 100, 1),
            "area_km2": round(count * pixel_area_m2 / 1e6, 2),
        }

    stats = {
        "total_pixels": int(total),
        "pixel_area_m2": float(pixel_area_m2),
        "total_area_km2": round(total * pixel_area_m2 / 1e6, 2),
        "low_risk": _class_stats(low),
        "medium_risk": _class_stats(medium),
        "high_risk": _class_stats(high),
        "mean_risk": round(float(np.nanmean(valid)), 4),
        "max_risk": round(float(np.nanmax(valid)), 4),
    }
    print(f"[DSS] Risk stats – Low: {stats['low_risk']['pct']}%, "
          f"Medium: {stats['medium_risk']['pct']}%, "
          f"High: {stats['high_risk']['pct']}%")
    return stats


def count_affected_roads(G) -> dict:
    """Count roads by risk category (3 classes)."""
    t = config.RISK_THRESHOLDS
    total = G.number_of_edges()
    high = sum(1 for _, _, d in G.edges(data=True)
               if d.get("flood_risk", 0) > t["medium_max"])
    medium = sum(1 for _, _, d in G.edges(data=True)
                 if t["low_max"] < d.get("flood_risk", 0) <= t["medium_max"])
    safe = total - high - medium
    return {
        "total_segments": total,
        "high_risk_segments": high,
        "medium_risk_segments": medium,
        "safe_segments": safe,
    }


def generate_report(
    risk_stats: dict,
    road_stats: dict = None,
    shelters: list[dict] = None,
    chosen_shelter: dict = None,
    evac_route_len: int = None,
    params: dict = None,
) -> dict:
    """
    Generate a structured analytical report (JSON) with a plain-text summary.
    """
    report = {
        "title": "Flood Susceptibility Situation Report",
        "parameters": params or {},
        "risk_statistics": risk_stats,
        "road_analysis": road_stats or {},
        "shelters_found": len(shelters) if shelters else 0,
        "chosen_shelter": chosen_shelter,
        "evacuation_route_nodes": evac_route_len,
    }

    # Plain-text summary
    total_area = risk_stats.get("total_area_km2", 0)

    def _fmt(key):
        return (risk_stats.get(key, {}).get('pct', 0),
                risk_stats.get(key, {}).get('area_km2', 0))

    lines = [
        "═══ SITUATION REPORT (AHP 6-Factor Model) ═══",
        "",
        f"Analysis area: {total_area} km²",
        f"Mean flood susceptibility index: {risk_stats.get('mean_risk', 'N/A')}",
        "",
        f"• Low risk:    {_fmt('low_risk')[0]}%  ({_fmt('low_risk')[1]} km²)",
        f"• Medium risk: {_fmt('medium_risk')[0]}%  ({_fmt('medium_risk')[1]} km²)",
        f"• High risk:   {_fmt('high_risk')[0]}%  ({_fmt('high_risk')[1]} km²)",
    ]

    if road_stats:
        lines += [
            "",
            f"Road segments: {road_stats['total_segments']}",
            f"  High-risk:   {road_stats['high_risk_segments']}",
            f"  Medium-risk: {road_stats['medium_risk_segments']}",
            f"  Safe:        {road_stats['safe_segments']}",
        ]

    if chosen_shelter:
        lines += [
            "",
            f"Recommended shelter: {chosen_shelter['name']} ({chosen_shelter['type']})",
            f"  Route length: {evac_route_len} waypoints",
        ]
    elif shelters is not None and len(shelters) == 0:
        lines.append("\n⚠  No shelters found in the area.")

    report["summary_text"] = "\n".join(lines)

    # Save JSON
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, config.REPORT_JSON)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[DSS] Report saved → {out_path}")

    # Print plain-text summary
    print()
    print(report["summary_text"])
    return report
