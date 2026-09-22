#!/usr/bin/env python3
"""Parametric laser-cut case for the CrowPanel 2.13" e-paper weather station.

A stack of plywood layers with the board behind a window, an 18650 holder
below it and neodymium magnets for mounting on a fridge or any steel surface.
The last layer is a separate mount plate that stays on the fridge; the frame
clips onto it magnetically, so swapping the battery means pulling the frame off.

    python3 case.py            # writes out/*.svg, out/*.dxf and out/preview.png

All sizes are in millimetres. Edit PARAMS below (or override on the command
line, e.g. `python3 case.py ply=2.8 holder_h=18.5`) after measuring your parts.
Every layer is drawn as seen from the FRONT of the case.
"""

import math
import sys
from pathlib import Path

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

PARAMS = {
    # Material
    "ply": 3.0,             # sheet thickness (measure it: "3 mm" is often 2.7-3.2)
    "kerf": 0.10,           # laser kerf; outlines grow and holes shrink by kerf/2

    # Board (bare, without the acrylic shell) - from Elecrow's Eagle files
    "pcb_w": 63.2,
    "pcb_h": 31.2,
    "pcb_fit": 0.3,         # clearance around the board in its pocket
    "board_stack": 2.8,     # PCB + e-paper glass thickness; must fit in one layer
    "back_parts": 4.0,      # tallest component on the back of the board
    "edge_relief": 2.5,     # extra room on the left edge for the dial and side buttons
    "edge_relief_len": 26.0,

    # Visible screen area (2.13" 122x250 panel: 48.55 x 23.71 active area)
    "win_w": 50.5,
    "win_h": 25.7,
    "win_r": 1.0,
    "win_dx": 0.0,          # window offset from the board centre (+ = right)
    "win_dy": 0.0,          # (+ = down)

    # 18650 holder (single-cell, open type)
    "holder_l": 77.0,
    "holder_w": 21.0,
    "holder_h": 19.0,
    "holder_fit": 0.5,

    # Magnets (neodymium discs); thickness should equal one layer
    "mag_d": 8.0,           # 8 x 3 mm discs; 10 x 3 also works (case gets wider)
    "mag_t": 3.0,
    "mag_fit": 0.2,
    "mag_wall": 1.5,        # minimum wood around a magnet pocket

    # Alignment pins between frame and mount plate (e.g. 3 mm dowel)
    "pin_d": 3.0,
    "pins": 1,              # 1 = add two pin holes, 0 = none

    # Frame
    "wall": 4.5,            # outer wall
    "rib": 4.0,             # wood between board pocket and holder pocket (layer 2)
    "channel_w": 30.0,      # wire channel from holder to board (layers 3+)
    "corner_r": 5.0,
}


def parse_overrides(p):
    for arg in sys.argv[1:]:
        k, _, v = arg.partition("=")
        if k not in p:
            sys.exit(f"unknown parameter: {k}")
        p[k] = float(v)
    return p


def rounded_rect(x0, y0, x1, y1, r):
    if r <= 0:
        return box(x0, y0, x1, y1)
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=16)


def build(p):
    t = p["ply"]
    k2 = p["kerf"] / 2

    # ---- layout (front view, origin top-left, y down) ----
    board_w = p["pcb_w"] + 2 * p["pcb_fit"]
    board_h = p["pcb_h"] + 2 * p["pcb_fit"]
    hold_w = p["holder_l"] + 2 * p["holder_fit"]
    hold_h = p["holder_w"] + 2 * p["holder_fit"]
    mag_hole = p["mag_d"] + p["mag_fit"]

    # Width: the holder must fit, and the top magnets must fit beside the board.
    W = max(hold_w + 2 * p["wall"],
            board_w + p["edge_relief"] + 2 * (p["wall"] + mag_hole + p["mag_wall"]))
    # Height: board, rib, holder, then a row of magnets below the holder.
    board_y0 = p["wall"]
    hold_y0 = board_y0 + board_h + p["rib"]
    mag_row_y = hold_y0 + hold_h + p["mag_wall"] + mag_hole / 2
    H = mag_row_y + mag_hole / 2 + p["wall"]

    board_x0 = (W - board_w - p["edge_relief"]) / 2 + p["edge_relief"]  # centre board + relief
    hold_x0 = (W - hold_w) / 2
    board = box(board_x0, board_y0, board_x0 + board_w, board_y0 + board_h)
    relief_y0 = board_y0 + (board_h - p["edge_relief_len"]) / 2
    relief = box(board_x0 - p["edge_relief"], relief_y0, board_x0 + 0.01,
                 relief_y0 + p["edge_relief_len"])
    board_pocket = board.union(relief)
    holder = rounded_rect(hold_x0, hold_y0, hold_x0 + hold_w, hold_y0 + hold_h, 1.0)
    channel = box(W / 2 - p["channel_w"] / 2, board_y0 + board_h - 1,
                  W / 2 + p["channel_w"] / 2, hold_y0 + 1)

    cx = board_x0 + board_w / 2 + p["win_dx"]
    cy = board_y0 + board_h / 2 + p["win_dy"]
    window = rounded_rect(cx - p["win_w"] / 2, cy - p["win_h"] / 2,
                          cx + p["win_w"] / 2, cy + p["win_h"] / 2, p["win_r"])

    # Magnets: two beside the board at the top, two below the holder.
    m_in = p["wall"] + mag_hole / 2
    mag_top_y = board_y0 + mag_hole / 2 + 1.0
    magnets = [(m_in, mag_top_y), (W - m_in, mag_top_y),
               (m_in, mag_row_y), (W - m_in, mag_row_y)]
    pins = [(W / 2 - 20, mag_row_y), (W / 2 + 20, mag_row_y)] if p["pins"] else []

    outer = rounded_rect(0, 0, W, H, p["corner_r"])

    # ---- layers ----
    n_cavity = math.ceil((p["holder_h"] + 0.3) / t)   # layers the holder passes through
    n_cavity = max(n_cavity, 1 + math.ceil((p["back_parts"] + 0.5) / t))
    cavity = unary_union([board_pocket, holder, channel])

    def mag_holes():
        return [Point(x, y).buffer(mag_hole / 2 - k2, quad_segs=32) for x, y in magnets]

    def pin_holes():
        return [Point(x, y).buffer(p["pin_d"] / 2 - k2, quad_segs=16) for x, y in pins]

    def part(holes):
        """Outline grown by kerf/2, holes shrunk by kerf/2."""
        o = outer.buffer(k2, quad_segs=16) if k2 else outer
        cut = unary_union([h.buffer(-k2) if k2 else h for h in holes])
        return o.difference(cut)

    layers = []
    layers.append(("front", "Front plate: window", part([window])))
    layers.append(("board", "Board and holder pockets", part([board_pocket, holder])))
    for i in range(n_cavity - 1):
        last = i == n_cavity - 2
        holes = [cavity]
        if last:
            holes += mag_holes() + pin_holes()
        layers.append((f"ring{i + 1}", "Frame ring" + (": frame magnets, pins" if last else ""),
                       part(holes)))
    layers.append(("mount", "Mount plate: fridge magnets, pins", part(mag_holes() + pin_holes())))

    info = {
        "W": W, "H": H, "D": len(layers) * t, "layers": len(layers),
        "cavity_depth": n_cavity * t, "magnets": len(magnets) * 2,
        "board_x0": board_x0, "board_y0": board_y0, "hold_x0": hold_x0, "hold_y0": hold_y0,
        "window": window.bounds,
        "hidden": [board_pocket, holder] + [Point(x, y).buffer(mag_hole / 2) for x, y in magnets],
    }
    checks = []
    if p["board_stack"] > t + 1e-6:
        checks.append(f"board stack {p['board_stack']} mm is thicker than one layer ({t} mm)")
    wall_mag = min(min(x, W - x) for x, _ in magnets) - mag_hole / 2
    if wall_mag < 1.5:
        checks.append(f"only {wall_mag:.1f} mm of wood outside the magnets")
    # clearance between magnets / pins and the cavity in the ring layers
    for x, y in magnets + pins:
        d = cavity.distance(Point(x, y)) - (mag_hole if (x, y) in magnets else p["pin_d"]) / 2
        if d < 1.0:
            checks.append(f"hole at ({x:.1f}, {y:.1f}) is only {d:.1f} mm from the cavity")
    if abs(p["mag_t"] - t) > 0.25:
        checks.append(f"magnets are {p['mag_t']} mm thick but layers are {t} mm: "
                      "they won't sit flush in the mount plate")
    if n_cavity * t < p["holder_h"] + 0.3:
        checks.append("cavity is shallower than the holder")
    return layers, info, checks


# ---- output -------------------------------------------------------------------

def poly_paths(geom):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    for poly in polys:
        yield list(poly.exterior.coords)
        for ring in poly.interiors:
            yield list(ring.coords)


def svg_path(coords, ox=0.0, oy=0.0):
    pts = " L ".join(f"{x + ox:.3f},{y + oy:.3f}" for x, y in coords)
    return f"M {pts} Z"


def write_svg(path, items, w, h):
    """items: list of (geometry, offset_x, offset_y, label)."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
           f'viewBox="0 0 {w:.3f} {h:.3f}">']
    for geom, ox, oy, label in items:
        d = " ".join(svg_path(c, ox, oy) for c in poly_paths(geom))
        out.append(f'<path d="{d}" fill="none" stroke="#ff0000" stroke-width="0.1" '
                   f'fill-rule="evenodd"><title>{label}</title></path>')
    out.append("</svg>")
    path.write_text("\n".join(out))


def write_dxf(path, geom):
    import ezdxf
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for coords in poly_paths(geom):
        # DXF is y-up: flip so the part isn't mirrored
        msp.add_lwpolyline([(x, -y) for x, y in coords], close=True)
    doc.saveas(path)


def write_preview(path, layers, info, t):
    """Front view + exploded side view, rendered to PNG."""
    import cairosvg
    W, H = info["W"], info["H"]
    s = 4.0
    pad = 30
    n = len(layers)
    gap = 6
    ex_w = n * t + (n - 1) * gap
    cw = pad * 3 + W * s + ex_w * s + 120
    ch = pad * 2 + H * s + 40
    wood = ["#e6cfa6", "#dcc195", "#d6b98a", "#d2b484", "#cdae7c", "#c9a976", "#c4a370",
            "#c09e6a", "#b89564", "#b08c5c"]
    el = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{cw}" height="{ch}" '
          f'viewBox="0 0 {cw} {ch}"><rect width="100%" height="100%" fill="#ffffff"/>']
    # Front view: all layers stacked, front plate on top
    ox, oy = pad, pad
    for i in reversed(range(n)):
        d = " ".join(svg_path([(x * s, y * s) for x, y in c], ox, oy)
                     for c in poly_paths(layers[i][2]))
        el.append(f'<path d="{d}" fill="{wood[i % len(wood)]}" stroke="#8a6a42" '
                  f'stroke-width="0.8" fill-rule="evenodd"/>')
    wx0, wy0, wx1, wy1 = info["window"]
    el.append(f'<rect x="{ox + wx0 * s:.1f}" y="{oy + wy0 * s:.1f}" width="{(wx1 - wx0) * s:.1f}" '
              f'height="{(wy1 - wy0) * s:.1f}" fill="#ecebe4" stroke="#333" stroke-width="1"/>')
    for g in info["hidden"]:
        d = " ".join(svg_path([(x * s, y * s) for x, y in c], ox, oy) for c in poly_paths(g))
        el.append(f'<path d="{d}" fill="none" stroke="#6b4a1f" stroke-width="1" '
                  f'stroke-dasharray="5 4"/>')
    el.append(f'<text x="{ox + W * s / 2:.1f}" y="{oy + H * s + 26}" font-family="sans-serif" '
              f'font-size="16" text-anchor="middle" fill="#333">{W:.1f} x {H:.1f} x {info["D"]:.1f} mm, '
              f'{n} layers</text>')
    # Exploded side view
    sx = pad * 2 + W * s
    for i in range(n):
        x = sx + i * (t + gap) * s
        el.append(f'<rect x="{x:.1f}" y="{oy}" width="{t * s:.1f}" height="{H * s:.1f}" '
                  f'fill="{wood[i % len(wood)]}" stroke="#8a6a42" stroke-width="0.8"/>')
        el.append(f'<text x="{x + t * s / 2:.1f}" y="{oy - 8}" font-family="sans-serif" '
                  f'font-size="13" text-anchor="middle" fill="#333">{i + 1}</text>')
    el.append(f'<text x="{sx}" y="{oy + H * s + 26}" font-family="sans-serif" font-size="14" '
              f'fill="#333">front  &#8594;  back (mount plate)</text>')
    el.append("</svg>")
    cairosvg.svg2png(bytestring="\n".join(el).encode(), write_to=str(path))


def main():
    p = parse_overrides(dict(PARAMS))
    layers, info, checks = build(p)
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    for f in out.glob("*"):
        if f.suffix in (".svg", ".dxf", ".png"):
            f.unlink()

    W, H = info["W"], info["H"]
    items = []
    cols = 3
    for i, (name, label, geom) in enumerate(layers, 1):
        stem = f"layer_{i:02d}_{name}"
        write_svg(out / f"{stem}.svg", [(geom, 1, 1, label)], W + 2, H + 2)
        write_dxf(out / f"{stem}.dxf", geom)
        r, c = divmod(i - 1, cols)
        items.append((geom, 5 + c * (W + 5), 5 + r * (H + 5), f"{i}: {label}"))
    rows = math.ceil(len(layers) / cols)
    write_svg(out / "sheet_all_layers.svg", items, 5 + cols * (W + 5), 5 + rows * (H + 5))
    write_preview(out / "preview.png", layers, info, p["ply"])

    print(f"Case: {W:.1f} x {H:.1f} x {info['D']:.1f} mm, {info['layers']} layers of {p['ply']} mm")
    for i, (name, label, _) in enumerate(layers, 1):
        print(f"  {i:2d}  {label}")
    print(f"Magnets: {info['magnets']} x D{p['mag_d']:g} x {p['mag_t']:g} mm")
    print("Checks: " + ("all fine" if not checks else ""))
    for c in checks:
        print("  WARNING: " + c)


if __name__ == "__main__":
    main()
