"""
AHP Module – Analytic Hierarchy Process for MCDA weight derivation.

5-factor base susceptibility (rainfall is applied as a multiplier, not a factor).

References:
    Saaty, T.L. (1980). The Analytic Hierarchy Process.
"""

import numpy as np


# Random Index table for matrices of size 1..10 (Saaty, 1980)
RI_TABLE = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12,
            6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


# ── Pairwise comparison matrix (Saaty scale) ────────────────────────────
# Factors: Elevation, Slope, Soil, River, FlowAccum
# Rainfall is NOT a spatial factor — it scales the final risk.
#
# Physical reasoning:
#   River proximity is the strongest flood predictor
#   Elevation is strongly important (low-lying = water collects)
#   Flow accumulation captures drainage convergence
#   Slope is moderate (flat = slower drainage)
#   Soil is moderate (clay resists infiltration)

FACTOR_NAMES = ["elevation", "slope", "soil", "river", "flow_accum"]

PAIRWISE_MATRIX = np.array([
    #  Elev  Slope  Soil   River  Flow
    [  1,    3,     3,     1/2,   1    ],   # Elevation
    [  1/3,  1,     1,     1/4,   1/2  ],   # Slope
    [  1/3,  1,     1,     1/4,   1/2  ],   # Soil
    [  2,    4,     4,     1,     2    ],   # River
    [  1,    2,     2,     1/2,   1    ],   # Flow Accum
], dtype=np.float64)


def compute_ahp_weights(matrix: np.ndarray = None, names: list = None):
    """
    Compute AHP priority weights from a pairwise comparison matrix.

    Returns:
        weights: dict {factor_name: weight}
        ci: Consistency Index
        cr: Consistency Ratio
        is_consistent: bool (CR < 0.1)
    """
    if matrix is None:
        matrix = PAIRWISE_MATRIX.copy()
    if names is None:
        names = FACTOR_NAMES

    n = matrix.shape[0]
    assert matrix.shape == (n, n), "Matrix must be square"

    # ── Step 1: Normalise columns ────────────────────────────────────────
    col_sums = matrix.sum(axis=0)
    normalised = matrix / col_sums

    # ── Step 2: Compute priority vector (row averages) ───────────────────
    priority = normalised.mean(axis=1)

    # ── Step 3: Consistency check ────────────────────────────────────────
    weighted = matrix @ priority
    lambda_ratios = weighted / priority
    lambda_max = lambda_ratios.mean()

    ci = (lambda_max - n) / (n - 1)

    ri = RI_TABLE.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0

    is_consistent = cr < 0.1

    # Build weights dict
    weights = {name: round(float(w), 4) for name, w in zip(names, priority)}

    # Print summary
    print(f"[AHP] Pairwise matrix ({n}×{n}) – 5 spatial factors")
    for name, w in weights.items():
        print(f"       {name:15s} = {w:.4f}")
    print(f"       λ_max = {lambda_max:.4f}")
    print(f"       CI    = {ci:.4f}")
    print(f"       CR    = {cr:.4f}  {'✅ Consistent' if is_consistent else '❌ INCONSISTENT'}")

    return weights, ci, cr, is_consistent


def get_validated_weights():
    """
    Compute and validate AHP weights.
    Raises ValueError if the matrix is inconsistent (CR >= 0.1).
    """
    weights, ci, cr, ok = compute_ahp_weights()
    if not ok:
        raise ValueError(
            f"AHP pairwise matrix is inconsistent (CR={cr:.4f} >= 0.1). "
            "Adjust the comparison matrix."
        )
    # Ensure weights sum to 1.0 (correct any rounding)
    total = sum(weights.values())
    weights = {k: round(v / total, 4) for k, v in weights.items()}
    return weights


# ── Quick self-test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    w = get_validated_weights()
    print(f"\nFinal weights: {w}")
    print(f"Sum: {sum(w.values()):.4f}")
