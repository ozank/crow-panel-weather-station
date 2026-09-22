#!/usr/bin/env python3
"""Lifestyle render: the case on a white fridge in a warm, sunlit kitchen.

    pip install bpy shapely
    python3 render_scene.py            # writes out/render_kitchen.png (1500 x 1000)
    python3 render_scene.py preview    # quick low-quality test
"""

import math
import sys
from pathlib import Path

import bpy
import bmesh  # available once bpy is imported

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import case as C  # noqa: E402
import render as R  # noqa: E402  (plywood material and layer builder)

QUICK = "preview" in sys.argv
S = 0.001


# ---- helpers ----------------------------------------------------------------------

def mat(name, color, rough=0.5, metal=0.0, coat=0.0, emission=None, strength=0.0):
    m, N, L, b = R.new_mat(name)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def image_mat(name, path, rough=0.7):
    m, N, L, b = R.new_mat(name)
    t = N.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(str(path))
    L.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    return m


def link(name, bm, material, bevel=0.0, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for poly in me.polygons:
            poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(material)
    if bevel:
        mod = ob.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 4
        mod.harden_normals = True
        for poly in me.polygons:
            poly.use_smooth = True
    return ob


def box(name, x0, x1, y0, y1, z0, z1, material, bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(x1 - x0, y1 - y0, z1 - z0), verts=bm.verts)
    bmesh.ops.translate(bm, vec=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), verts=bm.verts)
    return link(name, bm, material, bevel)


def cylinder(name, loc, r, h, material, axis="Z", r2=None, segments=64):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=r,
                          radius2=r if r2 is None else r2, depth=h)
    ob = link(name, bm, material, smooth=True)
    if axis == "Y":
        ob.rotation_euler = (math.pi / 2, 0, 0)
    ob.location = loc
    return ob


def blob(name, loc, scale, rot, material):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.0)
    ob = link(name, bm, material, smooth=True)
    ob.scale, ob.rotation_euler, ob.location = scale, rot, loc
    return ob


def card(name, loc, w, h, rot_y, material):
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (w, h, 1)
    ob.rotation_euler = (math.pi / 2, rot_y, 0)
    ob.location = loc
    ob.data.materials.append(material)
    return ob


# ---- scene ------------------------------------------------------------------------

def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    p = dict(C.PARAMS)
    layers, info, _ = C.build(p)
    t, W, H, n = p["ply"], info["W"], info["H"], len(layers)

    # Weather station (same geometry as the cut files), fridge door at y = 0
    for i, (name, _, geom) in enumerate(layers, 1):
        gap = 0.02 if i < n else 0.08
        yc = -((n - i) + 0.5) * t * S - (0 if i == n else gap * S)
        R.layer_object(f"L{i}_{name}", geom, yc, t - gap, R.plywood(f"ply{i}", (i * 7) % 5 / 4), H)
    wx0, wy0, wx1, wy1 = info["window"]
    cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
    epaper = image_mat("epaper", HERE / "screen_texture.png", rough=0.45)
    epaper.node_tree.nodes["Image Texture"].interpolation = "Closest"
    epaper.node_tree.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.35
    card("screen", (cx * S, -(n - 1) * t * S + 0.05 * S, (H - cy) * S), 60 * S, 30 * S, 0, epaper)

    # Fridge: white painted steel, chrome handle on the left edge
    fridge_white = mat("fridge", (0.86, 0.86, 0.85), rough=0.25, coat=0.6)
    box("fridge", -0.40, 0.20, 0.0, 0.66, -1.40, 0.42, fridge_white, bevel=0.035)
    dark = mat("gap", (0.02, 0.02, 0.02), rough=0.8)
    box("door_gap", -0.39, 0.19, -0.001, 0.004, -0.33, -0.326, dark)
    chrome = mat("chrome", (0.92, 0.92, 0.92), rough=0.12, metal=1.0)
    cylinder("handle", (-0.375, -0.045, 0.06), 0.011, 0.46, chrome)
    for z in (-0.16, 0.28):
        cylinder("standoff", (-0.375, -0.022, z), 0.008, 0.046, chrome, axis="Y")

    # Things already on the fridge: a child's drawing and a sticky note
    card("drawing", (-0.19, -0.0015, 0.10), 0.10, 0.133, math.radians(-4),
         image_mat("drawing", HERE / "tex_drawing.png"))
    cylinder("magnet_red", (-0.19, -0.006, 0.16), 0.011, 0.008, mat("red", (0.62, 0.08, 0.06), 0.35, coat=0.8), axis="Y")
    card("note", (-0.17, -0.0015, -0.08), 0.076, 0.076, math.radians(5),
         image_mat("note", HERE / "tex_note.png"))
    cylinder("magnet_blue", (-0.17, -0.006, -0.046), 0.009, 0.008, mat("blue", (0.08, 0.22, 0.45), 0.35, coat=0.8), axis="Y")

    # Kitchen: warm plaster wall with a sunny window, sage cabinets, oak worktop
    plaster = mat("wall", (0.72, 0.62, 0.50), rough=0.9)
    box("wall", -2.5, 3.0, 0.70, 0.72, -1.40, 1.2, plaster)
    box("floor", -2.5, 3.0, -2.0, 0.72, -1.42, -1.40, mat("floor", (0.35, 0.22, 0.13), 0.5))
    sage = mat("sage", (0.26, 0.34, 0.27), rough=0.45, coat=0.3)
    box("cabinet", 0.22, 2.0, 0.08, 0.70, -1.38, -0.50, sage, bevel=0.006)
    oak = R.plywood("oak", 1.0)
    oak.node_tree.nodes["Mapping"].inputs["Scale"].default_value = (4, 60, 60)
    box("worktop", 0.215, 2.05, 0.04, 0.70, -0.50, -0.46, oak, bevel=0.004)
    glow = mat("window", (1, 1, 1), emission=(1.0, 0.93, 0.80), strength=2.2)
    box("window", 0.95, 1.80, 0.695, 0.70, -0.30, 0.55, glow)
    white = mat("frame", (0.90, 0.88, 0.84), rough=0.5)
    for x in (0.95, 1.375, 1.80):
        box("mullion", x - 0.02, x + 0.02, 0.66, 0.695, -0.30, 0.55, white)
    for z in (-0.30, 0.125, 0.55):
        box("transom", 0.93, 1.82, 0.66, 0.695, z - 0.02, z + 0.02, white)
    box("sill", 0.89, 1.86, 0.60, 0.70, -0.33, -0.30, white, bevel=0.004)

    # Worktop details, soft in the background
    terracotta = mat("terracotta", (0.55, 0.26, 0.15), rough=0.8)
    cylinder("pot", (0.50, 0.45, -0.40), 0.065, 0.12, terracotta, r2=0.08)
    leaf = mat("leaf", (0.10, 0.28, 0.08), rough=0.55)
    for i in range(9):
        a = i / 9 * 2 * math.pi
        blob(f"leaf{i}", (0.50 + 0.05 * math.cos(a), 0.45 + 0.05 * math.sin(a), -0.28 + 0.03 * (i % 3)),
             (0.022, 0.06, 0.012), (0.6 * math.sin(a), 0.6 * math.cos(a), a), leaf)
    mug = mat("mug", (0.88, 0.84, 0.76), rough=0.25, coat=0.8)
    cylinder("mug", (0.33, 0.25, -0.415), 0.04, 0.09, mug)
    board = R.plywood("board", 0.5)
    box("board", 0.58, 0.83, 0.63, 0.66, -0.46, -0.10, board, bevel=0.01)
    jar = mat("jar", (0.35, 0.25, 0.15), rough=0.4, coat=0.5)
    cylinder("jar", (0.72, 0.52, -0.37), 0.05, 0.18, jar)

    # Open shelf with a few jars and a trailing plant
    shelf_wood = R.plywood("shelf", 0.8)
    shelf_wood.node_tree.nodes["Mapping"].inputs["Scale"].default_value = (4, 60, 60)
    box("shelf", 0.30, 0.90, 0.50, 0.70, 0.08, 0.105, shelf_wood, bevel=0.003)
    glass = mat("amber", (0.55, 0.32, 0.12), rough=0.3, coat=0.8)
    cylinder("jar2", (0.42, 0.60, 0.165), 0.04, 0.12, glass)
    cylinder("jar3", (0.52, 0.61, 0.145), 0.035, 0.08, mat("cream_jar", (0.85, 0.80, 0.70), 0.4, coat=0.6))
    cylinder("pot2", (0.74, 0.60, 0.15), 0.05, 0.09, terracotta, r2=0.058)
    for i in range(7):
        a = i / 7 * 2 * math.pi
        blob(f"trail{i}", (0.74 + 0.05 * math.cos(a), 0.56 + 0.02 * math.sin(a), 0.14 - 0.03 * (i % 4)),
             (0.02, 0.05, 0.012), (0.9 * math.sin(a), 0.4, a), leaf)

    # Warm late-afternoon sun from the front left, soft fill, warm ambient
    sun_d = bpy.data.lights.new("sun", "SUN")
    sun_d.energy = 3.2
    sun_d.angle = math.radians(4)
    sun_d.color = (1.0, 0.80, 0.58)
    sun = bpy.data.objects.new("sun", sun_d)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(58), math.radians(-38), math.radians(-28))
    fill_d = bpy.data.lights.new("fill", "AREA")
    fill_d.size = 0.8
    fill_d.energy = 25
    fill_d.color = (1.0, 0.9, 0.8)
    fill = bpy.data.objects.new("fill", fill_d)
    scene.collection.objects.link(fill)
    fill.location = (0.1, -1.2, 0.3)
    fill.rotation_euler = (math.radians(90), 0, 0)
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.55, 0.45, 0.35, 1)
    bg.inputs["Strength"].default_value = 0.25

    # Camera: slightly to the left, eye level, background falls out of focus
    target = bpy.data.objects.new("target", None)
    scene.collection.objects.link(target)
    target.location = (W / 2 * S + 0.012, -0.024, H / 2 * S + 0.008)
    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = 50
    cam_d.dof.use_dof = True
    cam_d.dof.focus_object = target
    cam_d.dof.aperture_fstop = 4.0
    cam = bpy.data.objects.new("cam", cam_d)
    scene.collection.objects.link(cam)
    cam.location = (target.location.x - 0.13, -0.30, target.location.z + 0.025)
    tr = cam.constraints.new("TRACK_TO")
    tr.target = target
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24 if QUICK else 160
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900 if QUICK else 1500
    scene.render.resolution_y = 600 if QUICK else 1000
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    out = HERE / "out" / ("render_kitchen_preview.png" if QUICK else "render_kitchen.png")
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
