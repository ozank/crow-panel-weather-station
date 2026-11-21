#!/usr/bin/env python3
"""G-code for part A of case v2, for GRBL (gSender) on a CNC Proxxon MF70.

    python3 gcode_v2.py                    # writes out/gcode/*.nc
    python3 gcode_v2.py feed=200 step=0.4  # slower

Writes three files, run in this order:
  A1_front_window.nc    front face up, 3.175 mm flat end mill
  A2_front_chamfer.nc   front face up, 90-degree V-bit (re-zero Z after the tool change)
  A3_back_pocket.nc     back face up (blank flipped left-to-right), 3.175 mm flat end mill

Work zero for every file: X0 Y0 = lower-left corner of the face that is up,
Z0 = top of that face. The MF70 spindle isn't under GRBL control, so each file
pauses (M0) before cutting: start the spindle, then press Resume in gSender.

Pockets are cleared with offset rings, cut clockwise (conventional milling, which
is kinder to leadscrew backlash), with a ramp into each depth level instead of a plunge.
"""

import math
import sys
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import case_v2 as C

CAM = {
    "feed": 250.0,          # mm/min, cutting
    "plunge": 60.0,         # mm/min, ramps and straight Z moves into wood
    "step": 0.5,            # mm per depth level (flat end mill)
    "stepover": 0.45,       # fraction of the tool diameter between rings
    "ramp_len": 8.0,        # mm of travel per ramp
    "safe_z": 3.0,          # mm above the work for rapids
    "chamfer_step": 0.5,    # mm per pass for the V-bit
    "chamfer_feed": 200.0,
    "through_extra": 0.2,   # mm below the bottom of the blank for through-cuts
    "tab_h": 1.0,           # holding tabs left at the bottom of through-cuts, 0 = none
    "tab_len": 3.0,         # tab length along the cut
    "tabs": 4,
    "drill_peck": 1.0,      # mm per peck for drilled holes
    "drill_feed": 40.0,
}


def parse(cam, p):
    for arg in sys.argv[1:]:
        k, _, v = arg.partition("=")
        if k in cam:
            cam[k] = float(v)
        elif k in p:
            p[k] = float(v)
        else:
            sys.exit(f"unknown parameter: {k}")


def rings_of(geom):
    polys = [] if geom.is_empty else ([geom] if geom.geom_type == "Polygon" else list(geom.geoms))
    out = []
    for pg in polys:
        pg = orient(pg, sign=-1.0)                 # exterior clockwise
        out.append(list(pg.exterior.coords))
        for r in pg.interiors:
            out.append(list(r.coords))
    return out


def pocket_rings(pocket, r, stepover):
    """Offset rings from the outside in; returns list of levels (outer first)."""
    levels = []
    k = 0
    while True:
        g = pocket.buffer(-(r + k * stepover), quad_segs=16)
        if g.is_empty or g.area < 1e-4:
            break
        g = g.simplify(0.01)
        # drop scraps that GEOS sometimes leaves after a negative buffer, and any ring
        # that isn't really clear of the wall
        off = r + k * stepover
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        keep = []
        for pg in polys:
            if pg.area < 0.01:
                continue
            dmin = min(pocket.boundary.distance(Point(c)) for c in pg.exterior.coords)
            if dmin < off - 0.02:
                continue
            keep.append(pg)
        if not keep:
            break
        levels.append(rings_of(unary_union(keep)))
        k += 1
    return levels


class G:
    def __init__(self, cam):
        self.cam = cam
        self.lines = []
        self.z = None

    def emit(self, s):
        self.lines.append(s)

    def rapid_to(self, x, y):
        self.emit(f"G0 Z{self.cam['safe_z']:.3f}")
        self.emit(f"G0 X{x:.3f} Y{y:.3f}")
        self.z = self.cam["safe_z"]

    def down_to(self, z):
        self.emit(f"G0 Z{z + 0.5:.3f}")
        self.emit(f"G1 Z{z:.3f} F{self.cam['plunge']:.0f}")
        self.z = z

    def ring(self, pts, z, feed, ramp_from=None):
        """Cut one closed ring at depth z, starting and ending at pts[0].
        With ramp_from, first descend from that depth while travelling along the ring."""
        loop = LineString(pts)
        per = loop.length
        start = 0.0
        if ramp_from is not None and ramp_from > z + 1e-9:
            ramp = self.cam["ramp_len"]
            for d, (x, y) in walk(pts, 0.0, ramp):
                zz = ramp_from - (ramp_from - z) * d / ramp
                self.emit(f"G1 X{x:.3f} Y{y:.3f} Z{zz:.3f} F{self.cam['plunge'] * 2:.0f}")
            start = ramp % per
        else:
            self.emit(f"G1 Z{z:.3f} F{self.cam['plunge']:.0f}")
        # one full lap at depth from where we are
        for _, (x, y) in walk(pts, start, per):
            self.emit(f"G1 X{x:.3f} Y{y:.3f} F{feed:.0f}")
        self.z = z
        self.pos = walk(pts, start, per)[-1][1]


def walk(pts, s0, dist):
    """Points along a closed ring from arc length s0 for a length dist (wrapping),
    as (distance travelled, point). Includes the interpolated end point."""
    segs = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L > 1e-9:
            segs.append((x0, y0, x1, y1, L))
    per = sum(sg[4] for sg in segs)
    s0 %= per
    out = []
    # find the segment containing s0
    acc, i = 0.0, 0
    while acc + segs[i][4] < s0 - 1e-12:
        acc += segs[i][4]
        i += 1
    off = s0 - acc
    travelled = 0.0
    while travelled < dist - 1e-9:
        x0, y0, x1, y1, L = segs[i % len(segs)]
        remain = L - off
        if travelled + remain >= dist - 1e-9:
            f = (off + dist - travelled) / L
            out.append((dist, (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)))
            break
        travelled += remain
        out.append((travelled, (x1, y1)))
        off = 0.0
        i += 1
    return out


def rotate_to_nearest(pts, xy):
    ring = pts[:-1]
    k = min(range(len(ring)), key=lambda i: math.hypot(ring[i][0] - xy[0], ring[i][1] - xy[1]))
    ring = ring[k:] + ring[:k]
    return ring + [ring[0]]


def header(g, title, tool, note):
    g.emit(f"( {title} )")
    g.emit(f"( Tool: {tool} )")
    for line in note:
        g.emit(f"( {line} )")
    g.emit("G21 G90 G17 G94")
    g.emit(f"G0 Z{g.cam['safe_z'] + 7:.3f}")
    g.emit("M3 S10000")
    g.emit("M0 (Start the spindle, then press Resume)")


def footer(g):
    g.emit(f"G0 Z{g.cam['safe_z'] + 7:.3f}")
    g.emit("G0 X0 Y0")
    g.emit("M5")
    g.emit("M2")


def pocket_program(g, pocket, depth, r, cam, tool_d):
    levels = pocket_rings(pocket, r, cam["stepover"] * tool_d)
    if not levels:
        sys.exit("pocket too small for the tool")
    n_steps = math.ceil(depth / cam["step"] - 1e-9)
    for s in range(1, n_steps + 1):
        z = -min(depth, s * cam["step"])
        z_prev = -min(depth, (s - 1) * cam["step"])
        # inside out: ramp in at the middle, finish each level on the wall
        for li, rings in enumerate(reversed(levels)):
            for ri, pts in enumerate(rings):
                if li == 0 and ri == 0:
                    g.rapid_to(*pts[0])
                    g.down_to(z_prev)
                    g.ring(pts, z, cam["feed"], ramp_from=z_prev)
                else:
                    # next ring surrounds the last one: step across at depth to its nearest point
                    pts = rotate_to_nearest(pts, g.pos)
                    g.emit(f"G1 X{pts[0][0]:.3f} Y{pts[0][1]:.3f} F{cam['feed']:.0f}")
                    g.ring(pts, z, cam["feed"])
    return levels


def densify(pts, step=0.5):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(1, math.ceil(L / step))
        for i in range(1, n + 1):
            out.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n))
    return out


def tab_centres(pts, n_tabs):
    """Arc-length positions of the midpoints of the n longest straight segments."""
    segs, acc = [], 0.0
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        segs.append((L, acc + L / 2))
        acc += L
    segs.sort(reverse=True)
    return sorted(c for _, c in segs[:n_tabs]), acc


def profile_program(g, shape, depth, r, cam, tab_h, n_tabs):
    """Through-cut along the inside of shape (tool fully inside), clockwise,
    ramping into each level; tabs of height tab_h are left at the bottom."""
    path = shape.buffer(-r, quad_segs=16).simplify(0.01)
    rings = rings_of(path)
    if len(rings) != 1:
        sys.exit("profile path is not a single ring")
    pts = rings[0]
    centres, per = tab_centres(pts, n_tabs) if tab_h > 0 and n_tabs else ([], 0)
    half = cam["tab_len"] / 2 + r          # tab length is measured at the wood
    tab_floor = -(depth - cam["through_extra"]) + tab_h if centres else None
    # start the ring away from any tab: at the vertex furthest from all tab centres
    dense = densify(pts, 0.4)
    # arc length of each dense point
    sl = [0.0]
    for (x0, y0), (x1, y1) in zip(dense[:-1], dense[1:]):
        sl.append(sl[-1] + math.hypot(x1 - x0, y1 - y0))
    per = sl[-1]

    def in_tab(s):
        s %= per
        return any(min(abs(s - c), per - abs(s - c)) <= half for c in centres)

    n_steps = math.ceil(depth / cam["step"] - 1e-9)
    g.rapid_to(*dense[0])
    g.down_to(0.0)
    z_prev = 0.0
    ramp = cam["ramp_len"]
    m = len(dense) - 1           # dense[0] == dense[m]
    j = 0                        # index of the current point, keeps counting across levels
    cur_z = 0.0
    for k in range(1, n_steps + 1):
        z = -min(depth, k * cam["step"])
        # ramp down over `ramp` mm from where we are, then one full lap at depth
        lap = [(dense[j % m][0], dense[j % m][1], cur_z)]
        travelled = 0.0
        while travelled < ramp + per - 1e-9:
            a_pt = dense[j % m]
            j += 1
            b_pt = dense[j % m]
            travelled += math.hypot(b_pt[0] - a_pt[0], b_pt[1] - a_pt[1])
            zz = z_prev - (z_prev - z) * min(1.0, travelled / ramp)
            if tab_floor is not None and zz < tab_floor and in_tab(sl[j % m]):
                zz = tab_floor
            lap.append((b_pt[0], b_pt[1], zz))
        keep = [lap[0]]
        for p0, p1, p2 in zip(lap[:-2], lap[1:-1], lap[2:]):
            cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
            if abs(cross) < 1e-6 and abs(p0[2] - p1[2]) < 1e-6 and abs(p1[2] - p2[2]) < 1e-6:
                continue
            keep.append(p1)
        keep.append(lap[-1])
        prev_z = cur_z
        for x, y, zz in keep[1:]:
            f = cam["plunge"] * 2 if zz < prev_z - 1e-6 else cam["feed"]
            g.emit(f"G1 X{x:.3f} Y{y:.3f} Z{zz:.3f} F{f:.0f}")
            prev_z = zz
        cur_z = keep[-1][2]
        z_prev = z
    return pts, tab_floor, centres, per


def drill_program(g, holes, depth, cam):
    """Peck-drill each hole (GRBL has no canned cycles, so the pecks are written out)."""
    for x, y in holes:
        g.rapid_to(x, y)
        g.emit("G0 Z0.500")
        z = 0.0
        while z > -depth + 1e-9:
            z = max(-depth, z - cam["drill_peck"])
            g.emit(f"G1 Z{z:.3f} F{cam['drill_feed']:.0f}")
            g.emit("G0 Z0.500")
            if z > -depth + 1e-9:
                g.emit(f"G0 Z{z + 0.3:.3f}")
        g.emit(f"G0 Z{cam['safe_z']:.3f}")


def main():
    cam = dict(CAM)
    p = dict(C.PARAMS)
    parse(cam, p)
    faces, slabs, info, checks = C.build(p)
    if checks:
        print("case_v2 checks failed:", *checks, sep="\n  ")
    out = Path(__file__).parent / "out" / "gcode"
    out.mkdir(parents=True, exist_ok=True)
    tool_d = p["tool_d"]
    r = tool_d / 2

    front = next(f for f in faces if f["part"] == "A" and f["face"] == "front")
    back = next(f for f in faces if f["part"] == "A" and f["face"] == "back")
    ops_f = {name: (C.to_face(geom, info, front["flip"]), depth) for name, geom, depth, _ in front["ops"]}
    ops_b = {name: (C.to_face(geom, info, back["flip"]), depth) for name, geom, depth, _ in back["ops"]}

    W, H = info["W"], info["H"]
    blank = f"blank {W:.1f} x {H:.1f} x {p['stock_a']:g} mm"
    report = []
    ring_report = []

    # ---- A1: window ----
    win, wd = ops_f["WINDOW"]
    g = G(cam)
    header(g, "Case v2 part A, op 1: window", f"{tool_d:g} mm flat end mill",
           [blank, "FRONT face up", "X0 Y0 = lower-left corner, Z0 = top face",
            f"depth {wd:.2f} mm in {cam['step']:g} mm steps"])
    lv = pocket_program(g, win, wd, r, cam, tool_d)
    footer(g)
    (out / "A1_front_window.nc").write_text("\n".join(g.lines) + "\n")
    report.append(("A1_front_window.nc", win, wd, lv, g))

    # ---- A2: chamfer with the V-bit tip on the window line ----
    ch, cd = ops_f.get("CHAMFER", (None, 0))
    if ch is not None and cd > 0:
        g = G(cam)
        header(g, "Case v2 part A, op 2: window chamfer", "90 degree V-bit",
               [blank, "FRONT face up, same XY zero as op 1", "After the tool change: re-zero Z on the top face",
                f"tip follows the window edge, {cd:g} mm deep"])
        pts = rings_of(ch.simplify(0.01))[0]
        n = math.ceil(cd / cam["chamfer_step"] - 1e-9)
        g.rapid_to(*pts[0])
        g.down_to(0.0)
        for s in range(1, n + 1):
            z = -min(cd, s * cam["chamfer_step"])
            g.emit(f"G1 Z{z:.3f} F{cam['plunge']:.0f}")
            for x, y in pts[1:]:
                g.emit(f"G1 X{x:.3f} Y{y:.3f} F{cam['chamfer_feed']:.0f}")
        footer(g)
        (out / "A2_front_chamfer.nc").write_text("\n".join(g.lines) + "\n")

    # ---- A3: board pocket from the back ----
    bp, bd = ops_b["BOARD_POCKET"]
    g = G(cam)
    header(g, "Case v2 part A, op 3: board pocket", f"{tool_d:g} mm flat end mill",
           [blank, "BACK face up: flip the blank LEFT-TO-RIGHT, top edge stays at the top",
            "X0 Y0 = lower-left corner of the back face, Z0 = top face",
            f"depth {bd:.2f} mm in {cam['step']:g} mm steps; breaks into the window"])
    lv = pocket_program(g, bp, bd, r, cam, tool_d)
    footer(g)
    (out / "A3_back_pocket.nc").write_text("\n".join(g.lines) + "\n")
    report.append(("A3_back_pocket.nc", bp, bd, lv, g))

    # ---- rings: B1 (cavity), B2 (magnets, pins, cavity) ----
    tb = p["stock_b"]
    rblank = f"blank {W:.1f} x {H:.1f} x {tb:g} mm"
    setup = ["BACK face up (the pencil arrow is underneath)",
             "X0 Y0 = lower-left corner, Z0 = top face",
             "Tape the blank to a flat backer board: the cut goes "
             f"{cam['through_extra']:g} mm into it"]
    ring_faces = [f for f in faces if f["part"].startswith("B")]
    for f in ring_faces:
        ops = {name: (C.to_face(geom, info, f["flip"]), depth) for name, geom, depth, _ in f["ops"]}
        part = f["part"]
        files = []
        if "MAGNET" in ops:
            mg, md = ops["MAGNET"]
            g = G(cam)
            header(g, f"Case v2 part {part}: magnet pockets", f"{tool_d:g} mm flat end mill",
                   [rblank] + setup[:2] + [f"4 pockets, {md:.2f} mm deep; run this before the cavity"])
            for one in getattr(mg, "geoms", [mg]):   # one pocket at a time, never across wood
                pocket_program(g, one, md, r, cam, tool_d)
            footer(g)
            files.append((f"{part}_1_magnets.nc", g))
        if "PIN" in ops:
            pg, pd = ops["PIN"]
            holes = [(c.centroid.x, c.centroid.y) for c in getattr(pg, "geoms", [pg])]
            g = G(cam)
            header(g, f"Case v2 part {part}: dowel pin holes", f"{p['pin_d']:g} mm drill bit",
                   [rblank] + setup[:2] + ["Same XY zero as the magnets; re-zero Z after the tool change",
                                           f"{len(holes)} holes, {pd:g} mm deep, pecked"])
            drill_program(g, holes, pd, cam)
            footer(g)
            files.append((f"{part}_2_pins.nc", g))
        cg, _ = ops["CAVITY"]
        depth = tb + cam["through_extra"]
        g = G(cam)
        header(g, f"Case v2 part {part}: cavity, cut through", f"{tool_d:g} mm flat end mill, 11+ mm flute",
               [rblank] + setup +
               ([f"{int(cam['tabs'])} tabs, {cam['tab_h']:g} mm high, hold the middle piece: "
                 "cut them with a knife afterwards"] if cam["tab_h"] > 0 else []))
        prof = profile_program(g, cg, depth, r, cam, cam["tab_h"], int(cam["tabs"]))
        footer(g)
        n = len(files) + 1
        files.append((f"{part}_{n}_cavity.nc" if len(files) else f"{part}_cavity.nc", g))
        for name, gg in files:
            (out / name).write_text("\n".join(gg.lines) + "\n")
        ring_report.append((part, files, ops, prof, depth))

    # ---- verify: area swept by the tool vs the pocket ----
    for name, pocket, depth, levels, gg in report:
        lines = [LineString(pts) for rings in levels for pts in rings]
        swept = unary_union([ln.buffer(r, quad_segs=16) for ln in lines])
        missed = pocket.buffer(-0.05).difference(swept).area
        over = swept.difference(pocket.buffer(0.05)).area
        xs, ys = [], []
        for ln in gg.lines:
            for tok in ln.split():
                if tok[0] == "X":
                    xs.append(float(tok[1:]))
                elif tok[0] == "Y":
                    ys.append(float(tok[1:]))
        t = sum(LineString(pts).length for rings in levels for pts in rings) * \
            math.ceil(depth / cam["step"] - 1e-9) / cam["feed"]
        print(f"{name}: {len(gg.lines)} lines, X {min(xs):.1f}..{max(xs):.1f}, "
              f"Y {min(ys):.1f}..{max(ys):.1f}, missed {missed:.3f} mm2, "
              f"overcut {over:.3f} mm2, ~{t:.0f} min")


if __name__ == "__main__":
    main()
