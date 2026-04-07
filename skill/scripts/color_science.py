"""
CIEDE2000 color matching engine for Perler bead pattern conversion.

Pure numpy implementation — no external color science libraries required.
Implements the full pipeline: sRGB -> linear RGB -> XYZ (D65) -> CIELAB -> CIEDE2000.

Reference: Sharma, Wu, Dalal (2005) "The CIEDE2000 Color-Difference Formula"
"""

import json
import sys
from pathlib import Path
import numpy as np


# --- Color Space Conversions ---

def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    """Convert sRGB [0,255] uint8 to linear RGB [0,1] float64."""
    c = srgb.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_xyz(linear: np.ndarray) -> np.ndarray:
    """Convert linear RGB to CIE XYZ using sRGB->XYZ D65 matrix.

    Input shape: (..., 3). Output shape: (..., 3).
    """
    # sRGB to XYZ (D65) matrix
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    return linear @ M.T


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    """Convert CIE XYZ to CIELAB with D65 white point.

    Input shape: (..., 3). Output shape: (..., 3) as [L*, a*, b*].
    """
    # D65 white point
    white = np.array([0.95047, 1.00000, 1.08883])
    scaled = xyz / white

    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    f = np.where(scaled > epsilon,
                 np.cbrt(scaled),
                 (kappa * scaled + 16.0) / 116.0)

    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 (..., 3) to CIELAB (..., 3)."""
    return xyz_to_lab(linear_to_xyz(srgb_to_linear(rgb)))


# --- CIEDE2000 ---

def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Compute CIEDE2000 color difference.

    lab1: (N, 3) or (3,)
    lab2: (M, 3) or (3,)

    Returns: (N, M) distance matrix if both are 2D,
             or (N,) if lab2 is 1D, or scalar if both 1D.
    """
    # Ensure 2D
    squeeze_1 = lab1.ndim == 1
    squeeze_2 = lab2.ndim == 1
    if squeeze_1:
        lab1 = lab1[np.newaxis, :]
    if squeeze_2:
        lab2 = lab2[np.newaxis, :]

    # Broadcast: (N, 1, 3) vs (1, M, 3) -> (N, M, 3)
    L1, a1, b1 = lab1[:, np.newaxis, 0], lab1[:, np.newaxis, 1], lab1[:, np.newaxis, 2]
    L2, a2, b2 = lab2[np.newaxis, :, 0], lab2[np.newaxis, :, 1], lab2[np.newaxis, :, 2]

    # Step 1: Calculate C'ab and h'ab
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    C_avg = (C1 + C2) / 2.0
    C_avg7 = C_avg**7
    G = 0.5 * (1.0 - np.sqrt(C_avg7 / (C_avg7 + 25.0**7)))

    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)

    C1p = np.sqrt(a1p**2 + b1**2)
    C2p = np.sqrt(a2p**2 + b2**2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    # Step 2: Calculate delta L', delta C', delta H'
    dLp = L2 - L1
    dCp = C2p - C1p

    # delta h'
    dhp = np.zeros_like(dCp)
    C1pC2p = C1p * C2p
    hdiff = h2p - h1p

    mask1 = C1pC2p == 0
    mask2 = (~mask1) & (np.abs(hdiff) <= 180.0)
    mask3 = (~mask1) & (~mask2) & (hdiff > 180.0)
    mask4 = (~mask1) & (~mask2) & (hdiff < -180.0)

    dhp[mask2] = hdiff[mask2]
    dhp[mask3] = (hdiff - 360.0)[mask3]
    dhp[mask4] = (hdiff + 360.0)[mask4]

    dHp = 2.0 * np.sqrt(C1pC2p) * np.sin(np.radians(dhp / 2.0))

    # Step 3: Calculate CIEDE2000
    Lp_avg = (L1 + L2) / 2.0
    Cp_avg = (C1p + C2p) / 2.0

    # h'avg — use the same abs_hdiff for consistency with dhp
    abs_hdiff = np.abs(hdiff)
    hp_sum = h1p + h2p
    hp_avg = np.zeros_like(h1p)
    mask_a = C1pC2p == 0
    mask_b = (~mask_a) & (abs_hdiff <= 180.0)
    mask_c = (~mask_a) & (~mask_b) & (hp_sum < 360.0)
    mask_d = (~mask_a) & (~mask_b) & (~mask_c)

    hp_avg[mask_a] = hp_sum[mask_a]
    hp_avg[mask_b] = (hp_sum / 2.0)[mask_b]
    hp_avg[mask_c] = ((hp_sum + 360.0) / 2.0)[mask_c]
    hp_avg[mask_d] = ((hp_sum - 360.0) / 2.0)[mask_d]

    T = (1.0
         - 0.17 * np.cos(np.radians(hp_avg - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hp_avg))
         + 0.32 * np.cos(np.radians(3.0 * hp_avg + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hp_avg - 63.0)))

    SL = 1.0 + 0.015 * (Lp_avg - 50.0)**2 / np.sqrt(20.0 + (Lp_avg - 50.0)**2)
    SC = 1.0 + 0.045 * Cp_avg
    SH = 1.0 + 0.015 * Cp_avg * T

    Cp_avg7 = Cp_avg**7
    RC = 2.0 * np.sqrt(Cp_avg7 / (Cp_avg7 + 25.0**7))
    d_theta = 30.0 * np.exp(-((hp_avg - 275.0) / 25.0)**2)
    RT = -np.sin(np.radians(2.0 * d_theta)) * RC

    dE = np.sqrt(
        (dLp / SL)**2
        + (dCp / SC)**2
        + (dHp / SH)**2
        + RT * (dCp / SC) * (dHp / SH)
    )

    if squeeze_1 and squeeze_2:
        return dE.item()
    if squeeze_2:
        return dE[:, 0]
    if squeeze_1:
        return dE[0, :]
    return dE


# --- Palette ---

def load_palette(name: str, palettes_dir: Path = None) -> dict:
    """Load a palette JSON file by name.

    Returns dict with keys: brand, series, colors (list of dicts with code, name, rgb),
    and precomputed 'lab' array (N, 3).
    """
    if palettes_dir is None:
        palettes_dir = Path(__file__).parent.parent / "data" / "palettes"

    path = palettes_dir / f"{name}.json"
    if not path.exists():
        available = [f.stem for f in palettes_dir.glob("*.json")]
        raise FileNotFoundError(
            f"Palette '{name}' not found. Available: {', '.join(available)}"
        )

    with open(path, "r", encoding="utf-8") as f:
        palette = json.load(f)

    # Precompute Lab values
    rgb_array = np.array([c["rgb"] for c in palette["colors"]], dtype=np.uint8)
    palette["lab"] = rgb_to_lab(rgb_array)
    palette["rgb_array"] = rgb_array
    return palette


def filter_palette(palette: dict, exclude: list = None, only: list = None,
                   skip_discontinued: bool = True) -> dict:
    """Filter palette colors by inclusion/exclusion lists.

    Returns a new palette dict with filtered colors and updated lab/rgb arrays.
    """
    colors = palette["colors"]
    mask = np.ones(len(colors), dtype=bool)

    if skip_discontinued:
        for i, c in enumerate(colors):
            if c.get("discontinued", False):
                mask[i] = False

    if only is not None:
        only_set = set(only)
        for i, c in enumerate(colors):
            if c["code"] not in only_set:
                mask[i] = False

    if exclude is not None:
        exclude_set = set(exclude)
        for i, c in enumerate(colors):
            if c["code"] in exclude_set:
                mask[i] = False

    filtered = {
        "brand": palette["brand"],
        "series": palette["series"],
        "colors": [c for c, m in zip(colors, mask) if m],
        "lab": palette["lab"][mask],
        "rgb_array": palette["rgb_array"][mask],
    }
    return filtered


def match_colors(pixels_lab: np.ndarray, palette: dict) -> np.ndarray:
    """Match each pixel to the closest palette color via CIEDE2000.

    pixels_lab: (N, 3) CIELAB values
    palette: dict with 'lab' key containing (M, 3) array

    Returns: (N,) int array of indices into palette['colors']
    """
    palette_lab = palette["lab"]
    # Compute distances: (N, M)
    distances = ciede2000(pixels_lab, palette_lab)
    return np.argmin(distances, axis=1)


# --- Self-test ---

def self_test():
    """Validate CIEDE2000 against Sharma (2005) reference pairs.

    These are the first 10 pairs from Table 1 of the paper.
    """
    # (L1, a1, b1, L2, a2, b2, expected_dE)
    test_pairs = [
        (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
        (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
        (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
        (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
        (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
        (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
        (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
        (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
        (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
        (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    ]

    print("CIEDE2000 Self-Test (Sharma 2005 reference values)")
    print("-" * 60)
    all_pass = True
    for i, (L1, a1, b1, L2, a2, b2, expected) in enumerate(test_pairs):
        lab1 = np.array([L1, a1, b1])
        lab2 = np.array([L2, a2, b2])
        result = ciede2000(lab1, lab2)
        diff = abs(result - expected)
        passed = diff < 0.0001
        status = "PASS" if passed else "FAIL"
        print(f"  Pair {i+1:2d}: expected={expected:.4f}  got={result:.4f}  diff={diff:.6f}  [{status}]")
        if not passed:
            all_pass = False

    print("-" * 60)
    if all_pass:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)

    # Also test vectorized matching
    print("\nVectorized matching test:")
    pixels = np.array([[50.0, 2.6772, -79.7751], [50.0, 0.0, 0.0]])
    palette_lab = np.array([[50.0, 0.0, -82.7485], [50.0, -1.0, 2.0], [50.0, 0.0, 0.0]])
    distances = ciede2000(pixels, palette_lab)
    matches = np.argmin(distances, axis=1)
    print(f"  Pixel 0 -> palette index {matches[0]} (expected 0)")
    print(f"  Pixel 1 -> palette index {matches[1]} (expected 2)")
    assert matches[0] == 0 and matches[1] == 2, "Vectorized matching failed"
    print("  PASSED")


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    elif "--match" in sys.argv:
        # Quick single-color match: python color_science.py --match 255,200,100 artkal_h
        idx = sys.argv.index("--match")
        rgb_str = sys.argv[idx + 1]
        palette_name = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else "artkal_h"
        r, g, b = [int(x) for x in rgb_str.split(",")]
        pixel_lab = rgb_to_lab(np.array([[r, g, b]], dtype=np.uint8))
        palette = load_palette(palette_name)
        distances = ciede2000(pixel_lab, palette["lab"])
        best_idx = np.argmin(distances[0])
        best = palette["colors"][best_idx]
        print(f"Input: RGB({r},{g},{b})")
        print(f"Best match: {best['code']} ({best['name']}) RGB{tuple(best['rgb'])} dE={distances[0, best_idx]:.2f}")
    else:
        print("Usage:")
        print("  python color_science.py --test              Run self-tests")
        print("  python color_science.py --match R,G,B [palette]  Find closest color")
