"""
Dithering algorithms for Perler bead pattern conversion.

Implements Floyd-Steinberg error diffusion and Bayer ordered dithering,
with strength control for blending between dithered and direct matching.
"""

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from color_science import rgb_to_lab, ciede2000


def _find_closest(pixel_lab: np.ndarray, palette_lab: np.ndarray) -> tuple[int, np.ndarray]:
    """Find closest palette color for a single pixel.

    Returns: (index, lab_of_match)
    """
    diffs = palette_lab - pixel_lab  # (M, 3)
    # Use quick Euclidean in Lab as approximation for single-pixel lookup
    # (full CIEDE2000 for single pixel is slow in Python loop)
    dists = np.sum(diffs**2, axis=1)
    idx = np.argmin(dists)
    return idx, palette_lab[idx]


def floyd_steinberg(
    pixels_rgb: np.ndarray,
    palette_lab: np.ndarray,
    palette_rgb: np.ndarray,
    strength: float = 1.0,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Floyd-Steinberg error diffusion dithering.

    Args:
        pixels_rgb: (H, W, 3) uint8 RGB array
        palette_lab: (M, 3) CIELAB values of palette colors
        palette_rgb: (M, 3) uint8 RGB values of palette colors
        strength: 0.0 (no dithering) to 1.0 (full dithering)
        alpha: (H, W) bool mask, True = opaque. None = all opaque.

    Returns:
        grid: (H, W) int array of palette indices. -1 = empty (transparent).
    """
    h, w, _ = pixels_rgb.shape
    # Work in float Lab space for error diffusion
    lab_image = rgb_to_lab(pixels_rgb.reshape(-1, 3)).reshape(h, w, 3).copy()
    grid = np.full((h, w), -1, dtype=np.int32)

    for y in range(h):
        for x in range(w):
            if alpha is not None and not alpha[y, x]:
                continue

            current_lab = lab_image[y, x]
            idx, matched_lab = _find_closest(current_lab, palette_lab)
            grid[y, x] = idx

            # Compute error
            error = (current_lab - matched_lab) * strength

            # Diffuse error to neighbors
            if x + 1 < w:
                lab_image[y, x + 1] += error * 7.0 / 16.0
            if y + 1 < h:
                if x - 1 >= 0:
                    lab_image[y + 1, x - 1] += error * 3.0 / 16.0
                lab_image[y + 1, x] += error * 5.0 / 16.0
                if x + 1 < w:
                    lab_image[y + 1, x + 1] += error * 1.0 / 16.0

    return grid


def _generate_bayer_matrix(n: int) -> np.ndarray:
    """Generate n x n Bayer threshold matrix (n must be power of 2)."""
    if n == 2:
        return np.array([[0, 2], [3, 1]], dtype=np.float64)

    half = n // 2
    smaller = _generate_bayer_matrix(half)
    m = np.zeros((n, n), dtype=np.float64)
    m[:half, :half] = 4 * smaller
    m[:half, half:] = 4 * smaller + 2
    m[half:, :half] = 4 * smaller + 3
    m[half:, half:] = 4 * smaller + 1
    return m


def bayer_ordered(
    pixels_rgb: np.ndarray,
    palette_lab: np.ndarray,
    palette_rgb: np.ndarray,
    strength: float = 1.0,
    matrix_size: int = 8,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Bayer ordered dithering.

    Args:
        pixels_rgb: (H, W, 3) uint8 RGB array
        palette_lab: (M, 3) CIELAB values of palette colors
        palette_rgb: (M, 3) uint8 RGB values of palette colors
        strength: 0.0 to 1.0
        matrix_size: Bayer matrix size (must be power of 2, default 8)
        alpha: (H, W) bool mask. None = all opaque.

    Returns:
        grid: (H, W) int array of palette indices. -1 = empty.
    """
    h, w, _ = pixels_rgb.shape

    # Generate and normalize Bayer matrix to [-0.5, 0.5]
    bayer = _generate_bayer_matrix(matrix_size)
    bayer = bayer / (matrix_size * matrix_size) - 0.5

    # Tile to cover image
    tiled = np.tile(bayer, (h // matrix_size + 1, w // matrix_size + 1))[:h, :w]

    # Convert to Lab
    lab_image = rgb_to_lab(pixels_rgb.reshape(-1, 3)).reshape(h, w, 3).copy()

    # Apply threshold offset to L* channel (lightness)
    max_adjust = 30.0 * strength  # Max L* adjustment
    lab_image[:, :, 0] += tiled * max_adjust

    # Clamp L* to valid range
    lab_image[:, :, 0] = np.clip(lab_image[:, :, 0], 0, 100)

    # Vectorized matching using CIEDE2000
    flat_lab = lab_image.reshape(-1, 3)

    # For performance: use Euclidean distance in Lab space for Bayer
    # (vectorized, much faster than pixel-by-pixel CIEDE2000)
    diffs = flat_lab[:, np.newaxis, :] - palette_lab[np.newaxis, :, :]  # (N, M, 3)
    dists = np.sum(diffs**2, axis=2)  # (N, M)
    indices = np.argmin(dists, axis=1)  # (N,)

    grid = indices.reshape(h, w).astype(np.int32)

    # Apply alpha mask
    if alpha is not None:
        grid[~alpha] = -1

    return grid


def apply_dithering(
    pixels_rgb: np.ndarray,
    palette: dict,
    algorithm: str = "floyd",
    strength: float = 1.0,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Apply dithering to pixel grid.

    Args:
        pixels_rgb: (H, W, 3) uint8
        palette: dict with 'lab' and 'rgb_array' keys
        algorithm: 'floyd' or 'bayer'
        strength: 0.0 to 1.0 (0 = no dithering)
        alpha: optional (H, W) bool mask

    Returns:
        grid: (H, W) int array of palette indices
    """
    palette_lab = palette["lab"]
    palette_rgb = palette["rgb_array"]

    if algorithm == "floyd":
        return floyd_steinberg(pixels_rgb, palette_lab, palette_rgb, strength, alpha)
    elif algorithm == "bayer":
        return bayer_ordered(pixels_rgb, palette_lab, palette_rgb, strength, alpha=alpha)
    else:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Use 'floyd' or 'bayer'.")


if __name__ == "__main__":
    print("Dithering module. Import and use apply_dithering().")
    print("Algorithms: floyd (Floyd-Steinberg), bayer (Ordered Dithering)")
