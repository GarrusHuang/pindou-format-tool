#!/usr/bin/env python3
"""
Pindou: Image to Perler bead pattern converter.

Main CLI entry point that orchestrates the full conversion pipeline:
  Load image → Preprocess → Pixelate → Color match → Render → Export
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

# Add scripts dir to path for local imports
sys.path.insert(0, str(Path(__file__).parent))
from color_science import rgb_to_lab, match_colors, load_palette, filter_palette


def load_image(path: str) -> Image.Image:
    """Load and validate image file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    supported = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    if p.suffix.lower() not in supported:
        raise ValueError(f"Unsupported format '{p.suffix}'. Supported: {', '.join(supported)}")

    img = Image.open(path)
    return img


def preprocess(img: Image.Image, max_size: int = 4096) -> tuple[np.ndarray, np.ndarray | None]:
    """Preprocess image: resize if too large, extract alpha channel.

    Returns:
        rgb_array: (H, W, 3) uint8 RGB array
        alpha_mask: (H, W) bool array where True = opaque, None if no alpha
    """
    # Auto-downscale if too large
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Handle transparency
    alpha_mask = None
    if img.mode == "RGBA":
        arr = np.array(img)
        alpha_mask = arr[:, :, 3] > 30  # Low threshold to keep semi-transparent outline pixels
        rgb_array = arr[:, :, :3]
    elif img.mode == "LA" or img.mode == "PA":
        img = img.convert("RGBA")
        arr = np.array(img)
        alpha_mask = arr[:, :, 3] > 30
        rgb_array = arr[:, :, :3]
    else:
        img = img.convert("RGB")
        rgb_array = np.array(img)

    return rgb_array, alpha_mask


def quantize_colors(rgb_array: np.ndarray, alpha_mask: np.ndarray | None,
                     palette: dict, max_colors: int = 0,
                     edge_threshold: int = 200) -> np.ndarray:
    """Color quantization: reduce image to N clean palette colors BEFORE pixelation.

    This is the key to clean bead art. Instead of matching 200 colors per-pixel,
    we first decide "what are the main colors in this image?" and map each to
    the best bead color. The result is a clean image with only N bead colors.

    Steps:
    1. Separate edge pixels (dark outlines) from fill pixels
    2. Quantize fill pixels to N dominant colors (PIL median cut)
    3. Match each dominant color to best palette color via CIEDE2000
    4. Replace all fill pixels with their matched palette RGB
    5. Replace edge pixels with palette's darkest color (black)

    Returns: rgb_array with only palette colors, same shape as input.
    """
    h, w = rgb_array.shape[:2]

    # Edge detection using Sobel gradient — finds actual color boundaries.
    from PIL import ImageFilter
    gray = Image.fromarray(rgb_array).convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.array(edges).astype(np.float64)
    is_edge = edge_arr > (255 - edge_threshold)

    # ALSO detect near-black pixels as edges (actual drawn outlines)
    r, g, b = rgb_array[:, :, 0], rgb_array[:, :, 1], rgb_array[:, :, 2]
    max_ch = np.maximum(np.maximum(r, g), b).astype(np.float64)
    is_dark = max_ch < 60  # actual black/near-black drawn lines
    is_edge = is_edge | is_dark

    # Dilate edge mask by 2 pixels — ensures thin lines survive downscaling
    from scipy.ndimage import binary_dilation
    is_edge = binary_dilation(is_edge, iterations=2)

    # Also mask transparent pixels
    valid_mask = np.ones((h, w), dtype=bool)
    if alpha_mask is not None:
        valid_mask = alpha_mask

    fill_mask = valid_mask & ~is_edge

    # Auto-detect max_colors if not specified
    if max_colors <= 0:
        # Count approximate unique hues in fill area
        fill_pixels = rgb_array[fill_mask]
        if len(fill_pixels) > 100:
            # Sample for speed
            sample_idx = np.random.choice(len(fill_pixels), min(5000, len(fill_pixels)), replace=False)
            sample = fill_pixels[sample_idx]
            # Count distinct colors (quantized to 16 levels per channel)
            quantized = (sample // 16).astype(np.uint32)
            color_keys = quantized[:, 0] * 256 + quantized[:, 1] * 16 + quantized[:, 2]
            n_distinct = len(np.unique(color_keys))
            max_colors = min(8, max(4, n_distinct // 10)) if n_distinct < 200 else min(24, n_distinct // 20)
        else:
            max_colors = 6

    # Step 1: Quantize fill pixels using PIL median cut
    fill_img = Image.fromarray(rgb_array).convert("RGB")
    quantized_img = fill_img.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    # Get the palette (list of N RGB triplets)
    q_palette = quantized_img.getpalette()[:max_colors * 3]
    dominant_colors = np.array(q_palette, dtype=np.uint8).reshape(-1, 3)

    # Step 2: Match each dominant color to closest palette bead color
    dominant_lab = rgb_to_lab(dominant_colors)
    palette_lab = palette["lab"]
    palette_rgb = palette["rgb_array"]

    from color_science import ciede2000
    distances = ciede2000(dominant_lab, palette_lab)  # (N, M)
    best_palette_idx = np.argmin(distances, axis=1)   # (N,)
    mapped_rgb = palette_rgb[best_palette_idx]  # (N, 3) — each dominant color's bead RGB

    # Step 3: Find darkest palette color for edges
    palette_lum = 0.299 * palette_rgb[:, 0].astype(float) + 0.587 * palette_rgb[:, 1].astype(float) + 0.114 * palette_rgb[:, 2].astype(float)
    darkest_palette_rgb = palette_rgb[np.argmin(palette_lum)]

    # Step 4: Replace pixels
    # Convert quantized image back to indices
    q_indices = np.array(quantized_img)  # (H, W) index into quantized palette
    result = np.zeros_like(rgb_array)

    for i in range(max_colors):
        mask = (q_indices == i)
        result[mask] = mapped_rgb[i]

    # Overwrite edges with darkest bead color
    result[is_edge & valid_mask] = darkest_palette_rgb

    # Transparent areas stay as-is (will be masked later)
    if alpha_mask is not None:
        result[~alpha_mask] = rgb_array[~alpha_mask]

    return result


def _compute_gradient_lines(src_size: int, n_lines: int, gradient_1d: np.ndarray, snap_range: int = 3) -> list:
    """Compute grid line positions that snap to gradient peaks (color boundaries).

    Instead of evenly-spaced grid lines, shift each line to the nearest
    strong gradient within ±snap_range pixels. This aligns cell boundaries
    with actual color transitions, producing cleaner outlines.

    Inspired by perfectPixel's grid refinement technique.
    """
    # Start with evenly spaced lines
    step = src_size / n_lines
    lines = [0]
    for i in range(1, n_lines):
        base = int(i * step)
        # Search for gradient peak within ±snap_range
        best_pos = base
        best_grad = gradient_1d[base] if 0 <= base < len(gradient_1d) else 0
        for offset in range(-snap_range, snap_range + 1):
            pos = base + offset
            if 0 <= pos < len(gradient_1d) and gradient_1d[pos] > best_grad:
                best_grad = gradient_1d[pos]
                best_pos = pos
        lines.append(best_pos)
    lines.append(src_size)
    return lines


def _kmeans2_majority(pixels_flat: np.ndarray) -> np.ndarray:
    """K-means with K=2 to find dominant color, discarding anti-aliasing.

    Splits pixels into 2 clusters, returns the center of the larger cluster.
    This naturally removes anti-aliased fringe pixels (the minority cluster).
    """
    if len(pixels_flat) <= 2:
        return pixels_flat.mean(axis=0).astype(np.uint8)

    # Initialize: c0 = first pixel, c1 = farthest from c0
    c0 = pixels_flat[0].astype(np.float64)
    dists = np.sum((pixels_flat.astype(np.float64) - c0) ** 2, axis=1)
    c1 = pixels_flat[np.argmax(dists)].astype(np.float64)

    if np.array_equal(c0, c1):
        return c0.astype(np.uint8)

    # 4 iterations of K-means
    for _ in range(4):
        d0 = np.sum((pixels_flat.astype(np.float64) - c0) ** 2, axis=1)
        d1 = np.sum((pixels_flat.astype(np.float64) - c1) ** 2, axis=1)
        mask0 = d0 <= d1
        if mask0.sum() > 0:
            c0 = pixels_flat[mask0].mean(axis=0).astype(np.float64)
        if (~mask0).sum() > 0:
            c1 = pixels_flat[~mask0].mean(axis=0).astype(np.float64)

    # Return majority cluster center
    d0 = np.sum((pixels_flat.astype(np.float64) - c0) ** 2, axis=1)
    d1 = np.sum((pixels_flat.astype(np.float64) - c1) ** 2, axis=1)
    count0 = (d0 <= d1).sum()
    return (c0 if count0 >= len(pixels_flat) - count0 else c1).astype(np.uint8)


def pixelate(rgb_array: np.ndarray, width: int, height: int,
             alpha_mask: np.ndarray | None = None,
             edge_threshold: int = 200) -> tuple[np.ndarray, np.ndarray | None]:
    """Gradient-aligned pixelation with K-means majority voting.

    Two key improvements over naive downscaling:
    1. Grid lines snap to color boundaries (gradient peaks) → cleaner outlines
    2. Each cell uses K-means(K=2) majority color → anti-aliasing discarded
    """
    from PIL import ImageFilter
    src_h, src_w = rgb_array.shape[:2]

    # Compute gradient magnitude for grid alignment
    gray = Image.fromarray(rgb_array).convert("L")
    grad_img = gray.filter(ImageFilter.FIND_EDGES)
    grad = np.array(grad_img).astype(np.float64)

    # Project gradient to 1D (sum along each axis)
    grad_x = grad.sum(axis=0)  # vertical gradient → horizontal positions
    grad_y = grad.sum(axis=1)  # horizontal gradient → vertical positions

    # Compute gradient-aligned grid lines
    x_lines = _compute_gradient_lines(src_w, width, grad_x)
    y_lines = _compute_gradient_lines(src_h, height, grad_y)

    # Sample each cell using K-means majority voting
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    for ty in range(height):
        sy0, sy1 = y_lines[ty], y_lines[ty + 1]
        if sy1 <= sy0:
            sy1 = sy0 + 1
        for tx in range(width):
            sx0, sx1 = x_lines[tx], x_lines[tx + 1]
            if sx1 <= sx0:
                sx1 = sx0 + 1

            region = rgb_array[sy0:sy1, sx0:sx1]
            flat = region.reshape(-1, 3)

            if len(flat) == 0:
                continue

            # K-means(K=2) majority voting
            pixels[ty, tx] = _kmeans2_majority(flat)

    alpha = None
    if alpha_mask is not None:
        alpha_img = Image.fromarray(alpha_mask.astype(np.uint8) * 255)
        alpha_img = alpha_img.resize((width, height), Image.NEAREST)
        alpha = np.array(alpha_img) > 30

    return pixels, alpha


def color_match_grid(pixels: np.ndarray, palette: dict,
                     alpha: np.ndarray | None = None) -> np.ndarray:
    """Match each pixel to closest palette color.

    Returns:
        grid: (H, W) int array. -1 = empty cell (transparent), otherwise palette index.
    """
    h, w, _ = pixels.shape
    flat_pixels = pixels.reshape(-1, 3)

    # Convert to Lab
    pixels_lab = rgb_to_lab(flat_pixels)

    # Match
    indices = match_colors(pixels_lab, palette)

    # Reshape
    grid = indices.reshape(h, w)

    # Apply alpha mask
    if alpha is not None:
        grid[~alpha] = -1  # -1 = empty cell

    return grid


def reflow_outlines(grid: np.ndarray, palette: dict) -> np.ndarray:
    """Reflow outlines: replace messy outlines with smooth color-boundary outlines.

    The best approach for bead art outlines:
    1. Remove outline-black (black cells between different fill colors) — these are messy
    2. Keep feature-black (black cells within same-color regions) — eyes, whiskers, etc.
    3. Re-add outlines at color boundaries — guaranteed smooth, continuous, 1-cell wide
    """
    h, w = grid.shape
    palette_rgb = palette["rgb_array"]
    palette_lum = (0.299 * palette_rgb[:, 0].astype(float)
                   + 0.587 * palette_rgb[:, 1].astype(float)
                   + 0.114 * palette_rgb[:, 2].astype(float))
    B = int(np.argmin(palette_lum))

    # Step 1: Classify black cells
    clean = grid.copy()
    for y in range(h):
        for x in range(w):
            if grid[y, x] != B:
                continue
            fills = [grid[y + dy, x + dx]
                     for dy in [-1, 0, 1] for dx in [-1, 0, 1]
                     if (dy, dx) != (0, 0) and 0 <= y + dy < h and 0 <= x + dx < w
                     and grid[y + dy, x + dx] != B and grid[y + dy, x + dx] != -1]
            if not fills:
                continue
            if len(set(fills)) > 1:
                # Between different colors → outline artifact → remove
                vals, counts = np.unique(fills, return_counts=True)
                clean[y, x] = vals[np.argmax(counts)]

    # Step 1.5: Thin remaining black cells (feature-black might be too thick)
    for _pass in range(3):
        changed = False
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if clean[y, x] != B:
                    continue
                bn = sum(1 for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]
                         if clean[y+dy, x+dx] == B)
                if bn >= 3:
                    fills = [clean[y+dy, x+dx] for dy in [-1,0,1] for dx in [-1,0,1]
                             if (dy,dx)!=(0,0) and 0<=y+dy<h and 0<=x+dx<w
                             and clean[y+dy,x+dx]!=B and clean[y+dy,x+dx]!=-1]
                    if fills:
                        vals, counts = np.unique(fills, return_counts=True)
                        clean[y, x] = vals[np.argmax(counts)]
                        changed = True
        if not changed:
            break

    # Step 2+3: Detect color boundaries and add smooth outlines
    result = clean.copy()
    for y in range(h):
        for x in range(w):
            if clean[y, x] == -1 or clean[y, x] == B:
                continue
            c = clean[y, x]
            is_boundary = any(
                (0 <= y + dy < h and 0 <= x + dx < w
                 and clean[y + dy, x + dx] != c and clean[y + dy, x + dx] != B)
                or (0 <= y + dy < h and 0 <= x + dx < w and clean[y + dy, x + dx] == -1)
                or not (0 <= y + dy < h and 0 <= x + dx < w)
                for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            )
            if not is_boundary:
                continue
            same = sum(1 for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                       if 0 <= y + dy < h and 0 <= x + dx < w and clean[y + dy, x + dx] == c)
            if same <= 2:
                result[y, x] = B

    return result


def compute_statistics(grid: np.ndarray, palette: dict) -> dict:
    """Compute bead usage statistics."""
    h, w = grid.shape
    total_cells = h * w
    empty_cells = int(np.sum(grid == -1))
    filled_cells = total_cells - empty_cells

    # Count per color
    counts = {}
    for idx in grid.flat:
        if idx == -1:
            continue
        idx = int(idx)
        if idx not in counts:
            counts[idx] = 0
        counts[idx] += 1

    # Build breakdown sorted by count desc
    breakdown = []
    for idx, count in sorted(counts.items(), key=lambda x: -x[1]):
        color = palette["colors"][idx]
        breakdown.append({
            "code": color["code"],
            "name": color["name"],
            "rgb": color["rgb"],
            "count": count,
        })

    return {
        "board_width": w,
        "board_height": h,
        "total_cells": total_cells,
        "filled_cells": filled_cells,
        "empty_cells": empty_cells,
        "colors_used": len(breakdown),
        "palette_brand": palette["brand"],
        "palette_series": palette["series"],
        "breakdown": breakdown,
    }


def parse_board(board_str: str) -> tuple[int, int]:
    """Parse board size string like '58x58' or '29x29'."""
    parts = board_str.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid board size '{board_str}'. Use format WxH, e.g. 58x58")
    return int(parts[0]), int(parts[1])


def parse_grid(grid_str: str) -> tuple[int, int]:
    """Parse multi-board grid string like '2x3'."""
    parts = grid_str.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid grid '{grid_str}'. Use format RxC, e.g. 2x3")
    rows, cols = int(parts[0]), int(parts[1])
    if rows < 1 or cols < 1 or rows > 5 or cols > 5:
        raise ValueError(f"Grid must be 1-5 rows and 1-5 cols, got {rows}x{cols}")
    return rows, cols


def main():
    parser = argparse.ArgumentParser(
        description="Pindou: Convert images to Perler bead patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python convert.py photo.png
  python convert.py photo.png --board 29x29 --palette hama_midi
  python convert.py photo.png --board 58x58 --palette artkal_s --exclude S01,S02
  python convert.py photo.png --grid 2x3 --board 29x29
""")
    parser.add_argument("image", nargs="?", help="Input image path")

    board_group = parser.add_argument_group("Board options")
    board_group.add_argument("--board", default="58x58", help="Board size WxH (default: 58x58)")
    board_group.add_argument("--grid", default="1x1", help="Multi-board grid RxC (default: 1x1)")

    color_group = parser.add_argument_group("Color options")
    color_group.add_argument("--palette", default="artkal_s", help="Palette name (default: artkal_s)")
    color_group.add_argument("--exclude", help="Comma-separated color codes to exclude")
    color_group.add_argument("--only", help="Comma-separated color codes to use exclusively")

    dither_group = parser.add_argument_group("Dithering options")
    dither_group.add_argument("--dither", choices=["none", "floyd", "bayer"], default="none",
                              help="Dithering algorithm (default: none)")
    dither_group.add_argument("--dither-strength", type=int, default=100,
                              help="Dithering strength 0-100 (default: 100)")

    adjust_group = parser.add_argument_group("Color adjustment")
    adjust_group.add_argument("--replace", action="append", metavar="A:B",
                              help="Replace color A with B (repeatable)")
    adjust_group.add_argument("--tone-shift", choices=["warm", "cool", "bright", "dark"],
                              help="Shift overall tone")
    adjust_group.add_argument("--tone-strength", type=int, default=30,
                              help="Tone shift strength 0-100 (default: 30)")

    board_group.add_argument("--max-colors", type=int, default=0,
                              help="Max distinct colors (0=auto, 6-8 for cartoons, 15-24 for photos)")
    board_group.add_argument("--edge-threshold", type=int, default=200,
                              help="Edge detection threshold 0-255 (default: 80, lower=more edges)")

    bg_group = parser.add_argument_group("Background removal")
    bg_group.add_argument("--remove-bg", action="store_true",
                          help="Remove background using rembg (requires pip install rembg)")

    export_group = parser.add_argument_group("Export options")
    export_group.add_argument("--output-dir", help="Output directory (default: auto-generated)")
    export_group.add_argument("--project-name", help="Project name (default: from image filename)")
    export_group.add_argument("--mode", default="blocks+numbers",
                              choices=["blocks", "dots", "numbers", "blocks+numbers"],
                              help="Display mode (default: blocks+numbers)")
    export_group.add_argument("--cell-size", type=int, default=20, help="Pixels per cell (default: 20)")
    export_group.add_argument("--ref-lines", type=int, default=10, help="Reference line interval (default: 10)")
    # PDF export removed — PNG only

    info_group = parser.add_argument_group("Info")
    info_group.add_argument("--list-palettes", action="store_true", help="List available palettes")
    info_group.add_argument("--list-colors", metavar="PALETTE", help="List colors in a palette")

    args = parser.parse_args()

    palettes_dir = Path(__file__).parent.parent / "data" / "palettes"

    # Info commands
    if args.list_palettes:
        for f in sorted(palettes_dir.glob("*.json")):
            p = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {f.stem:20s} {p['brand']} {p['series']} ({p['color_count']} colors)")
        return

    if args.list_colors:
        p = load_palette(args.list_colors, palettes_dir)
        print(f"{p['brand']} {p['series']} — {len(p['colors'])} colors:")
        for c in p["colors"]:
            status = " [DISCONTINUED]" if c.get("discontinued") else ""
            print(f"  {c['code']:10s} {c['name']:30s} RGB({c['rgb'][0]:3d},{c['rgb'][1]:3d},{c['rgb'][2]:3d}){status}")
        return

    # Main conversion — image is required for this
    if not args.image:
        parser.error("image path is required for conversion")
    t0 = time.time()

    # Parse parameters
    board_w, board_h = parse_board(args.board)
    grid_rows, grid_cols = parse_grid(args.grid)
    total_w = board_w * grid_cols
    total_h = board_h * grid_rows

    if total_w > 200 or total_h > 200:
        print(f"Warning: Total grid size {total_w}x{total_h} exceeds 200x200. This may be slow.", file=sys.stderr)

    # Load image
    img = load_image(args.image)
    w, h = img.size
    if max(w, h) < 50:
        print(f"Warning: Image is very small ({w}x{h}). Conversion quality may be poor.", file=sys.stderr)

    # Preprocess
    rgb_array, alpha_mask = preprocess(img)

    # Background removal (optional)
    if hasattr(args, 'remove_bg') and args.remove_bg:
        try:
            from rembg import remove as rembg_remove
            from PIL import Image as PILImage
            import io
            # Convert back to PIL for rembg
            pil_img = PILImage.fromarray(rgb_array)
            result = rembg_remove(pil_img)
            result_arr = np.array(result)
            rgb_array = result_arr[:, :, :3]
            alpha_mask = result_arr[:, :, 3] > 30
            print("Background removed successfully.", file=sys.stderr)
        except ImportError:
            print("Error: rembg not installed. Run: pip3 install rembg", file=sys.stderr)
            sys.exit(1)

    # Load palette
    palette = load_palette(args.palette, palettes_dir)

    # Filter palette
    exclude_list = args.exclude.split(",") if args.exclude else None
    only_list = args.only.split(",") if args.only else None
    if exclude_list or only_list:
        palette = filter_palette(palette, exclude=exclude_list, only=only_list)

    if len(palette["colors"]) < 10:
        print(f"Warning: Only {len(palette['colors'])} colors available. Pattern quality may be poor.", file=sys.stderr)

    # NEW PIPELINE: Quantize colors FIRST, then pixelate
    # Step 1: Reduce original image to N clean palette colors
    rgb_array = quantize_colors(
        rgb_array, alpha_mask, palette,
        max_colors=args.max_colors,
        edge_threshold=args.edge_threshold,
    )

    # Step 2: Pixelate the clean image using edge-aware mode voting
    pixels, alpha = pixelate(
        rgb_array, total_w, total_h, alpha_mask,
        edge_threshold=args.edge_threshold,
    )

    # Step 3: Map pixel RGB values directly to palette indices
    # (pixels are already palette colors from quantization, just find index)
    grid = color_match_grid(pixels, palette, alpha)

    # Reflow outlines: replace messy outlines with smooth color-boundary outlines
    grid = reflow_outlines(grid, palette)

    # Color adjustments (post-matching)
    if args.replace:
        code_to_idx = {c["code"]: i for i, c in enumerate(palette["colors"])}
        for rep in args.replace:
            if ":" not in rep:
                print(f"Warning: Invalid replace format '{rep}', use A:B", file=sys.stderr)
                continue
            a, b = rep.split(":", 1)
            if a not in code_to_idx or b not in code_to_idx:
                print(f"Warning: Color code '{a}' or '{b}' not in palette", file=sys.stderr)
                continue
            grid[grid == code_to_idx[a]] = code_to_idx[b]

    # Statistics
    stats = compute_statistics(grid, palette)
    elapsed = time.time() - t0

    # Setup output
    project_name = args.project_name or Path(args.image).stem
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(f"pindou_output_{project_name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save intermediate data for grid_render.py
    pattern_data = {
        "grid": grid.tolist(),
        "palette_name": args.palette,
        "palette_colors": palette["colors"],
        "palette_rgb": palette["rgb_array"].tolist(),
        "board_w": board_w,
        "board_h": board_h,
        "grid_rows": grid_rows,
        "grid_cols": grid_cols,
        "project_name": project_name,
        "statistics": stats,
    }
    pattern_path = output_dir / "pattern.json"
    with open(pattern_path, "w", encoding="utf-8") as f:
        json.dump(pattern_data, f, ensure_ascii=False)

    # Render PNG via grid_render
    try:
        from grid_render import render_and_export
        files = render_and_export(
            grid=grid,
            palette=palette,
            board_w=board_w,
            board_h=board_h,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            mode=args.mode,
            cell_size=args.cell_size,
            ref_interval=args.ref_lines,
            output_dir=output_dir,
            project_name=project_name,
        )
    except ImportError:
        files = [str(pattern_path)]
        print("Warning: grid_render.py not found. Only pattern.json saved.", file=sys.stderr)

    # Output result JSON to stdout
    result = {
        "output_dir": str(output_dir),
        "files": [str(f) for f in files],
        "elapsed_seconds": round(elapsed, 2),
        "statistics": stats,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
