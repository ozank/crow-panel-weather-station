#!/usr/bin/env python3
"""Renders of case v2 (Blender / Cycles, headless). Geometry comes from case_v2.py.

    pip install bpy shapely
    python3 render_v2.py              # out/render_fridge.png and out/render_exploded.png
    python3 render_v2.py preview      # quick low-quality test

screen_texture.png is shared with v1 (../screen_texture.png).
"""

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import case_v2 as C  # noqa: E402

QUICK = "preview" in sys.argv
S = 0.001  # mm -> m
TEXTURE = HERE.parent / "screen_texture.png"


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes, m.node_tree.links, m.node_tree.nodes["Principled BSDF"]


def wood(name, seed, dark=False):
    """Oiled hardwood (beech or walnut): long grain along x, a little darker on end grain."""
    m, N, L, bsdf = new_mat(name)
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (14, 420, 420)
    mp.inputs["Location"].default_value = (seed * 3.1, seed * 1.7, seed * 0.9)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    grain = N.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 1.0
    grain.inputs["Detail"].default_value = 9
    grain.inputs["Roughness"].default_value = 0.6
    grain.inputs["Distortion"].default_value = 0.5
    L.new(mp.outputs["Vector"], grain.inputs["Vector"])
    ramp = N.new("ShaderNodeValToRGB")
    if dark:
        lo, hi = (0.16, 0.09, 0.05, 1), (0.30, 0.18, 0.10, 1)
    else:
        lo, hi = (0.36, 0.20, 0.09, 1), (0.56, 0.34, 0.16, 1)
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = lo
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = hi
    L.new(grain.outputs["Fac"], ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.42
    bsdf.inputs["Coat Weight"].default_value = 0.15
    bsdf.inputs["Coat Roughness"].default_value = 0.3
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.05
    bump.inputs["Distance"].default_value = 0.0002
    L.new(grain.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def plain(name, color, rough=0.5, metal=0.0, coat=0.0):
    m, N, L, bsdf = new_mat(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Coat Weight"].default_value = coat
    return m


def slab(name, geom, z0, z1, mat, D, dy=0.0, bevel=0.3):
    """Extrude a shapely polygon between depths z0..z1 (mm from the front face).
    Blender axes: x right, z up, -y toward the viewer; the fridge is at y = 0."""
    t = z1 - z0
    bevel = min(bevel, t / 2 - 0.05)
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = t * S / 2 - bevel * S
    cu.bevel_depth = bevel * S
    cu.bevel_resolution = 2
    for coords in C.poly_rings(geom):
        pts = coords[:-1]
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = (x * S, y * S, 0, 1)
        sp.use_cyclic_u = True
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = (math.pi / 2, 0, 0)
    ob.location = (0, ((z0 + z1) / 2 - D) * S - dy * S, 0)
    return ob


def cube(name, x0, x1, y0, y1, z0, z1, mat, D, dy=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = ((x1 - x0) * S, (z1 - z0) * S, (y1 - y0) * S)
    ob.location = ((x0 + x1) / 2 * S, ((z0 + z1) / 2 - D) * S - dy * S, (y0 + y1) / 2 * S)
    ob.data.materials.append(mat)
    return ob


def cylinder_x(name, x0, x1, cy, cz_mm, r, mat, D, dy=0.0):
    bpy.ops.mesh.primitive_cylinder_add(radius=r * S, depth=(x1 - x0) * S, vertices=48)
    ob = bpy.context.active_object
    ob.name = name
    ob.rotation_euler = (0, math.pi / 2, 0)
    ob.location = ((x0 + x1) / 2 * S, (cz_mm - D) * S - dy * S, cy * S)
    bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat)
    return ob


def screen_mat():
    m, N, L, bsdf = new_mat("epaper")
    tex = N.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(TEXTURE))
    tex.interpolation = "Closest"
    L.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    bsdf.inputs["Coat Weight"].default_value = 0.35
    bsdf.inputs["Coat Roughness"].default_value = 0.12
    return m


def build_scene(exploded):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    p = dict(C.PARAMS)
    faces, slabs, info, _ = C.build(p)
    W, H, D = info["W"], info["H"], info["D"]

    # gaps between parts in the exploded view (toward the viewer = larger dy)
    order = ["A"] + [f"B{i + 1}" for i in range(info["n_rings"])] + ["P"]
    seq = ["A", "board", "holder"] + order[1:]   # front to back
    gap = {name: 0.0 for name in seq}
    if exploded:
        for i, name in enumerate(seq):
            gap[name] = (len(seq) - 1 - i) * 32.0
    mats = {name: wood(f"wood_{name}", i * 1.37) for i, name in enumerate(order)}
    mats["P"] = wood("ply_P", 4.2)

    for i, (part, z0, z1, geom) in enumerate(slabs):
        slab(f"{part}_{i}", geom, z0, z1, mats[part], D, dy=gap[part], bevel=0.25)

    # board: PCB + screen glass behind the window
    bw, bh = p["pcb_w"], p["pcb_h"]
    za = p["skin"]
    board_gap = gap["board"]
    pcb = plain("pcb", (0.02, 0.10, 0.05), 0.4)
    glass = plain("glass", (0.85, 0.85, 0.83), 0.3, coat=0.4)
    cube("pcb", -bw / 2, bw / 2, -bh / 2, bh / 2, za + 1.4, za + 2.8, pcb, D, board_gap)
    cube("panel", -bw / 2 + 2, bw / 2 - 2, -bh / 2 + 1, bh / 2 - 1, za, za + 1.4, glass, D,
         board_gap)
    bpy.ops.mesh.primitive_plane_add(size=1)
    scr = bpy.context.active_object
    scr.scale = (60 * S, 30 * S, 1)
    scr.rotation_euler = (math.pi / 2, 0, 0)
    scr.location = (0, (za - 0.02 - D) * S - board_gap * S, 0)
    scr.data.materials.append(screen_mat())

    # 18650 holder resting on the back face of part A
    zh = p["stock_a"]
    hgap = gap["holder"]
    hl, hw, hh = p["holder_l"], p["holder_w"], p["holder_h"]
    black = plain("holder", (0.02, 0.02, 0.02), 0.55)
    cube("holder_base", -hl / 2, hl / 2, -hw / 2, hw / 2, zh, zh + 2.0, black, D, hgap)
    cube("holder_end_l", -hl / 2, -hl / 2 + 3.5, -hw / 2, hw / 2, zh, zh + hh, black, D, hgap)
    cube("holder_end_r", hl / 2 - 3.5, hl / 2, -hw / 2, hw / 2, zh, zh + hh, black, D, hgap)
    cell = plain("cell", (0.05, 0.25, 0.55), 0.3, coat=0.6)
    cylinder_x("cell", -32.5, 32.5, 0, zh + 2.0 + 9.3, 9.25, cell, D, hgap)

    # magnets (nickel) in B2's back and in the plate
    nickel = plain("nickel", (0.75, 0.75, 0.75), 0.25, metal=1.0)
    last = f"B{info['n_rings']}"
    zb = p["stock_a"] + info["cavity_h"]
    for (x, y) in info["magnets"]:
        for z0, z1, part in ((zb - p["mag_t"], zb, last), (zb, zb + p["mag_t"], "P")):
            bpy.ops.mesh.primitive_cylinder_add(radius=p["mag_d"] / 2 * S,
                                                depth=(z1 - z0 - 0.1) * S, vertices=48)
            ob = bpy.context.active_object
            ob.rotation_euler = (math.pi / 2, 0, 0)
            ob.location = (x * S, ((z0 + z1) / 2 - D) * S - gap[part] * S, y * S)
            ob.data.materials.append(nickel)

    # fridge door (assembled view only)
    if not exploded:
        bpy.ops.mesh.primitive_plane_add(size=1)
        fr = bpy.context.active_object
        fr.scale = (0.9, 0.9, 1)
        fr.rotation_euler = (math.pi / 2, 0, 0)
        fr.location = (0, 0.0001, 0)
        m, N, L, bsdf = new_mat("fridge")
        bsdf.inputs["Base Color"].default_value = (0.82, 0.82, 0.81, 1)
        bsdf.inputs["Roughness"].default_value = 0.22
        bsdf.inputs["Coat Weight"].default_value = 0.5
        nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 900
        bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.03
        L.new(nz.outputs["Fac"], bump.inputs["Height"])
        L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        fr.data.materials.append(m)

    target = bpy.data.objects.new("target", None)
    scene.collection.objects.link(target)
    span = sum(gap.values()) / max(1, len(gap))
    target.location = (0, (-D / 2 - (80 if exploded else 0)) * S, 0)

    def area(name, loc, size, energy, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.size, ld.energy, ld.color = size, energy, color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = loc
        tr = ob.constraints.new("TRACK_TO")
        tr.target = target
        tr.track_axis = "TRACK_NEGATIVE_Z"
        tr.up_axis = "UP_Y"

    area("key", (-0.30, -0.45, 0.42), 0.35, 9, (1.0, 0.96, 0.9))
    area("fill", (0.45, -0.35, 0.05), 0.5, 3.0, (0.9, 0.95, 1.0))
    area("rim", (0.05, 0.25, 0.40), 0.3, 3.0)
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.55, 0.56, 0.58, 1) if not exploded else (0.9, 0.9, 0.9, 1)
    bg.inputs["Strength"].default_value = 0.12 if not exploded else 0.6

    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = 85
    cam = bpy.data.objects.new("cam", cam_d)
    scene.collection.objects.link(cam)
    if exploded:
        cam.location = (-0.52, 0.40, 0.34)     # from the back-left, above
    else:
        cam_d.dof.use_dof = True
        cam_d.dof.focus_object = target
        cam_d.dof.aperture_fstop = 11.0
        cam.location = (0.17, -0.36, 0.11)
    tr = cam.constraints.new("TRACK_TO")
    tr.target = target
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16 if QUICK else 128
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 800 if QUICK else 1600
    scene.render.resolution_y = 600 if QUICK else 1200
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    return scene


def main():
    for exploded, name in ((False, "render_fridge"), (True, "render_exploded")):
        scene = build_scene(exploded)
        out = HERE / "out" / (name + ("_preview" if QUICK else "") + ".png")
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("wrote", out)


if __name__ == "__main__":
    main()
