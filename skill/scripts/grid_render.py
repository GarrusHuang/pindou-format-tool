#!/usr/bin/env python3
"""
Grid renderer for Perler bead patterns.

Renders bead grids as images with multiple display modes,
grid lines, reference lines, row/column numbering, and multi-board support.
"""

import json
import sys
from pathlib import Path
from typing import List

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Get a font at the given size. Prefers fonts with CJK (Chinese) support."""
    # CJK-capable fonts first (for Chinese text), then Latin fallbacks
    font_paths = [
        str(Path(__file__).parent.parent / "assets" / "fonts" / "NotoSansSC-Regular.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def text_color_for_bg(rgb: tuple) -> tuple:
    """Choose black or white text based on background luminance."""
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (0, 0, 0) if luminance > 128 else (255, 255, 255)


def render_pattern(
    grid: np.ndarray,
    palette_colors: list,
    palette_rgb: np.ndarray,
    mode: str = "blocks+numbers",
    cell_size: int = 20,
    ref_interval: int = 10,
    margin: int = 0,
    title: str = None,
) -> Image.Image:
    """Render a bead pattern grid as a PIL Image.

    Args:
        grid: (H, W) int array. -1 = empty cell, else index into palette.
        palette_colors: list of color dicts with 'code', 'name', 'rgb'.
        palette_rgb: (N, 3) uint8 array of palette RGB values.
        mode: 'blocks', 'dots', 'numbers', 'blocks+numbers'
        cell_size: pixels per cell
        ref_interval: draw thick reference line every N cells (0 = disabled)
        margin: extra margin for axis labels (auto-calculated if 0)
        title: optional title text above the grid
    """
    h, w = grid.shape

    # Auto margin for labels
    if margin == 0:
        label_font = get_font(max(8, cell_size // 2))
        margin = cell_size + 4  # space for row/col numbers

    title_height = 0
    if title:
        title_font = get_font(max(12, cell_size))
        title_height = cell_size + 8

    img_w = margin + w * cell_size + 2
    img_h = margin + h * cell_size + 2 + title_height
    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    ox = margin  # origin x
    oy = margin + title_height  # origin y

    # Title
    if title:
        title_font = get_font(max(12, cell_size))
        draw.text((ox, 2), title, fill=(0, 0, 0), font=title_font)

    # Draw cells
    empty_color = (240, 240, 240)  # light gray for empty cells
    num_font = get_font(max(6, cell_size * 2 // 5))

    for y in range(h):
        for x in range(w):
            cx = ox + x * cell_size
            cy = oy + y * cell_size
            idx = int(grid[y, x])

            if idx == -1:
                # Empty cell
                if "blocks" in mode:
                    draw.rectangle([cx, cy, cx + cell_size - 1, cy + cell_size - 1],
                                  fill=empty_color, outline=(220, 220, 220))
                continue

            rgb = tuple(palette_rgb[idx])
            code = palette_colors[idx]["code"]

            if "blocks" in mode:
                draw.rectangle([cx, cy, cx + cell_size - 1, cy + cell_size - 1], fill=rgb)

            if mode == "dots":
                # Draw circle
                r = cell_size * 0.4
                center_x = cx + cell_size / 2
                center_y = cy + cell_size / 2
                draw.ellipse([center_x - r, center_y - r, center_x + r, center_y + r], fill=rgb)

            if "numbers" in mode:
                tc = text_color_for_bg(rgb) if "blocks" in mode else (0, 0, 0)
                # Truncate code if too long for cell
                display_code = code
                bbox = draw.textbbox((0, 0), display_code, font=num_font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                # Center text in cell
                tx = cx + (cell_size - text_w) / 2
                ty = cy + (cell_size - text_h) / 2
                draw.text((tx, ty), display_code, fill=tc, font=num_font)

    # Grid lines
    line_color = (180, 180, 180)
    ref_color = (80, 80, 80)

    for x in range(w + 1):
        px = ox + x * cell_size
        is_ref = ref_interval > 0 and x % ref_interval == 0
        color = ref_color if is_ref else line_color
        width = 2 if is_ref else 1
        draw.line([(px, oy), (px, oy + h * cell_size)], fill=color, width=width)

    for y in range(h + 1):
        py = oy + y * cell_size
        is_ref = ref_interval > 0 and y % ref_interval == 0
        color = ref_color if is_ref else line_color
        width = 2 if is_ref else 1
        draw.line([(ox, py), (ox + w * cell_size, py)], fill=color, width=width)

    # Axis labels
    label_font = get_font(max(7, cell_size // 3))
    for x in range(w):
        if ref_interval > 0 and x % ref_interval == 0:
            label = str(x + 1)
            bbox = draw.textbbox((0, 0), label, font=label_font)
            lw = bbox[2] - bbox[0]
            draw.text((ox + x * cell_size + (cell_size - lw) / 2, oy - cell_size // 2 - 2 + title_height),
                      label, fill=(100, 100, 100), font=label_font)

    for y in range(h):
        if ref_interval > 0 and y % ref_interval == 0:
            label = str(y + 1)
            bbox = draw.textbbox((0, 0), label, font=label_font)
            lh = bbox[3] - bbox[1]
            draw.text((2, oy + y * cell_size + (cell_size - lh) / 2),
                      label, fill=(100, 100, 100), font=label_font)

    return img


def split_boards(grid: np.ndarray, board_w: int, board_h: int,
                 grid_rows: int, grid_cols: int) -> list:
    """Split grid into individual boards.

    Returns: list of (sub_grid, row_idx, col_idx) tuples
    """
    boards = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            y0 = r * board_h
            y1 = y0 + board_h
            x0 = c * board_w
            x1 = x0 + board_w
            sub = grid[y0:y1, x0:x1]
            boards.append((sub, r + 1, c + 1))
    return boards


def render_and_export(
    grid: np.ndarray,
    palette: dict,
    board_w: int,
    board_h: int,
    grid_rows: int,
    grid_cols: int,
    mode: str = "blocks+numbers",
    cell_size: int = 20,
    ref_interval: int = 10,
    output_dir: Path = None,
    project_name: str = "pattern",
) -> List[str]:
    """Render and export all PNG files.

    Returns: list of output file paths.
    """
    if output_dir is None:
        output_dir = Path(".")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = []
    palette_colors = palette["colors"]
    palette_rgb = palette["rgb_array"]

    # Global pattern (blocks+numbers)
    global_img = render_pattern(
        grid, palette_colors, palette_rgb,
        mode=mode, cell_size=cell_size, ref_interval=ref_interval,
        title=f"{project_name} ({grid.shape[1]}x{grid.shape[0]})"
    )
    global_path = output_dir / f"{project_name}_global.png"
    global_img.save(str(global_path))
    files.append(str(global_path))

    # Dot mode preview
    dots_img = render_pattern(
        grid, palette_colors, palette_rgb,
        mode="dots", cell_size=cell_size, ref_interval=ref_interval,
    )
    dots_path = output_dir / f"{project_name}_dots.png"
    dots_img.save(str(dots_path))
    files.append(str(dots_path))

    # Per-board exports (if multi-board)
    if grid_rows > 1 or grid_cols > 1:
        boards = split_boards(grid, board_w, board_h, grid_rows, grid_cols)

        # Add board boundaries to global image
        draw = ImageDraw.Draw(global_img)
        margin = cell_size + 4
        title_h = cell_size + 8
        for r in range(1, grid_rows):
            py = margin + title_h + r * board_h * cell_size
            draw.line([(margin, py), (margin + grid.shape[1] * cell_size, py)],
                      fill=(255, 0, 0), width=2)
        for c in range(1, grid_cols):
            px = margin + c * board_w * cell_size
            draw.line([(px, margin + title_h), (px, margin + title_h + grid.shape[0] * cell_size)],
                      fill=(255, 0, 0), width=2)
        global_img.save(str(global_path))  # overwrite with boundary lines

        for sub_grid, row, col in boards:
            board_img = render_pattern(
                sub_grid, palette_colors, palette_rgb,
                mode=mode, cell_size=cell_size, ref_interval=ref_interval,
                title=f"Board R{row}C{col} ({board_w}x{board_h})"
            )
            board_path = output_dir / f"{project_name}_board_R{row}C{col}.png"
            board_img.save(str(board_path))
            files.append(str(board_path))

    return files


# CLI interface
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python grid_render.py <pattern.json> [options]")
        print("  --mode blocks|dots|numbers|blocks+numbers")
        print("  --cell-size N")
        print("  --ref-lines N")
        print("  --output-dir DIR")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern_json")
    parser.add_argument("--mode", default="blocks+numbers")
    parser.add_argument("--cell-size", type=int, default=20)
    parser.add_argument("--ref-lines", type=int, default=10)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    with open(args.pattern_json, "r") as f:
        data = json.load(f)

    grid = np.array(data["grid"])
    palette = {
        "colors": data["palette_colors"],
        "rgb_array": np.array(data["palette_rgb"], dtype=np.uint8),
    }

    files = render_and_export(
        grid=grid,
        palette=palette,
        board_w=data["board_w"],
        board_h=data["board_h"],
        grid_rows=data["grid_rows"],
        grid_cols=data["grid_cols"],
        mode=args.mode,
        cell_size=args.cell_size,
        ref_interval=args.ref_lines,
        output_dir=Path(args.output_dir),
        project_name=data["project_name"],
    )
    print(f"Exported {len(files)} files:")
    for f in files:
        print(f"  {f}")
