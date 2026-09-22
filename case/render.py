#!/usr/bin/env python3
"""Photo-style render of the case on a fridge door (Blender / Cycles, headless).

    pip install bpy shapely          # bpy is Blender as a Python module
    python3 render.py                # writes out/render.png
    python3 render.py preview        # quick low-quality test

Geometry comes straight from case.py, so the render always matches the cut files.
"""

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import case as C  # noqa: E402

QUICK = "preview" in sys.argv
S = 0.001  # mm -> m


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes, m.node_tree.links, m.node_tree.nodes["Principled BSDF"]


def plywood(name, tone):
    """Birch face veneer with long soft grain; laser-burnt brown on cut edges."""
    m, N, L, bsdf = new_mat(name)
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (18, 650, 60)  # grain runs along x
    mp.inputs["Location"].default_value = (tone * 3.1, tone * 1.7, 0)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    grain = N.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 1.0
    grain.inputs["Detail"].default_value = 8
    grain.inputs["Roughness"].default_value = 0.6
    grain.inputs["Distortion"].default_value = 0.35
    L.new(mp.outputs["Vector"], grain.inputs["Vector"])
    ramp = N.new("ShaderNodeValToRGB")
    lo = (0.60 - 0.03 * tone, 0.46 - 0.03 * tone, 0.27 - 0.02 * tone, 1)
    hi = (0.76 - 0.02 * tone, 0.62 - 0.02 * tone, 0.40 - 0.02 * tone, 1)
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = lo
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = hi
    L.new(grain.outputs["Fac"], ramp.inputs["Fac"])

    # Edge mask from the world normal: faces not looking along Y are cut edges.
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], sep.inputs["Vector"])
    ab = N.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"
    L.new(sep.outputs["Y"], ab.inputs[0])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.35
    mr.inputs["From Max"].default_value = 0.8
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    L.new(ab.outputs["Value"], mr.inputs["Value"])

    burn_noise = N.new("ShaderNodeTexNoise")
    burn_noise.inputs["Scale"].default_value = 900
    L.new(tc.outputs["Object"], burn_noise.inputs["Vector"])
    burn = N.new("ShaderNodeValToRGB")
    burn.color_ramp.elements[0].color = (0.10, 0.055, 0.03, 1)
    burn.color_ramp.elements[1].color = (0.22, 0.13, 0.07, 1)
    L.new(burn_noise.outputs["Fac"], burn.inputs["Fac"])

    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"
    # ShaderNodeMix has float/vector/colour sockets with the same names; pick the colour ones.
    L.new(mr.outputs["Result"], mix.inputs[0])
    L.new(ramp.outputs["Color"], mix.inputs[6])
    L.new(burn.outputs["Color"], mix.inputs[7])
    L.new(mix.outputs[2], bsdf.inputs["Base Color"])

    rough = N.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.55
    rough.inputs["To Max"].default_value = 0.8
    L.new(mr.outputs["Result"], rough.inputs["Value"])
    L.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    bump.inputs["Distance"].default_value = 0.0002
    L.new(grain.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def layer_object(name, geom, y_center, t, mat, H):
    bevel = 0.25 * S
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = t * S / 2 - bevel
    cu.bevel_depth = bevel
    cu.bevel_resolution = 2
    for coords in C.poly_paths(geom):
        pts = coords[:-1]
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = (x * S, (H - y) * S, 0, 1)
        sp.use_cyclic_u = True
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = (math.pi / 2, 0, 0)
    ob.location = (0, y_center, 0)
    return ob


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    p = dict(C.PARAMS)
    layers, info, _ = C.build(p)
    t, W, H, n = p["ply"], info["W"], info["H"], len(layers)

    # ---- case: layer 1 at the front (-y), mount plate against the fridge (y = 0)
    for i, (name, _, geom) in enumerate(layers, 1):
        gap = 0.02 if i < n else 0.08  # glue line; the mount plate is a separate part
        yc = -((n - i) + 0.5) * t * S - (0 if i == n else gap * S)
        layer_object(f"L{i}_{name}", geom, yc, t - gap, plywood(f"ply{i}", (i * 7) % 5 / 4), H)

    # ---- e-paper panel behind the window
    wx0, wy0, wx1, wy1 = info["window"]
    cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
    bpy.ops.mesh.primitive_plane_add(size=1)
    scr = bpy.context.active_object
    scr.scale = (60 * S, 30 * S, 1)
    scr.rotation_euler = (math.pi / 2, 0, 0)
    scr.location = (cx * S, -(n - 1) * t * S + 0.05 * S, (H - cy) * S)
    m, N, L, bsdf = new_mat("epaper")
    tex = N.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(HERE / "screen_texture.png"))
    tex.interpolation = "Closest"
    L.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    bsdf.inputs["Coat Weight"].default_value = 0.35
    bsdf.inputs["Coat Roughness"].default_value = 0.12
    scr.data.materials.append(m)

    # ---- fridge door: white painted steel with a faint orange-peel texture
    bpy.ops.mesh.primitive_plane_add(size=1)
    fr = bpy.context.active_object
    fr.scale = (0.9, 0.9, 1)
    fr.rotation_euler = (math.pi / 2, 0, 0)
    fr.location = (W / 2 * S, 0.0001, H / 2 * S)
    m, N, L, bsdf = new_mat("fridge")
    bsdf.inputs["Base Color"].default_value = (0.82, 0.82, 0.81, 1)
    bsdf.inputs["Roughness"].default_value = 0.22
    bsdf.inputs["Coat Weight"].default_value = 0.5
    bsdf.inputs["Coat Roughness"].default_value = 0.08
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 900
    bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.03
    L.new(nz.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    fr.data.materials.append(m)

    # ---- lights and world
    def area(name, loc, size, energy, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.size = size
        ld.energy = energy
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = loc
        tr = ob.constraints.new("TRACK_TO")
        tr.target = target
        tr.track_axis = "TRACK_NEGATIVE_Z"
        tr.up_axis = "UP_Y"

    target = bpy.data.objects.new("target", None)
    scene.collection.objects.link(target)
    target.location = (W / 2 * S, -0.012, H / 2 * S)

    area("key", (-0.30, -0.45, 0.42), 0.35, 9, (1.0, 0.96, 0.9))
    area("fill", (0.45, -0.35, 0.05), 0.5, 2.5, (0.9, 0.95, 1.0))
    area("rim", (0.05, -0.05, 0.40), 0.2, 1.2)
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.56, 0.58, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.12

    # ---- camera: three-quarter view with shallow depth of field
    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = 85
    cam_d.dof.use_dof = True
    cam_d.dof.focus_object = target
    cam_d.dof.aperture_fstop = 11.0
    cam = bpy.data.objects.new("cam", cam_d)
    scene.collection.objects.link(cam)
    cam.location = (W / 2 * S + 0.19, -0.38, H / 2 * S + 0.13)
    tr = cam.constraints.new("TRACK_TO")
    tr.target = target
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"
    scene.camera = cam

    # ---- render
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16 if QUICK else 160
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 800 if QUICK else 1600
    scene.render.resolution_y = 600 if QUICK else 1200
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    out = HERE / "out" / ("render_preview.png" if QUICK else "render.png")
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
