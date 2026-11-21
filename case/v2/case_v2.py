#!/usr/bin/env python3
"""Case v2 for the CrowPanel 2.13" e-paper weather station: compact, milled at home.

v2 puts the 18650 holder directly behind the board, so the case is about half the
front area of v1. The body is three blanks of wood (solid hardwood or plywood),
cut square on the table router or saw and pocketed on a small CNC mill (Proxxon MF70).
A thin mount plate stays on the fridge; the body clips onto it with magnets, as in v1.

    python3 case_v2.py                 # writes out/
    python3 case_v2.py stock_a=9.5     # with your measurements

Parts, front to back:
  A   front      window and board pocket (milled from both faces)
  B1  ring       through-cut cavity for the battery holder
  B2  ring       same cavity, plus magnet and pin pockets on its back face
  P   mount      thin plate on the fridge, magnets and pins pass through

All sizes are in millimetres. Each CNC drawing is drawn as seen from the face that
is UP on the mill, with the origin at that face's lower-left corner of the blank.
"""

import math
import sys
from pathlib import Path

from shapely.affinity import scale as shp_scale
from shapely.affinity import translate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

PARAMS = {
    # Wood
    "stock_a": 10.2,        # front blank thickness (measure it)
    "skin": 1.5,            # wood left in front of the screen
    "stock_b": 10.0,        # ring blank thickness; enough rings are added to fit the holder
    "plate_t": 3.0,         # mount plate (3 mm plywood); should equal the magnet thickness

    # Mill
    "tool_d": 3.175,        # end mill for pockets (1/8"); sets dog-bone and corner sizes
    "mill_y_travel": 46.0,  # MF70 Y travel; used only for a warning

    # Board (bare, without the acrylic shell) - from Elecrow's Eagle files
    "pcb_w": 63.2,
    "pcb_h": 31.2,
    "pcb_fit": 0.3,
    "board_stack": 2.8,     # PCB + e-paper glass
    "back_parts": 4.0,      # tallest part on the back of the board
    "edge_relief": 2.5,     # dial and side buttons on the left edge
    "edge_relief_len": 26.0,

    # Visible screen area (2.13" panel, 48.55 x 23.71 active)
    "win_w": 50.5,
    "win_h": 25.7,
    "win_dx": 0.0,          # window offset from the board centre (+ = right, seen from front)
    "win_dy": 0.0,          # (+ = up)
    "win_chamfer": 1.0,     # 90-degree V-bit chamfer around the window, 0 = none

    # 18650 holder (single-cell, open type), lies behind the board
    "holder_l": 77.0,
    "holder_w": 21.0,
    "holder_h": 19.0,
    "holder_fit": 0.5,
    "holder_dy": 0.0,       # holder offset from the board centre (+ = up)
    "head_room": 0.8,       # gap above the holder for a felt pad

    # Magnets (neodymium discs)
    "mag_d": 8.0,
    "mag_t": 3.0,
    "mag_fit": 0.2,
    "mag_wall": 1.2,        # wood between a magnet and the cavity
    "edge_wall": 2.0,       # wood between a magnet and the outside

    # Alignment pins (3 mm dowel), 1 = on
    "pins": 1,
    "pin_d": 3.0,
    "pin_depth": 4.0,       # blind hole in B2

    # Registration for part A: the blank is left long, two dowel holes outside the part
    # let you flip it onto pins in the spoilboard, so op 2 lines up with op 1 exactly.
    "reg_pins": 0,
    "reg_d": 3.0,           # dowel diameter (drill this size)
    "reg_off": 8.0,         # dowel centre beyond the end of the part
    "reg_margin": 6.0,      # wood beyond the dowel

    # Body
    "wall_min": 4.0,        # outer wall around the holder
    "corner_r": 4.0,
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


def dogbone(poly, r, axis=None):
    """Add a dog-bone at every sharp convex corner so a round tool clears it fully.
    axis="y" makes T-bones that poke out only in y (the x extent stays the same)."""
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    extras = []
    for pg in polys:
        ring = pg.exterior
        pts = list(ring.coords)[:-1]
        ccw = ring.is_ccw
        n = len(pts)
        for i in range(n):
            ax, ay = pts[i - 1]
            bx, by = pts[i]
            cx, cy = pts[(i + 1) % n]
            v1 = (bx - ax, by - ay)
            v2 = (cx - bx, cy - by)
            l1, l2 = math.hypot(*v1), math.hypot(*v2)
            if l1 < 1e-6 or l2 < 1e-6:
                continue
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            convex = cross > 0 if ccw else cross < 0
            turn = math.degrees(math.asin(max(-1, min(1, abs(cross) / (l1 * l2)))))
            if not convex or turn < 30:
                continue
            # bisector pointing into the polygon
            u1 = (-v1[0] / l1, -v1[1] / l1)
            u2 = (v2[0] / l2, v2[1] / l2)
            ux, uy = u1[0] + u2[0], u1[1] + u2[1]
            ul = math.hypot(ux, uy)
            # A tool of radius r centred at c = corner + u*r just touches the corner.
            # Adding the disc around c to the pocket lets the tool get there.
            if axis == "y":
                c = (bx + math.copysign(r, ux), by)
            elif axis == "x":
                c = (bx, by + math.copysign(r, uy))
            else:
                c = (bx + ux / ul * r, by + uy / ul * r)
            extras.append(Point(c).buffer(r + 0.05, quad_segs=24))
    if not extras:
        return poly
    return unary_union([poly] + extras)


def build(p):
    r_tool = p["tool_d"] / 2

    # ---- footprint, front view, origin at the case centre, y up ----
    bw = p["pcb_w"] + 2 * p["pcb_fit"]
    bh = p["pcb_h"] + 2 * p["pcb_fit"]
    rel = p["edge_relief"]
    # board (and so the window) centred on the case; the relief sticks out on the left
    bx0 = -bw / 2
    board = box(bx0, -bh / 2, bx0 + bw, bh / 2)
    relief = box(bx0 - rel, -p["edge_relief_len"] / 2, bx0 + 0.01, p["edge_relief_len"] / 2)
    board_pocket = unary_union([board, relief])

    hl = p["holder_l"] + 2 * p["holder_fit"]
    hw = p["holder_w"] + 2 * p["holder_fit"]
    holder = box(-hl / 2, p["holder_dy"] - hw / 2, hl / 2, p["holder_dy"] + hw / 2)

    wcx = bx0 + bw / 2 + p["win_dx"]
    wcy = p["win_dy"]
    win_r = max(r_tool + 0.05, 1.0)
    window = rounded_rect(wcx - p["win_w"] / 2, wcy - p["win_h"] / 2,
                          wcx + p["win_w"] / 2, wcy + p["win_h"] / 2, win_r)

    # cavity through the rings: the board must pass through to be removable
    cavity = unary_union([board_pocket, holder])
    bp_cnc = dogbone(board_pocket, r_tool, axis="y")
    # holder corners: T-bones along the holder's length, so the case doesn't get taller
    hy0, hy1 = p["holder_dy"] - hw / 2, p["holder_dy"] + hw / 2
    tbones = [Point(sx * hl / 2, y).buffer(r_tool + 0.05, quad_segs=24)
              for sx in (-1, 1) for y in (hy0 + r_tool, hy1 - r_tool)]
    cav_cnc = unary_union([bp_cnc, holder] + tbones)

    # ---- magnets in the four corners, outside the cavity ----
    mr = (p["mag_d"] + p["mag_fit"]) / 2
    # search magnet positions for the smallest front face
    def size_for(mx, my):
        W = 2 * max(mx + mr + p["edge_wall"], hl / 2 + p["wall_min"],
                    bw / 2 + rel + p["wall_min"])
        H = 2 * max(my + mr + p["edge_wall"], bh / 2 + r_tool + p["wall_min"])
        return math.ceil(W * 2) / 2, math.ceil(H * 2) / 2   # round up to 0.5 mm

    best = None
    mx = bw / 2 + p["mag_wall"] + mr
    while mx < hl / 2 + p["mag_wall"] + mr + 8:
        my = abs(p["holder_dy"]) + hw / 2 + p["mag_wall"] + mr
        for _ in range(400):
            pts = [(sx * mx, sy * my) for sx in (-1, 1) for sy in (-1, 1)]
            if min(cav_cnc.distance(Point(x, y)) - mr for x, y in pts) >= p["mag_wall"] - 1e-6:
                break
            my += 0.05
        W, H = size_for(mx, my)
        if best is None or W * H < best[0] - 1e-6:
            best = (W * H, mx, my, W, H)
        mx += 0.1
    _, mx, my, W, H = best
    magnets = [(sx * mx, sy * my) for sx in (-1, 1) for sy in (-1, 1)]
    outer = rounded_rect(-W / 2, -H / 2, W / 2, H / 2, p["corner_r"])

    # pins: above and below the board, diagonally opposite
    pins = []
    if p["pins"]:
        py = (bh / 2 + H / 2) / 2
        pins = [(-W / 4, py), (W / 4, -py)]
    pr = p["pin_d"] / 2

    n_rings = math.ceil((p["holder_h"] + p["head_room"]) / p["stock_b"])
    pocket_a = p["stock_a"] - p["skin"]

    mag_c = [Point(x, y).buffer(mr, quad_segs=32) for x, y in magnets]
    pin_c = [Point(x, y).buffer(pr, quad_segs=24) for x, y in pins]

    # ---- CNC operations per face. depth None = through ----
    # each op: (name, geometry in front-view coords, depth, tool note)
    faces = []
    reg = None
    reg_ops = []
    if p["reg_pins"]:
        rx = W / 2 + p["reg_off"]
        bl = rx + p["reg_margin"]
        reg = box(-bl, -H / 2, bl, H / 2)          # the long blank
        reg_holes = unary_union([Point(sx * rx, 0).buffer(p["reg_d"] / 2, quad_segs=24)
                                 for sx in (-1, 1)])
        reg_ops = [("REG_PIN", reg_holes, p["stock_a"] + 5,
                    f"drill {p['reg_d']:g} through the blank and 5 mm into the spoilboard")]
    faces.append({
        "part": "A", "face": "front", "flip": False, "blank": reg,
        "title": "A front: window (op 1)",
        "ops": reg_ops + [("WINDOW", window, p["skin"] + 0.4, f"end mill {p['tool_d']:g}")]
               + ([("CHAMFER", window, p["win_chamfer"], "90 deg V-bit, follow line")]
                  if p["win_chamfer"] > 0 else []),
    })
    faces.append({
        "part": "A", "face": "back", "flip": True, "blank": reg,
        "title": "A back: board pocket (op 2, flip onto pins)",
        "ops": [(n, g, d, "already drilled: sits on the dowels, don't cut") for n, g, d, _ in reg_ops] + [("BOARD_POCKET", bp_cnc, pocket_a, f"end mill {p['tool_d']:g}")],
    })
    for i in range(n_rings):
        last = i == n_rings - 1
        ops = [("CAVITY", cav_cnc, None, f"end mill {p['tool_d']:g}, through")]
        if last:
            ops += [("MAGNET", unary_union(mag_c), p["mag_t"] + 0.1, "end mill, or drill press + 8 mm Forstner")]
            if pins:
                ops += [("PIN", unary_union(pin_c), p["pin_depth"], "drill")]
        faces.append({
            "part": f"B{i + 1}", "face": "back", "flip": True,
            "title": f"B{i + 1} ring" + (": magnets, pins on back face" if last else ""),
            "ops": ops,
        })
    faces.append({
        "part": "P", "face": "front", "flip": False,
        "title": "P mount plate (3 mm ply)",
        "ops": [("MAGNET", unary_union(mag_c), None, "through"),
                ("PIN", unary_union(pin_c), None, "through, glue dowels")] if pins else
               [("MAGNET", unary_union(mag_c), None, "through")],
    })

    # ---- solid model as stacked slabs (front face at z=0, going back = +z) ----
    slabs = []   # (part, z0, z1, polygon)
    z = 0.0
    slabs.append(("A", 0, p["skin"], outer.difference(window)))
    slabs.append(("A", p["skin"], p["stock_a"], outer.difference(board_pocket)))
    z = p["stock_a"]
    for i in range(n_rings):
        last = i == n_rings - 1
        name = f"B{i + 1}"
        if last:
            z_mag = z + p["stock_b"] - p["mag_t"]
            slabs.append((name, z, z_mag, outer.difference(cavity)))
            slabs.append((name, z_mag, z + p["stock_b"],
                          outer.difference(unary_union([cavity] + mag_c + pin_c))))
        else:
            slabs.append((name, z, z + p["stock_b"], outer.difference(cavity)))
        z += p["stock_b"]
    slabs.append(("P", z, z + p["plate_t"], outer.difference(unary_union(mag_c + pin_c))))
    D = z + p["plate_t"]

    info = dict(W=W, H=H, D=D, n_rings=n_rings, pocket_a=pocket_a, outer=outer,
                window=window, board_pocket=board_pocket, holder=holder, cavity=cavity,
                magnets=magnets, pins=pins, mr=mr, z_rings=p["stock_a"],
                cavity_h=n_rings * p["stock_b"])

    # ---- checks ----
    c = []
    need_a = p["board_stack"] + p["back_parts"] + 0.3
    if pocket_a < need_a:
        c.append(f"board pocket is {pocket_a:.1f} mm deep, needs {need_a:.1f}: use thicker stock_a")
    if n_rings * p["stock_b"] < p["holder_h"] + 0.3:
        c.append("ring cavity is shallower than the holder")
    ends = holder.difference(board_pocket)
    ends_list = [ends] if ends.geom_type == "Polygon" else list(ends.geoms)
    shoulder = min((g.bounds[2] - g.bounds[0]) for g in ends_list) if ends_list else 0
    info["shoulder"] = shoulder
    if shoulder < 3:
        c.append(f"holder ends rest on only {shoulder:.1f} mm of the front part")
    for x, y in magnets:
        d = cav_cnc.distance(Point(x, y)) - mr
        e = min(W / 2 - abs(x), H / 2 - abs(y)) - mr
        if d < p["mag_wall"] - 0.01:
            c.append(f"magnet at ({x:.1f},{y:.1f}) only {d:.1f} mm from the cavity")
        if e < 1.5:
            c.append(f"magnet at ({x:.1f},{y:.1f}) only {e:.1f} mm from the edge")
    for x, y in pins:
        d = cav_cnc.distance(Point(x, y)) - pr
        if d < 1.0:
            c.append(f"pin at ({x:.1f},{y:.1f}) only {d:.1f} mm from the cavity")
    if abs(p["mag_t"] - p["plate_t"]) > 0.25:
        c.append(f"magnets {p['mag_t']} mm vs plate {p['plate_t']} mm: they won't sit flush")
    if p["mag_t"] + 0.1 > p["stock_b"] - 1.5:
        c.append("magnet pocket leaves less than 1.5 mm of wood in the last ring")
    win_in_pocket = board.contains(window)
    if not win_in_pocket:
        c.append("window runs outside the board pocket")
    # mill travel: span of tool-centre paths in Y for pockets
    span = (cav_cnc.bounds[3] - cav_cnc.bounds[1]) - p["tool_d"]
    for x, y in magnets:
        span = max(span, 2 * abs(y) + 2 * mr - p["tool_d"])
    info["y_span"] = span
    if span > p["mill_y_travel"]:
        c.append(f"pockets need {span:.1f} mm of Y travel, mill has {p['mill_y_travel']:.0f}: "
                 "turn the blank 90 degrees or re-clamp")
    return faces, slabs, info, c


# ---- output ---------------------------------------------------------------------

def poly_rings(geom):
    if geom.is_empty:
        return
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    for pg in polys:
        yield list(pg.exterior.coords)
        for ring in pg.interiors:
            yield list(ring.coords)


def to_face(geom, info, flip, centre=False):
    """Front-view coords (centre origin, y up) -> face coords (y up).
    Origin at the blank's lower-left corner, or at the part centre if centre=True.
    flip=True mirrors left-right: the face seen from the back."""
    g = shp_scale(geom, xfact=-1 if flip else 1, yfact=1, origin=(0, 0))
    if centre:
        return g
    return translate(g, info["W"] / 2, info["H"] / 2)


DEPTH_COLOURS = ["#1f6feb", "#d97706", "#16a34a", "#9333ea", "#dc2626", "#0891b2"]


def write_face(out, face, info, p):
    stem = f"{face['part']}_{face['face']}"
    flip = face["flip"]
    blank = face.get("blank")
    centre = blank is not None
    outer = to_face(info["outer"], info, flip, centre)
    stock = to_face(blank, info, flip, centre) if centre else outer

    # DXF: one layer per operation, named with its depth
    import ezdxf
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    doc.layers.add("OUTLINE_REFERENCE", color=8)
    for coords in poly_rings(stock):
        msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": "OUTLINE_REFERENCE"})
    if centre:
        doc.layers.add("PART_OUTLINE_CUT_LATER", color=9)
        for coords in poly_rings(outer):
            msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": "PART_OUTLINE_CUT_LATER"})
    for i, (name, geom, depth, note) in enumerate(face["ops"]):
        dtxt = "THRU" if depth is None else f"{depth:.1f}MM"
        layer = f"{name}_{dtxt}".replace(".", "_")
        doc.layers.add(layer, color=i + 1)
        for coords in poly_rings(to_face(geom, info, flip, centre)):
            msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": layer})
    doc.saveas(out / f"{stem}.dxf")

    # SVG drawing with legend
    x0, y0, x1, y1 = stock.bounds
    W, H = x1 - x0, y1 - y0
    m = 6
    leg_h = 7 * (len(face["ops"]) + 2) + 6
    sw, sh = max(W + 2 * m, 140), H + 2 * m + leg_h
    el = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw:.2f}mm" height="{sh:.2f}mm" '
          f'viewBox="0 0 {sw:.3f} {sh:.3f}"><rect width="100%" height="100%" fill="#fff"/>']

    def path(g):
        # SVG is y-down: flip y
        return " ".join("M " + " L ".join(f"{x - x0 + m:.3f},{y1 - y + m:.3f}" for x, y in r)
                        + " Z" for r in poly_rings(g))

    if centre:
        el.append(f'<path d="{path(stock)}" fill="#f6efe0" stroke="#999" stroke-width="0.25"/>')
        el.append(f'<path d="{path(outer)}" fill="#efe2c8" stroke="#555" stroke-width="0.25" '
                  f'stroke-dasharray="2 1"/>')
    else:
        el.append(f'<path d="{path(outer)}" fill="#efe2c8" stroke="#555" stroke-width="0.25"/>')
    for i, (name, geom, depth, note) in enumerate(face["ops"]):
        col = DEPTH_COLOURS[i % len(DEPTH_COLOURS)]
        fill = "none" if name == "CHAMFER" else col
        dash = ' stroke-dasharray="1 0.6"' if name == "CHAMFER" else ""
        el.append(f'<path d="{path(to_face(geom, info, flip, centre))}" fill="{fill}" fill-opacity="0.35" '
                  f'stroke="{col}" stroke-width="0.3" fill-rule="evenodd"{dash}/>')
    # origin marker
    ox, oy = -x0 + m, y1 + m
    el.append(f'<circle cx="{ox}" cy="{oy}" r="1.2" fill="none" stroke="#000" stroke-width="0.3"/>'
              f'<text x="{ox + 1.8}" y="{oy + 3.5}" font-size="2.6" font-family="sans-serif">0,0</text>')
    y = H + 2 * m + 2
    pw, ph = info["W"], info["H"]
    size = (f"blank {W:.1f} x {H:.1f} mm, part {pw:.1f} x {ph:.1f} mm (dashed), origin at part centre"
            if centre else f"{pw:.1f} x {ph:.1f} mm")
    el.append(f'<text x="{m}" y="{y + 2}" font-size="3.2" font-family="sans-serif" font-weight="bold">'
              f'{face["title"]} - seen from the {face["face"]}</text>')
    y += 6
    el.append(f'<text x="{m}" y="{y + 2}" font-size="3" font-family="sans-serif">{size}</text>')
    for i, (name, geom, depth, note) in enumerate(face["ops"]):
        y += 7
        col = DEPTH_COLOURS[i % len(DEPTH_COLOURS)]
        dtxt = "through" if depth is None else f"{depth:.1f} mm deep"
        el.append(f'<rect x="{m}" y="{y - 3}" width="4" height="4" fill="{col}" fill-opacity="0.5" '
                  f'stroke="{col}" stroke-width="0.3"/>'
                  f'<text x="{m + 6}" y="{y}" font-size="3" font-family="sans-serif">'
                  f'{name.replace("_", " ").lower()}: {dtxt} ({note})</text>')
    el.append("</svg>")
    (out / f"{stem}.svg").write_text("\n".join(el))
    import cairosvg
    cairosvg.svg2png(url=str(out / f"{stem}.svg"), write_to=str(out / f"{stem}.png"), dpi=300)
    return stem


def write_stl(out, slabs, info):
    import trimesh
    parts = {}
    for part, z0, z1, poly in slabs:
        polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        for pg in polys:
            m = trimesh.creation.extrude_polygon(pg, z1 - z0)
            m.apply_translation((0, 0, z0))
            parts.setdefault(part, []).append(m)
    meshes = {}
    for part, ms in parts.items():
        m = trimesh.util.concatenate(ms)
        # flip z so the front faces +z in viewers
        m.apply_transform(trimesh.transformations.scale_matrix(-1, direction=(0, 0, 1)))
        m.invert()
        m.export(out / f"part_{part}.stl")
        meshes[part] = m
    trimesh.util.concatenate(list(meshes.values())).export(out / "assembly.stl")
    return meshes


def main():
    p = parse_overrides(dict(PARAMS))
    faces, slabs, info, checks = build(p)
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    for f in out.glob("*"):
        if f.suffix in (".svg", ".dxf", ".stl") or (f.suffix == ".png" and "render" not in f.name):
            f.unlink()
    stems = [write_face(out, f, info, p) for f in faces]
    write_stl(out, slabs, info)

    print(f"Case v2: {info['W']:.1f} x {info['H']:.1f} x {info['D']:.1f} mm "
          f"(front {p['stock_a']:g} + {info['n_rings']} x {p['stock_b']:g} rings + "
          f"{p['plate_t']:g} plate)")
    print(f"  board pocket {info['pocket_a']:.1f} mm, cavity {info['cavity_h']:.1f} mm, "
          f"holder rests on {info['shoulder']:.1f} mm shoulders")
    print(f"  pockets need {info['y_span']:.1f} mm of Y travel")
    print("  files: " + ", ".join(stems))
    print("Checks: " + ("all fine" if not checks else ""))
    for c in checks:
        print("  WARNING: " + c)
    return faces, slabs, info


if __name__ == "__main__":
    main()
