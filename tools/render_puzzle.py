#!/usr/bin/env python3
"""Render the recovered Star Battle regions and solution as submission images."""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from pathlib import Path


PALETTE = {
    "A": "#CFE8FF", "B": "#FFD9C7", "C": "#D9F2D0", "D": "#EEE0FF",
    "E": "#FFF0B8", "F": "#CDEFEA", "G": "#F8D2E2", "H": "#DCE0FA",
    "I": "#D8EDC4", "J": "#F9DCC4", "K": "#D7D7D7",
}


def svg_text(x, y, value, size, *, weight="400", fill="#17212B", anchor="middle"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{value}</text>'
    )


def star_points(cx: float, cy: float, outer: float, inner: float) -> str:
    points = []
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = outer if index % 2 == 0 else inner
        points.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(points)


def render(regions: list[str], bits: str | None) -> str:
    width, height = 1400, 1375
    cell, left, top = 100, 150, 100
    board = 11 * cell
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#F8FAFC"/>',
    ]

    for index in range(11):
        out.append(svg_text(left + index * cell + cell / 2, top - 30, str(index + 1), 20, fill="#52606D"))
        out.append(svg_text(left - 32, top + index * cell + 61, str(index + 1), 20, fill="#52606D"))

    for row in range(11):
        for col in range(11):
            x, y = left + col * cell, top + row * cell
            label = regions[row][col]
            out.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{PALETTE[label]}"/>')
            out.append(svg_text(x + 16, y + 25, label, 18, weight="600", fill="#52606D", anchor="start"))
            if bits and bits[11 * row + col] == "1":
                out.append(
                    f'<polygon points="{star_points(x + cell / 2, y + cell / 2 + 3, 31, 13)}" '
                    'fill="#17212B" stroke="#FFFFFF" stroke-width="3" stroke-linejoin="round"/>'
                )

    # Fine cell grid.
    for index in range(12):
        pos = index * cell
        out.append(f'<line x1="{left + pos}" y1="{top}" x2="{left + pos}" y2="{top + board}" stroke="#FFFFFF" stroke-width="2"/>')
        out.append(f'<line x1="{left}" y1="{top + pos}" x2="{left + board}" y2="{top + pos}" stroke="#FFFFFF" stroke-width="2"/>')

    # Heavy borders only where regions differ.
    border = '#17212B'
    for row in range(11):
        for col in range(11):
            x, y = left + col * cell, top + row * cell
            here = regions[row][col]
            if row == 0 or regions[row - 1][col] != here:
                out.append(f'<line x1="{x}" y1="{y}" x2="{x + cell}" y2="{y}" stroke="{border}" stroke-width="7"/>')
            if col == 0 or regions[row][col - 1] != here:
                out.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + cell}" stroke="{border}" stroke-width="7"/>')
            if row == 10:
                out.append(f'<line x1="{x}" y1="{y + cell}" x2="{x + cell}" y2="{y + cell}" stroke="{border}" stroke-width="7"/>')
            if col == 10:
                out.append(f'<line x1="{x + cell}" y1="{y}" x2="{x + cell}" y2="{y + cell}" stroke="{border}" stroke-width="7"/>')

    if bits:
        out.append(svg_text(width / 2, 1260, "22 stars · 2 per row, column, and region · no touching", 23, weight="600"))
        out.append(svg_text(width / 2, 1315, "CHIP OUTPUT:  (* TWO STARS *)", 29, weight="700", fill="#0B6E4F"))
    else:
        out.append(svg_text(width / 2, 1280, "A–K: regions recovered from gate-level state influence", 22, fill="#52606D"))
    out.append('</svg>')
    return "\n".join(out) + "\n"


def convert(svg: Path, png: Path) -> None:
    renderer = shutil.which("rsvg-convert")
    if renderer:
        subprocess.run([renderer, "-w", "1400", "-h", "1375", "-o", str(png), str(svg)], check=True)
        return
    renderer = shutil.which("magick") or shutil.which("convert")
    if renderer:
        subprocess.run([renderer, "-density", "144", str(svg), "-resize", "1400x1375", str(png)], check=True)
        return
    raise SystemExit("PNG conversion requires rsvg-convert or ImageMagick")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("region_map", type=Path)
    parser.add_argument("solution_bits", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/visuals"))
    args = parser.parse_args()
    regions = [line.strip() for line in args.region_map.read_text().splitlines() if line.strip()]
    bits = "".join(args.solution_bits.read_text().split())
    if len(regions) != 11 or any(len(row) != 11 for row in regions):
        raise SystemExit("region map must be 11 rows of 11 labels")
    if len(bits) != 121 or set(bits) - {"0", "1"}:
        raise SystemExit("solution must contain exactly 121 binary digits")

    args.outdir.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("recovered_puzzle", None),
        ("solved_puzzle", bits),
    ]
    for name, pattern in jobs:
        svg = args.outdir / f"{name}.svg"
        png = args.outdir / f"{name}.png"
        svg.write_text(render(regions, pattern))
        convert(svg, png)
        print(f"wrote {png}")


if __name__ == "__main__":
    main()
