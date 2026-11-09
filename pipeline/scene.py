"""Blender script: builds one shot (set + characters + camera) and renders it.

Run:  blender -b --factory-startup -P scene.py -- shot.json

The shot JSON is written by make_video.py. Characters are blocky
"avatar game" style figures with drawn faces; sets are built from boxes.
Everything is procedural so every video looks consistent.
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Euler, Quaternion, Vector

ARGS = json.load(open(sys.argv[sys.argv.index("--") + 1]))
TEX = ARGS["tex"]
FPS = ARGS.get("fps", 24)
NF = ARGS["frames"]
RND = random.Random(ARGS.get("seed", 1))
CHAR_SCALE = 0.36  # local character units -> meters

# ----------------------------------------------------------------- helpers

_mats = {}


def hexcol(c):
    if isinstance(c, (list, tuple)):
        return tuple(c[:3])
    c = c.lstrip("#")
    srgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    # convert sRGB -> linear for Blender
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in srgb)


def mat(color, rough=0.55, emit=0.0, metal=0.0, name=None):
    key = (str(color), rough, emit, metal)
    if key in _mats:
        return _mats[key]
    m = bpy.data.materials.new(name or f"m{len(_mats)}")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    col = hexcol(color)
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*col, 1)
        b.inputs["Emission Strength"].default_value = emit
    _mats[key] = m
    return m


def img_mat(fname, rough=0.6, alpha=False, emit=0.0, scale=(1, 1)):
    key = ("img", fname, alpha, emit, scale)
    if key in _mats:
        return _mats[key]
    m = bpy.data.materials.new(fname)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(os.path.join(TEX, fname), check_existing=True)
    if scale != (1, 1):
        mp = nt.nodes.new("ShaderNodeMapping")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp.inputs["Scale"].default_value = (scale[0], scale[1], 1)
        nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    if emit:
        nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = emit
    if alpha:
        nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
        m.blend_method = "CLIP"
        m.shadow_method = "NONE"
        m.alpha_threshold = 0.5
    _mats[key] = m
    return m


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def box(size, loc=(0, 0, 0), material=None, parent=None, bevel=0.04, name="box", rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    if hasattr(me, "use_auto_smooth"):
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(40)
    ob = link(bpy.data.objects.new(name, me))
    ob.location = loc
    ob.rotation_euler = rot
    if bevel:
        md = ob.modifiers.new("bev", "BEVEL")
        md.width = bevel
        md.segments = 3
        md.limit_method = "NONE"
    if material:
        ob.data.materials.append(material)
    if parent:
        ob.parent = parent
    return ob


def cyl(r, h, loc=(0, 0, 0), material=None, parent=None, verts=24, rot=(0, 0, 0), r2=None, name="cyl"):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r if r2 is None else r2, depth=h)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    if hasattr(me, "use_auto_smooth"):
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(40)
    ob = link(bpy.data.objects.new(name, me))
    ob.location = loc
    ob.rotation_euler = rot
    if material:
        ob.data.materials.append(material)
    if parent:
        ob.parent = parent
    return ob


def sphere(r, loc=(0, 0, 0), material=None, parent=None, scale=(1, 1, 1), name="sph"):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=r)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = link(bpy.data.objects.new(name, me))
    ob.location = loc
    ob.scale = scale
    if material:
        ob.data.materials.append(material)
    if parent:
        ob.parent = parent
    return ob


def plane(w, h, loc, material, rot=(0, 0, 0), parent=None, name="plane"):
    me = bpy.data.meshes.new(name)
    hw, hh = w / 2, h / 2
    me.from_pydata([(-hw, -hh, 0), (hw, -hh, 0), (hw, hh, 0), (-hw, hh, 0)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    ob = link(bpy.data.objects.new(name, me))
    ob.location = loc
    ob.rotation_euler = rot
    ob.data.materials.append(material)
    if parent:
        ob.parent = parent
    return ob


def empty(name, loc=(0, 0, 0), parent=None):
    e = link(bpy.data.objects.new(name, None))
    e.location = loc
    if parent:
        e.parent = parent
    return e


def key(ob, path, frame, value=None, index=-1):
    if value is not None:
        if index >= 0:
            getattr(ob, path)[index] = value
        else:
            setattr(ob, path, value)
    ob.keyframe_insert(data_path=path, frame=frame, index=index)


# ----------------------------------------------------------------- sets

def floor(size, material, z=0.0):
    return box((size[0], size[1], 0.2), (0, size[1] / 2 - 3, z - 0.1), material, bevel=0)


def walls(color, back_y=3.6, side_x=5.5, height=3.8, left=True, right=True):
    m = mat(color, 0.8)
    box((side_x * 2 + 0.4, 0.3, height), (0, back_y, height / 2), m, bevel=0)
    if left:
        box((0.3, 12, height), (-side_x, back_y - 6, height / 2), m, bevel=0)
    if right:
        box((0.3, 12, height), (side_x, back_y - 6, height / 2), m, bevel=0)
    # skirting board
    box((side_x * 2, 0.06, 0.18), (0, back_y - 0.17, 0.09), mat("#f4f1ea", 0.5), bevel=0)


def window(x, z, w=1.6, h=1.4, wall_y=3.6, night=False, side=None):
    frame = mat("#ffffff", 0.4)
    sky = mat("#0d1b3d" if night else "#9fd3ff", 1.0, emit=0.6 if night else 2.2)
    if side is None:
        y = wall_y - 0.16
        plane(w, h, (x, y, z), sky, rot=(math.pi / 2, 0, 0))
        box((w + 0.16, 0.08, 0.1), (x, y - 0.02, z + h / 2), frame)
        box((w + 0.16, 0.08, 0.1), (x, y - 0.02, z - h / 2), frame)
        box((0.1, 0.08, h), (x - w / 2, y - 0.02, z), frame)
        box((0.1, 0.08, h), (x + w / 2, y - 0.02, z), frame)
        box((0.06, 0.06, h), (x, y - 0.03, z), frame)
        box((w + 0.3, 0.25, 0.06), (x, y - 0.12, z - h / 2 - 0.04), frame)


def tree(x, y, s=1.0):
    cyl(0.18 * s, 2.0 * s, (x, y, 1.0 * s), mat("#7a5230", 0.9))
    g = mat("#4caf50", 0.8)
    g2 = mat("#3d9443", 0.8)
    sphere(1.1 * s, (x, y, 2.6 * s), g)
    sphere(0.8 * s, (x + 0.6 * s, y + 0.2, 2.3 * s), g2)
    sphere(0.75 * s, (x - 0.6 * s, y - 0.1, 2.4 * s), g2)


def house(x, y, w=4.0, color="#f2d0a4", roof="#b54a3a"):
    box((w, 3.0, 3.0), (x, y, 1.5), mat(color, 0.8), bevel=0.02)
    r = box((w + 0.4, 3.4, 0.25), (x, y, 3.2), mat(roof, 0.7), bevel=0.02)
    box((0.9, 0.08, 1.8), (x, y - 1.52, 0.9), mat("#6b4430", 0.6))
    for dx in (-w / 3, w / 3):
        plane(0.8, 0.8, (x + dx, y - 1.52, 1.9), mat("#bfe6ff", 0.2, emit=0.4), rot=(math.pi / 2, 0, 0))


def chair(x, y, yaw=0, color="#e8833a"):
    p = empty("chair", (x, y, 0))
    p.rotation_euler = (0, 0, math.radians(yaw))
    c = mat(color, 0.5)
    leg = mat("#666a70", 0.4, metal=0.6)
    box((0.55, 0.5, 0.07), (0, 0, 0.47), c, p)
    box((0.55, 0.06, 0.5), (0, 0.24, 0.78), c, p)
    for dx in (-0.23, 0.23):
        for dy in (-0.2, 0.2):
            box((0.05, 0.05, 0.46), (dx, dy, 0.23), leg, p, bevel=0.01)
    return p


def desk(x, y, color="#d9b98a"):
    top = mat(color, 0.5)
    leg = mat("#666a70", 0.4, metal=0.6)
    box((1.1, 0.65, 0.06), (x, y, 0.76), top)
    box((1.0, 0.55, 0.25), (x, y, 0.6), mat("#5a6b7d", 0.6))
    for dx in (-0.5, 0.5):
        box((0.05, 0.05, 0.74), (x + dx, y, 0.37), leg, bevel=0.01)


def bed(x, y, color="#4a7bd1", rot=0):
    p = empty("bed", (x, y, 0))
    p.rotation_euler = (0, 0, rot)
    box((1.4, 2.4, 0.4), (0, 0, 0.25), mat("#8a5a3a", 0.6), p)
    box((1.35, 2.3, 0.25), (0, 0, 0.55), mat("#f6f6f6", 0.8), p)
    box((1.4, 1.6, 0.12), (0, -0.4, 0.68), mat(color, 0.8), p)
    box((0.9, 0.4, 0.18), (0, 0.85, 0.72), mat("#ffffff", 0.9), p)
    box((1.5, 0.15, 1.1), (0, 1.25, 0.55), mat("#8a5a3a", 0.6), p)
    return p


def crib(x, y):
    w = mat("#ffffff", 0.5)
    box((1.3, 2.0, 0.1), (x, y, 0.55), w)
    box((1.25, 1.95, 0.15), (x, y, 0.65), mat("#9fd0ff", 0.8))
    for side in (-1, 1):
        box((1.4, 0.08, 0.08), (x, y + side * 1.0, 1.25), w)
        box((0.08, 2.0, 0.08), (x + side * 0.68, y, 1.25), w)
        for i in range(11):
            box((0.05, 0.05, 0.7), (x - 0.62 + i * 0.124, y + side * 1.0, 0.9), w, bevel=0.01)
        for i in range(15):
            box((0.05, 0.05, 0.7), (x + side * 0.68, y - 0.92 + i * 0.13, 0.9), w, bevel=0.01)
        box((0.1, 0.1, 1.3), (x + side * 0.68, y - 1.0, 0.65), w)
        box((0.1, 0.1, 1.3), (x + side * 0.68, y + 1.0, 0.65), w)


def lockers(x0, n, y, color="#3fb7b1"):
    c = mat(color, 0.45, metal=0.2)
    dark = mat("#2a2a2a", 0.5)
    for i in range(n):
        x = x0 + i * 0.62
        box((0.6, 0.5, 2.1), (x, y, 1.05), c, bevel=0.01)
        for k in range(4):
            box((0.32, 0.02, 0.03), (x, y - 0.26, 1.85 - k * 0.06), dark, bevel=0)
        box((0.04, 0.03, 0.18), (x + 0.2, y - 0.26, 1.1), mat("#cccccc", 0.3, metal=0.8), bevel=0)


def build_set(name, time="day"):
    night = time == "night"
    sunset = time == "sunset"
    slots = {}
    world_col = "#b9d8f0"
    sun_energy, sun_col, sun_rot = 3.0, "#fff3dd", (math.radians(50), math.radians(10), math.radians(30))
    interior = True
    ceiling_light = 250
    if name in ("bedroom", "nursery"):
        floor((14, 12), img_mat("wood.png", scale=(3, 3)))
        walls("#f0b88a" if name == "bedroom" else "#bfe3d4")
        window(1.8, 2.0, night=night)
        plane(3.0, 4.2, (0, 0.4, 0.005), img_mat("rug.png", 0.9))
        if name == "bedroom":
            bed(-3.3, 1.9)
        else:
            crib(-2.6, 1.4)
            slots["CRIB"] = (-2.6, 1.4, 0, 0.62)
        box((1.6, 0.7, 0.08), (3.6, 3.0, 0.8), mat("#ffffff", 0.4))
        box((1.5, 0.6, 0.78), (3.6, 3.0, 0.4), mat("#e9e3d8", 0.5))
        cyl(0.12, 0.5, (3.2, 3.0, 1.1), mat("#333333"))
        sphere(0.2, (3.2, 3.0, 1.45), mat("#fff3c0", 0.3, emit=4.0))
        plane(0.8, 1.1, (-1.2, 3.43, 2.1), img_mat("poster1.png"), rot=(math.pi / 2, 0, 0))
        plane(0.7, 1.0, (4.2, 3.43, 2.3), img_mat("poster2.png"), rot=(math.pi / 2, 0, 0))
        box((1.6, 0.35, 0.06), (-0.4, 3.3, 2.9), mat("#ffffff", 0.5))
        for i, c in enumerate(["#e04f5f", "#4f8fe0", "#f2c14e", "#5fc46a"]):
            box((0.18, 0.28, 0.42), (-0.9 + i * 0.25, 3.3, 3.14), mat(c))
        cyl(0.25, 0.5, (4.6, 1.2, 0.25), mat("#c8743b"))
        sphere(0.45, (4.6, 1.2, 0.85), mat("#3e9b4a", 0.8))
        world_col = "#e8c9a8"
        slots.update({"A": (0, 0.2, 0), "B": (1.3, 0.5, 0), "C": (-1.3, 0.5, 0), "D": (0.7, -0.8, 0),
                      "E": (-0.7, -0.8, 0), "BED": (-3.3, 1.9, 0, 0.72), "DESK": (3.6, 2.2, 180)})
    elif name == "classroom":
        floor((14, 12), img_mat("tiles_gray.png", scale=(4, 4)))
        walls("#f3e6c4")
        box((3.6, 0.08, 1.6), (-2.6, 3.42, 1.9), mat("#7a5230", 0.6))
        plane(3.4, 1.45, (-2.6, 3.37, 1.9), img_mat("chalkboard.png", 0.9), rot=(math.pi / 2, 0, 0))
        box((2.6, 0.06, 1.3), (2.4, 3.43, 1.9), mat("#c99a5e", 0.9))
        for i in range(4):
            plane(0.5, 0.65, (1.5 + i * 0.6, 3.39, 1.95 + (i % 2) * 0.1), img_mat(f"poster{i}.png"), rot=(math.pi / 2, 0, 0))
        cyl(0.28, 0.05, (0.3, 3.42, 3.1), mat("#ffffff", 0.3), rot=(math.pi / 2, 0, 0))
        window(4.6, 2.0, night=night) if False else None
        box((1.6, 0.8, 0.8), (-3.4, 2.0, 0.4), mat("#8a5a3a", 0.5))
        box((1.7, 0.85, 0.06), (-3.4, 2.0, 0.83), mat("#a0704a", 0.4))
        sphere(0.12, (-3.0, 2.0, 0.95), mat("#e53935", 0.3))
        desks = []
        for r, y in enumerate((1.6, 0.0)):
            for cidx, x in enumerate((0.0, 1.6, 3.2)):
                desk(x, y - 0.55)
                chair(x, y, 180, ["#e8833a", "#3a8be8", "#4caf50"][cidx])
                desks.append((x, y))
        for i, (x, y) in enumerate(desks):
            slots[f"S{i + 1}"] = (x, y + 0.05, 0, 0.47)
        slots.update({"T": (-2.6, 1.6, 0), "A": (-1.4, -0.6, 0), "B": (0.0, -1.4, 0), "C": (1.4, -1.4, 0),
                      "D": (-2.6, 0.2, 0)})
        world_col = "#f4ead2"
    elif name == "hallway":
        floor((16, 12), img_mat("tiles_blue.png", scale=(5, 5)))
        walls("#e8edf2")
        lockers(-5.0, 17, 3.3)
        for x in (-3, 0, 3):
            box((1.6, 0.4, 0.06), (x, 1.0, 3.75), mat("#ffffff", 0.2, emit=6.0), bevel=0)
        plane(0.9, 1.2, (4.6, 3.43, 2.6), img_mat("poster3.png"), rot=(math.pi / 2, 0, 0))
        slots.update({"A": (0, 0.3, 0), "B": (1.4, 0.6, 0), "C": (-1.4, 0.6, 0), "D": (2.8, 1.0, 0),
                      "E": (-2.8, 1.0, 0), "F": (0.4, 2.5, 0), "G": (-4.0, 1.6, 0)})
        world_col = "#dbe4ee"
        ceiling_light = 300
    elif name == "cafeteria":
        floor((16, 12), img_mat("tiles_gray.png", scale=(5, 5)))
        walls("#f7d9a0")
        box((6, 0.8, 1.0), (0, 3.0, 0.5), mat("#b0b8c0", 0.3, metal=0.6))
        box((6, 0.4, 0.05), (0, 2.8, 1.5), mat("#ffffff", 0.2, emit=3.0), bevel=0)
        for x in (-2.0, 2.0):
            box((1.0, 3.2, 0.06), (x, 0.6, 0.78), mat("#f2f2f2", 0.4))
            box((0.9, 3.0, 0.75), (x, 0.6, 0.39), mat("#5a6b7d", 0.5))
            for side in (-1, 1):
                box((0.35, 3.0, 0.08), (x + side * 0.85, 0.6, 0.46), mat("#e8833a", 0.5))
                box((0.3, 2.8, 0.42), (x + side * 0.85, 0.6, 0.21), mat("#5a6b7d", 0.5))
            for dy in (-0.6, 0.6, 1.6):
                tray = box((0.35, 0.45, 0.04), (x - 0.25, dy, 0.83), mat("#3a8be8", 0.5))
                sphere(0.08, (x - 0.25, dy - 0.1, 0.9), mat("#f2c14e"))
                box((0.14, 0.14, 0.08), (x - 0.2, dy + 0.1, 0.89), mat("#e53935"))
        slots.update({"A": (0, 0.0, 0), "B": (0.0, 1.4, 0), "C": (-0.9, -1.0, 0), "D": (0.9, -1.0, 0),
                      "SL": (-2.85, 0.4, 90, 0.47), "SR": (-1.15, 0.4, -90, 0.47),
                      "SL2": (2.85, 0.4, -90, 0.47), "SR2": (1.15, 0.4, 90, 0.47)})
        world_col = "#f1e2c4"
    elif name == "livingroom":
        floor((14, 12), img_mat("wood_light.png", scale=(3, 3)))
        walls("#cfe0c8")
        window(-2.6, 2.0, night=night)
        window(2.8, 2.0, w=2.2, night=night)
        plane(3.4, 2.4, (0, 0.2, 0.005), img_mat("rug.png", 0.9))
        sofa = mat("#7a5bd1", 0.8)
        box((2.8, 0.9, 0.45), (0, 2.4, 0.3), sofa)
        box((2.8, 0.3, 0.9), (0, 2.85, 0.55), sofa)
        for s in (-1, 1):
            box((0.3, 0.9, 0.65), (s * 1.45, 2.4, 0.4), sofa)
        box((1.6, 0.4, 0.5), (4.6, 0.6, 0.25), mat("#6b4430", 0.5))
        box((0.08, 1.6, 0.9), (4.7, 0.6, 1.0), mat("#111111", 0.2), rot=(0, 0, 0))
        plane(1.5, 0.82, (4.65, 0.6, 1.0), mat("#4da3ff", 0.3, emit=1.5), rot=(math.pi / 2, 0, math.pi / 2))
        cyl(0.18, 1.6, (-4.4, 2.6, 0.8), mat("#333333"))
        cyl(0.35, 0.4, (-4.4, 2.6, 1.7), mat("#fff3c0", 0.4, emit=2.0), r2=0.2)
        plane(1.1, 0.8, (0.0, 3.43, 2.4), img_mat("poster0.png"), rot=(math.pi / 2, 0, 0))
        slots.update({"A": (0, 0.2, 0), "B": (1.3, 0.4, 0), "C": (-1.3, 0.4, 0), "D": (0.6, -0.9, 0),
                      "SOFA": (0, 2.35, 0, 0.5), "SOFA2": (0.9, 2.35, 0, 0.5), "SOFA3": (-0.9, 2.35, 0, 0.5)})
        world_col = "#e2dccf"
    elif name == "hospital":
        floor((14, 12), img_mat("tiles_gray.png", scale=(4, 4)))
        walls("#e6f0f2")
        window(2.6, 2.0, night=night)
        bed(-1.4, 1.6, color="#9fc7d8")
        box((0.5, 0.4, 1.4), (-0.3, 3.1, 0.7), mat("#c9ced3", 0.4))
        plane(0.42, 0.3, (-0.3, 2.89, 1.25), mat("#0aff6a", 0.3, emit=2.5), rot=(math.pi / 2, 0, 0))
        box((0.04, 3.0, 2.6), (-3.2, 1.6, 1.4), mat("#8ec9c0", 0.9))
        slots.update({"BED": (-1.4, 1.6, 0, 0.72), "A": (0.4, 0.6, 0), "B": (1.6, 0.6, 0),
                      "C": (0.6, -0.6, 0), "D": (2.6, 0.0, 0)})
        world_col = "#e3eef0"
        ceiling_light = 320
    elif name in ("street", "park", "schoolyard"):
        interior = False
        g = mat("#6cc04a", 0.9)
        box((60, 60, 0.2), (0, 10, -0.1), g, bevel=0)
        if name in ("street", "schoolyard"):
            box((60, 4, 0.02), (0, -4.0, 0.01), mat("#3a3d42", 0.8), bevel=0)
            for i in range(-6, 7):
                box((1.2, 0.15, 0.02), (i * 3.0, -4.0, 0.025), mat("#ffffff", 0.6), bevel=0)
            box((60, 2.0, 0.08), (0, -1.2, 0.04), mat("#c9c9c9", 0.8), bevel=0)
        if name == "schoolyard":
            b = img_mat("bricks.png", 0.9, scale=(4, 1))
            box((16, 4, 6), (0, 7, 3), b, bevel=0)
            box((2.4, 0.1, 2.6), (0, 4.95, 1.3), mat("#2b5fa8", 0.4))
            for x in (-5.5, -3, 3, 5.5):
                for z in (1.8, 4.2):
                    plane(1.4, 1.2, (x, 4.94, z), mat("#bfe6ff", 0.2, emit=0.5), rot=(math.pi / 2, 0, 0))
            cyl(0.06, 6, (6.5, 3.5, 3), mat("#cccccc", 0.3, metal=0.8))
            box((0.02, 1.2, 0.8), (6.5, 3.0, 5.5), mat("#d32f2f", 0.6), bevel=0)
            tree(-7, 3)
            tree(8.5, 2)
        elif name == "street":
            house(-5, 6, color="#f2d0a4")
            house(0.5, 7, color="#a4c8f2", roof="#3a4ab5")
            house(6, 6, color="#f2a4b8", roof="#6b4430")
            tree(-2.2, 3.5)
            tree(3.3, 3.8, 0.9)
            box((0.12, 0.12, 1.0), (2.0, -0.6, 0.5), mat("#ffffff"))
        else:  # park
            for (x, y, s) in [(-5, 5, 1.2), (5, 6, 1.0), (-1, 9, 1.4), (8, 3, 0.9), (-8, 2, 1.0)]:
                tree(x, y, s)
            wood = mat("#a0704a", 0.6)
            box((2.0, 0.5, 0.08), (3.2, 1.8, 0.5), wood)
            box((2.0, 0.08, 0.5), (3.2, 2.05, 0.8), wood)
            for dx in (-0.85, 0.85):
                box((0.08, 0.45, 0.48), (3.2 + dx, 1.8, 0.24), mat("#333333"))
            box((0.6, 3.2, 0.06), (-3.4, 2.2, 1.0), mat("#e53935", 0.4), rot=(math.radians(28), 0, 0))
            box((0.7, 0.7, 1.7), (-3.4, 3.6, 0.85), mat("#f2c14e", 0.5))
            box((3, 0.08, 0.08), (0, 4.5, 1.0), mat("#8a5a3a"))
            slots["BENCH"] = (3.2, 1.75, 0, 0.5)
        slots.update({"A": (0, 0.2, 0), "B": (1.4, 0.5, 0), "C": (-1.4, 0.5, 0), "D": (0.7, -0.6, 0),
                      "E": (-0.7, -0.6, 0), "F": (3.5, 1.0, 0), "G": (-3.5, 1.0, 0), "ROAD": (0, -4.0, 0)})
        world_col = "#8ec5f0"
        sun_energy = 4.5
    else:
        raise SystemExit(f"unknown set {name}")

    if night:
        world_col = "#1a2340" if not interior else "#2a2a3a"
        sun_energy, sun_col = 0.6, "#8fa8ff"
    elif sunset:
        world_col = "#f0a070"
        sun_energy, sun_col = 3.0, "#ffb070"
        sun_rot = (math.radians(75), math.radians(10), math.radians(30))

    w = bpy.context.scene.world
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*hexcol(world_col), 1)
    bg.inputs["Strength"].default_value = 0.9 if interior else 1.2
    if night:
        bg.inputs["Strength"].default_value = 0.35

    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = sun_energy
    sun.color = hexcol(sun_col)
    sun.angle = math.radians(8)
    so = link(bpy.data.objects.new("sun", sun))
    so.rotation_euler = sun_rot
    if interior:
        a = bpy.data.lights.new("ceil", "AREA")
        a.shape = "RECTANGLE"
        a.size, a.size_y = 6, 4
        a.energy = ceiling_light * (0.35 if night else 1.0)
        a.color = hexcol("#fff1dc" if not night else "#ffd59a")
        ao = link(bpy.data.objects.new("ceil", a))
        ao.location = (0, 0.5, 3.7)
        # ceiling
        box((12, 12, 0.2), (0, -2.4, 3.9), mat("#f5f5f5", 0.9), bevel=0)
    # soft fill from camera side so faces read well
    f = bpy.data.lights.new("fill", "AREA")
    f.size = 4
    f.energy = 120
    fo = link(bpy.data.objects.new("fill", f))
    fo.location = (0, -5, 2.4)
    fo.rotation_euler = (math.radians(70), 0, 0)
    return slots, interior


# ----------------------------------------------------------------- characters

class Char:
    pass


def build_hair(style, col, neck, ch):
    m = mat(col, 0.7)
    top = 0.7 + 0.65  # top of head in neck space
    if style in ("none", "bald"):
        return
    if style == "cap":
        box((1.5, 1.4, 0.45), (0, 0, top + 0.05), m, neck, bevel=0.12)
        box((1.3, 0.8, 0.08), (0, -0.95, top - 0.12), m, neck, bevel=0.03)
        return
    base = box((1.52, 1.42, 0.42), (0, 0.02, top), m, neck, bevel=0.15, name="hairbase")
    box((1.5, 0.35, 1.0), (0, 0.55, top - 0.45), m, neck, bevel=0.12)  # back
    if style == "spiky":
        rnd = random.Random(42)
        for i in range(13):
            x = -0.62 + (i % 5) * 0.31 + rnd.uniform(-0.05, 0.05)
            y = -0.45 + (i // 5) * 0.42
            c = cyl(0.22, 0.45, (x, y, top + 0.25), m, neck, verts=5, r2=0.03)
            c.rotation_euler = (rnd.uniform(-0.6, -0.1) + (i // 5) * 0.35, rnd.uniform(-0.5, 0.5) + x * 0.6, rnd.uniform(0, 1))
        for i in range(5):  # fringe
            x = -0.56 + i * 0.28
            c = cyl(0.17, 0.4, (x, -0.68, top - 0.1), m, neck, verts=5, r2=0.03)
            c.rotation_euler = (math.radians(200), 0.25 * (2 - i) * -0.5, 0.3)
        for s in (-1, 1):
            box((0.18, 0.9, 0.6), (s * 0.72, 0.1, top - 0.35), m, neck, bevel=0.06)
    elif style == "short":
        box((1.52, 0.3, 0.25), (0, -0.6, top - 0.15), m, neck, bevel=0.08)
        for s in (-1, 1):
            box((0.16, 1.0, 0.45), (s * 0.72, 0.1, top - 0.25), m, neck, bevel=0.06)
    elif style == "messy":
        rnd = random.Random(7)
        for i in range(10):
            sphere(0.32, (rnd.uniform(-0.6, 0.6), rnd.uniform(-0.55, 0.5), top + rnd.uniform(0.05, 0.25)), m, neck)
        for i in range(4):
            sphere(0.22, (-0.5 + i * 0.33, -0.66, top - 0.1), m, neck, scale=(1, 0.6, 1))
    elif style == "curly":
        rnd = random.Random(9)
        for i in range(22):
            a = rnd.uniform(0, math.tau)
            sphere(0.27, (0.72 * math.cos(a) * rnd.uniform(0.3, 1), 0.66 * math.sin(a) * rnd.uniform(0.3, 1) + 0.05,
                          top + rnd.uniform(-0.1, 0.25)), m, neck)
    elif style in ("long", "pigtails", "bun", "ponytail", "bob"):
        box((1.52, 0.25, 0.3), (0, -0.62, top - 0.12), m, neck, bevel=0.08)
        if style in ("long", "bob"):
            ln = 1.6 if style == "long" else 0.9
            for s in (-1, 1):
                box((0.22, 1.3, ln), (s * 0.78, 0.1, top - ln / 2 - 0.05), m, neck, bevel=0.08)
            box((1.6, 0.3, ln), (0, 0.6, top - ln / 2 - 0.05), m, neck, bevel=0.08)
        if style == "pigtails":
            for s in (-1, 1):
                sphere(0.38, (s * 0.95, 0.15, top - 0.15), m, neck)
                sphere(0.3, (s * 1.05, 0.2, top - 0.65), m, neck)
        if style == "bun":
            sphere(0.42, (0, 0.35, top + 0.35), m, neck)
        if style == "ponytail":
            sphere(0.35, (0, 0.75, top - 0.1), m, neck)
            box((0.35, 0.3, 1.0), (0, 0.85, top - 0.7), m, neck, bevel=0.12)
    elif style == "curlers":  # mom with curlers
        box((1.52, 0.25, 0.3), (0, -0.62, top - 0.12), m, neck, bevel=0.08)
        for i in range(6):
            cyl(0.14, 0.42, (-0.55 + (i % 3) * 0.55, -0.2 + (i // 3) * 0.5, top + 0.22),
                mat("#ff7ab8", 0.5), neck, rot=(0, math.pi / 2, 0))


def make_char(name, spec, x, y, yaw):
    c = Char()
    c.name = name
    c.spec = spec
    age = spec.get("age", "kid")
    hs = {"kid": 1.0, "adult": 1.18, "baby": 0.62, "teen": 1.08}.get(age, 1.0) * spec.get("height", 1.0)
    c.scale = CHAR_SCALE * hs
    skin = mat(spec.get("skin", "#f2c9a0"), 0.55)
    shirt = mat(spec.get("shirt", "#3a8be8"), 0.7)
    pants = mat(spec.get("pants", "#2b3b6b"), 0.7)
    shoes = mat(spec.get("shoes", "#222222"), 0.5)
    accent = mat(spec.get("accent", "#ffffff"), 0.6)
    root = empty(name, (x, y, 0))
    root.rotation_euler = (0, 0, math.radians(yaw))
    root.scale = (c.scale,) * 3
    legh = 1.7 if age != "baby" else 1.1
    hips = empty(name + "_hips", (0, 0, legh + 0.3), root)
    torso_mat = shirt
    box((2.0, 1.0, 2.0), (0, 0, 1.0), torso_mat, hips, bevel=0.1, name=name + "_torso")
    top = spec.get("top", "tshirt")
    if top == "hoodie":
        box((1.7, 0.5, 0.55), (0, 0.55, 1.95), torso_mat, hips, bevel=0.15)
        for s in (-0.3, 0.3):
            box((0.08, 0.04, 0.6), (s, -0.52, 1.5), accent, hips, bevel=0.01)
        box((1.1, 0.04, 0.5), (0, -0.51, 0.45), mat(spec.get("shirt", "#3a8be8"), 0.9), hips, bevel=0.02)
    elif top == "jacket":
        box((0.7, 0.04, 2.0), (0, -0.51, 1.0), accent, hips, bevel=0.01)
    elif top == "dress":
        box((2.4, 1.3, 1.0), (0, 0, -0.2), torso_mat, hips, bevel=0.1)
    elif top == "stripes":
        for k in range(3):
            box((2.02, 1.02, 0.18), (0, 0, 0.4 + k * 0.6), accent, hips, bevel=0.02)
    elif top == "suit":
        box((0.5, 0.04, 1.4), (0, -0.51, 1.25), mat("#ffffff"), hips, bevel=0.01)
        box((0.18, 0.05, 1.1), (0, -0.53, 1.3), accent, hips, bevel=0.01)
    elif top == "galaxy":
        for k in range(8):
            sphere(0.12, (RND.uniform(-0.9, 0.9), -0.51, RND.uniform(0.2, 1.8)), mat("#ffffff", 0.3, emit=3), hips,
                   scale=(1, 0.2, 1))
    if spec.get("logo"):
        cyl(0.3, 0.03, (0, -0.52, 1.25), mat(spec["logo"], 0.4), hips, rot=(math.pi / 2, 0, 0))
    neck = empty(name + "_neck", (0, 0, 2.0), hips)
    head = box((1.42, 1.3, 1.3), (0, 0, 0.7), skin, neck, bevel=0.32, name=name + "_head")
    face = spec.get("face", "neutral")
    c.faces = {}
    c.neck, c.hips, c.root = neck, hips, root
    c.face_parent = neck
    build_hair(spec.get("hair", "short"), spec.get("hair_color", "#4a2e1c"), neck, c)
    for acc in spec.get("acc", []):
        if acc == "crown":
            g = mat("#ffcc33", 0.25, metal=0.9)
            cyl(0.55, 0.3, (0, 0, 1.65), g, neck, verts=20)
            for i in range(5):
                a = i / 5 * math.tau
                cyl(0.12, 0.35, (0.5 * math.cos(a), 0.5 * math.sin(a), 1.95), g, neck, verts=4, r2=0)
        elif acc == "glasses":
            gm = mat("#1a1a1a", 0.3)
            for s in (-0.33, 0.33):  # thin rims so the eyes stay visible
                box((0.46, 0.04, 0.05), (s, -0.69, 0.92), gm, neck, bevel=0)
                box((0.46, 0.04, 0.05), (s, -0.69, 0.6), gm, neck, bevel=0)
                box((0.05, 0.04, 0.37), (s - 0.21, -0.69, 0.76), gm, neck, bevel=0)
                box((0.05, 0.04, 0.37), (s + 0.21, -0.69, 0.76), gm, neck, bevel=0)
            box((0.2, 0.04, 0.05), (0, -0.69, 0.86), gm, neck, bevel=0)
        elif acc == "headband":
            box((1.5, 1.38, 0.15), (0, 0, 1.15), accent, neck, bevel=0.06)
        elif acc == "backpack":
            box((1.5, 0.6, 1.6), (0, 0.8, 1.0), mat(spec.get("bag", "#e53935"), 0.6), hips, bevel=0.15)
        elif acc == "cape":
            box((1.9, 0.08, 2.8), (0, 0.58, 0.6), mat(spec.get("cape", "#d32f2f"), 0.6), hips, bevel=0.02,
                rot=(math.radians(-6), 0, 0))
        elif acc == "note":  # sticky note on the forehead
            box((0.55, 0.03, 0.4), (0.05, -0.74, 1.08), mat("#ffe14d", 0.7), neck, bevel=0.0,
                rot=(0, math.radians(-6), 0))
            for k in range(3):
                box((0.36, 0.035, 0.03), (0.03, -0.75, 1.17 - k * 0.09), mat("#5a5a5a", 0.6), neck, bevel=0)
        elif acc == "bow":
            for s in (-1, 1):
                sphere(0.22, (s * 0.25 + 0.45, -0.1, 1.55), mat("#ff4fa0", 0.5), neck, scale=(1.2, 0.6, 0.8))
    # arms (character's right = -x)
    c.arms = {}
    for side, sx in (("r", -1), ("l", 1)):
        sh = empty(f"{name}_sh{side}", (sx * 1.48, 0, 1.85), hips)
        sleeve = shirt if top not in ("tshirt", "dress") else skin
        if top in ("tshirt", "stripes", "galaxy"):
            box((0.92, 0.92, 0.7), (0, 0, -0.3), shirt, sh, bevel=0.1)
            box((0.86, 0.86, 1.3), (0, 0, -1.25), skin, sh, bevel=0.1)
        else:
            box((0.92, 0.92, 1.6), (0, 0, -0.75), sleeve, sh, bevel=0.1)
            box((0.84, 0.84, 0.42), (0, 0, -1.7), skin, sh, bevel=0.12)
        hand = empty(f"{name}_hand{side}", (0, -0.1, -1.9), sh)
        c.arms[side] = (sh, hand)
    c.legs = {}
    for side, sx in (("r", -0.5), ("l", 0.5)):
        hp = empty(f"{name}_hip{side}", (sx, 0, 0), hips)
        box((0.96, 0.96, legh), (0, 0, -legh / 2), pants, hp, bevel=0.08)
        box((0.98, 1.15, 0.32), (0, -0.08, -legh - 0.08), shoes, hp, bevel=0.1)
        c.legs[side] = hp
    c.legh = legh
    return c


def set_face(c, kind, talk, f0, f1):
    """Two face planes (closed / open mouth); alternate visibility to lip-flap."""
    k = kind
    closed = plane(1.3, 1.3, (0, -0.665, 0.64), img_mat(f"face_{k}.png", alpha=True),
                   rot=(math.pi / 2, 0, 0), parent=c.face_parent, name=c.name + "_face")
    opened = plane(1.3, 1.3, (0, -0.666, 0.64), img_mat(f"face_{k}_open.png", alpha=True),
                   rot=(math.pi / 2, 0, 0), parent=c.face_parent, name=c.name + "_faceo")
    opened.hide_render = True
    opened.keyframe_insert("hide_render", frame=1)
    if talk:
        f = f0
        state = False
        rnd = random.Random(hash(c.name) & 0xffff)
        while f < f1:
            state = not state
            opened.hide_render = not state
            closed.hide_render = state
            opened.keyframe_insert("hide_render", frame=f)
            closed.keyframe_insert("hide_render", frame=f)
            f += rnd.choice([2, 3, 3, 4])
        opened.hide_render = True
        closed.hide_render = False
        opened.keyframe_insert("hide_render", frame=f1)
        closed.keyframe_insert("hide_render", frame=f1)


def wave(t, speed=1.0, phase=0.0):
    return math.sin((t * speed + phase) * math.tau)


def animate(c, cfg, slots, chars_by_name, cam_info):
    act = cfg.get("act", "idle")
    acts = act if isinstance(act, list) else [act]
    root, hips, neck = c.root, c.hips, c.neck
    sh_r, hand_r = c.arms["r"]
    sh_l, hand_l = c.arms["l"]
    leg_r, leg_l = c.legs["r"], c.legs["l"]
    seat = cfg.get("_seat")
    base_hz = hips.location.z
    if "sit" in acts or seat is not None:
        base_hz = (seat if seat is not None else 0.47) / c.scale + 0.05
        for lg in (leg_r, leg_l):
            lg.rotation_euler = (math.radians(-88), 0, 0)
            # lower legs are one block; drop them to the floor with a small offset
        hips.location.z = base_hz
    start = Vector(root.location)
    end = None
    c.moving = bool(cfg.get("to"))
    if cfg.get("to"):
        t = cfg["to"]
        if isinstance(t, str):
            s = slots[t]
            end = Vector((s[0], s[1], 0))
        else:
            end = Vector((t[0], t[1], 0))
    yaw0 = root.rotation_euler.z
    if cfg.get("look"):
        tgt = chars_by_name.get(cfg["look"])
        if tgt is not None:
            d = Vector(tgt.root.location) - Vector(root.location)
            # turn only part of the way so the face still reads on camera
            yaw0 = math.atan2(d.x, -d.y) * cfg.get("look_amount", 0.5)
            root.rotation_euler.z = yaw0
    if "lie" in acts:
        root.rotation_euler.x = math.radians(-90)
        root.location.z = (cfg.get("_seat") or 0.0) + 0.5 * c.scale
        body = (c.legh + 0.3 + 2.0 + 1.35) * c.scale
        root.location.y -= body / 2 - 0.15
        hips.location.z = c.legh + 0.3
        for lg in (leg_r, leg_l):
            lg.rotation_euler = (0, 0, 0)
    step = 2
    for f in range(1, NF + 2, step):
        t = (f - 1) / FPS
        u = (f - 1) / max(1, NF - 1)
        # idle breathing + sway always
        hz = base_hz + 0.04 * wave(t, 0.35)
        rz = 0.03 * wave(t, 0.2, 0.3)
        nx = 0.03 * wave(t, 0.27)
        nz = 0.05 * wave(t, 0.13, 0.5)
        ar = [0.05 * wave(t, 0.3), 0.0, 0.08]  # right arm rot (x, y) small out
        al = [0.05 * wave(t, 0.3, 0.5), 0.0, -0.08]
        lr = list(leg_r.rotation_euler)
        ll = list(leg_l.rotation_euler)
        pos = Vector(start)
        yaw = yaw0
        rx = root.rotation_euler.x
        if "talk" in acts:
            nx += 0.06 * wave(t, 1.1)
            nz += 0.06 * wave(t, 0.45)
            ar[0] = -0.5 - 0.25 * wave(t, 0.6)
            ar[1] = 0.25
        if "walk" in acts or "run" in acts:
            sp = 2.2 if "run" in acts else 1.5
            amp = 0.75 if "run" in acts else 0.5
            if end is not None:
                ease = u * u * (3 - 2 * u) if "run" not in acts else u
                pos = start.lerp(end, min(1, ease * 1.15))
                d = end - start
                if d.length > 0.01 and u < 0.87:
                    yaw = math.atan2(d.x, -d.y)
                moving = u < 0.87
            else:
                moving = True
            if moving:
                s = wave(t, sp)
                lr = [amp * s, 0, 0]
                ll = [-amp * s, 0, 0]
                ar = [-amp * s * 0.8, 0, 0.08]
                al = [amp * s * 0.8, 0, -0.08]
                hz += 0.12 * abs(wave(t, sp))
        if "jump" in acts:
            hz += 2.2 * abs(math.sin(t * math.pi * 1.6))
            ar = [0, 2.6, 0]
            al = [0, -2.6, 0]
        if "cheer" in acts:
            ar = [0, 2.5 + 0.25 * wave(t, 2), 0]
            al = [0, -2.5 - 0.25 * wave(t, 2, 0.5), 0]
            hz += 0.5 * abs(wave(t, 1.2))
        if "wave" in acts:
            ar = [0, 2.6, 0.35 * wave(t, 1.6)]
        if "point" in acts:
            ar = [-1.55, 0.1, 0]
        if "hold" in acts:
            ar = [-1.0, 0.15, 0]
        if "hug" in acts:
            ar = [-1.4, -0.35, 0]
            al = [-1.4, 0.35, 0]
        if "cry" in acts:
            ar = [-2.3, -0.55, 0]
            al = [-2.3, 0.55, 0]
            nx = 0.35 + 0.04 * wave(t, 3)
            rz = 0.04 * wave(t, 4)
        if "sad" in acts:
            nx = 0.3
            ar = [0.05, 0, 0.02]
            al = [0.05, 0, -0.02]
            hz -= 0.05
        if "shrug" in acts:
            k = max(0, wave(t, 0.5))
            ar = [-0.3, 0.6 * k, 0]
            al = [-0.3, -0.6 * k, 0]
            nz = 0.15 * k
        if "shake" in acts or "scared" in acts:
            rz += 0.05 * wave(t, 9)
            nz += 0.04 * wave(t, 11)
            if "scared" in acts:
                ar = [-2.0, -0.4, 0]
                al = [-2.0, 0.4, 0]
        if "angry" in acts:
            ar = [0.2, 0.3, 0]
            al = [0.2, -0.3, 0]
            rz += 0.03 * wave(t, 6)
        if "dance" in acts:
            ar = [0, 1.5 + wave(t, 1.2), 0]
            al = [0, -1.5 + wave(t, 1.2), 0]
            rz = 0.3 * wave(t, 0.6)
            hz += 0.25 * abs(wave(t, 1.2))
        if "float" in acts:
            hz += (0.6 + 1.5 * u) / c.scale * 0.35 + 0.15 * wave(t, 0.5)
            ar = [0, 1.2, 0]
            al = [0, -1.2, 0]
            lr = [0.15, 0, 0]
            ll = [-0.1, 0, 0]
        if "fall" in acts:
            k = min(1, t / 0.6)
            rx = math.radians(-90) * k * k
            pos.z = 0.5 * c.scale * k
        if "lookaround" in acts:
            nz = 0.5 * wave(t, 0.35)
        if "nod" in acts:
            nx = 0.2 * wave(t, 1.2)
        if "headshake" in acts:
            nz = 0.35 * wave(t, 1.4)
        if "turn" in acts:
            yaw = yaw0 + math.pi * min(1, u * 2)
        if "sit" in acts or seat is not None:
            lr = [math.radians(-88), 0, 0]
            ll = [math.radians(-88), 0, 0]
        if "lie" in acts:
            lr = [0, 0, 0]
            ll = [0, 0, 0]
            rx = math.radians(-90)
        hips.location.z = hz
        hips.rotation_euler = (0, 0, rz)
        neck.rotation_euler = (nx, 0, nz)
        sh_r.rotation_euler = (ar[0], ar[1], ar[2] if len(ar) > 2 else 0)
        sh_l.rotation_euler = (al[0], al[1], al[2] if len(al) > 2 else 0)
        leg_r.rotation_euler = lr
        leg_l.rotation_euler = ll
        if "lie" not in acts:
            root.location = (pos.x, pos.y, pos.z)
            root.rotation_euler = (rx, 0, yaw)
        for ob in (hips,):
            ob.keyframe_insert("location", frame=f)
            ob.keyframe_insert("rotation_euler", frame=f)
        for ob in (neck, sh_r, sh_l, leg_r, leg_l):
            ob.keyframe_insert("rotation_euler", frame=f)
        if "lie" not in acts:
            root.keyframe_insert("location", frame=f)
            root.keyframe_insert("rotation_euler", frame=f)


# ----------------------------------------------------------------- props & fx

def make_prop(kind, parent=None, loc=(0, 0, 0), inv_scale=1.0):
    p = empty("prop_" + kind, loc, parent)
    # props held in hand are built in meters; undo character scale
    p.scale = (inv_scale,) * 3
    if kind == "ball":
        sphere(0.22, (0, -0.1, 0), mat("#ffffff", 0.4), p)
        for i in range(6):
            a = i / 6 * math.tau
            sphere(0.07, (0.2 * math.cos(a), -0.1 + 0.2 * math.sin(a), 0.05), mat("#111111", 0.4), p,
                   scale=(1, 1, 0.5))
    elif kind == "phone":
        box((0.12, 0.02, 0.24), (0, -0.05, 0.05), mat("#111111", 0.2), p, bevel=0.02)
        plane(0.1, 0.2, (0, -0.062, 0.05), mat("#7fd4ff", 0.2, emit=2.0), rot=(math.pi / 2, 0, 0), parent=p)
    elif kind == "book":
        box((0.3, 0.06, 0.4), (0, -0.08, 0), mat("#d84343", 0.6), p, bevel=0.01)
    elif kind == "tray":
        box((0.5, 0.35, 0.03), (0, -0.25, 0.1), mat("#3a8be8", 0.5), p, bevel=0.01, rot=(math.pi / 2, 0, 0))
    elif kind == "trophy":
        g = mat("#ffcc33", 0.2, metal=0.9)
        cyl(0.12, 0.08, (0, -0.1, -0.05), g, p)
        cyl(0.04, 0.2, (0, -0.1, 0.07), g, p)
        cyl(0.15, 0.22, (0, -0.1, 0.27), g, p, r2=0.08)
    elif kind == "gift":
        box((0.35, 0.35, 0.3), (0, -0.2, 0.1), mat("#e53935", 0.5), p, bevel=0.01)
        box((0.36, 0.08, 0.31), (0, -0.2, 0.1), mat("#ffd54f", 0.4), p, bevel=0.0)
        box((0.08, 0.36, 0.31), (0, -0.2, 0.1), mat("#ffd54f", 0.4), p, bevel=0.0)
    elif kind == "cake":
        cyl(0.35, 0.25, (0, 0, 0.12), mat("#f8bbd0", 0.6), p)
        cyl(0.36, 0.06, (0, 0, 0.26), mat("#ffffff", 0.6), p)
        for i in range(5):
            a = i / 5 * math.tau
            cyl(0.02, 0.14, (0.2 * math.cos(a), 0.2 * math.sin(a), 0.36), mat("#4fc3f7"), p)
            sphere(0.03, (0.2 * math.cos(a), 0.2 * math.sin(a), 0.46), mat("#ffb74d", 0.2, emit=8), p)
    elif kind == "balloon":
        sphere(0.3, (0, 0, 1.2), mat("#e53935", 0.2), p, scale=(1, 1, 1.2))
        cyl(0.005, 1.0, (0, 0, 0.5), mat("#ffffff"), p)
    elif kind == "paper":
        box((0.3, 0.01, 0.4), (0, -0.1, 0.05), mat("#ffffff", 0.8), p, bevel=0)
    elif kind == "shoes":
        for s in (-0.13, 0.13):
            box((0.2, 0.4, 0.15), (s, -0.1, 0), mat("#e53935", 0.4), p)
    elif kind == "letter":
        box((0.36, 0.01, 0.24), (0, -0.1, 0.05), mat("#fff3e0", 0.8), p, bevel=0)
        sphere(0.04, (0, -0.115, 0.05), mat("#d32f2f"), p, scale=(1, 0.3, 1))
    elif kind == "icecream":
        cyl(0.08, 0.25, (0, -0.1, 0), mat("#d9a066", 0.6), p, r2=0.0, rot=(math.pi, 0, 0))
        sphere(0.1, (0, -0.1, 0.16), mat("#f8bbd0", 0.5), p)
    return p


def sparkles(c, color="#7fe7ff", n=16):
    m = mat(color, 0.2, emit=3.5)
    head = c.root
    pts = []
    for i in range(n):
        s = sphere(0.04, (0, 0, 0), m)
        ph = i / n
        r = RND.uniform(0.45, 0.7)
        h = RND.uniform(0.3, 1.9)
        for f in range(1, NF + 2, 2):
            t = (f - 1) / FPS
            a = (ph + t * 0.3) * math.tau
            base = Vector(head.matrix_world.translation)
            s.location = base + Vector((r * math.cos(a), r * math.sin(a), h + 0.2 * math.sin(t * 3 + i)))
            sc = 0.6 + 0.6 * abs(math.sin(t * 4 + i))
            s.scale = (sc, sc, sc)
            s.keyframe_insert("location", frame=f)
            s.keyframe_insert("scale", frame=f)
    L = bpy.data.lights.new("glow", "POINT")
    L.energy = 18
    L.color = hexcol(color)
    L.shadow_soft_size = 0.5
    lo = link(bpy.data.objects.new("glow", L))
    lo.location = Vector(head.location) + Vector((0.4, -1.0, 1.0))


def bubble(c):
    hp = Vector(c.root.location) + Vector((0.45, 0, (c.legh + 0.3 + 2 + 1.6) * c.scale + 0.35))
    box((0.6, 0.12, 0.34), hp, mat("#ffffff", 0.5), bevel=0.14)
    for i in range(3):
        sphere(0.045, hp + Vector((-0.15 + i * 0.15, -0.08, 0)), mat("#111111", 0.4))
    sphere(0.06, hp + Vector((-0.25, 0, -0.25)), mat("#ffffff", 0.5))


def tag(c, text, color="#7fe7ff"):
    """Glowing number floating above the head (follows the head)."""
    cu = bpy.data.curves.new("tag", type="FONT")
    cu.body = text
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.size = 0.6
    cu.extrude = 0.04
    for fp in ("/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Black.ttf",
               "/usr/share/fonts/truetype/roboto/hinted/Roboto-Black.ttf"):
        if os.path.exists(fp):
            cu.font = bpy.data.fonts.load(fp)
            break
    ob = link(bpy.data.objects.new("tag", cu))
    ob.parent = c.neck
    ob.location = (0, -0.12, 1.95)
    ob.rotation_euler = (math.radians(90), 0, 0)
    m = bpy.data.materials.new("tagm")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    col = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1,)
    bsdf.inputs["Base Color"].default_value = (0.07, 0.09, 0.14, 1)
    ob.data.materials.append(m)
    w = 0.55 + 0.36 * len(text)
    box((w, 0.08, 0.78), (0, 0.0, 1.95), mat(color, 0.5, emit=0.6), c.neck, bevel=0.18)


# ----------------------------------------------------------------- camera

def setup_camera(cfg, chars, chars_by_name, interior):
    cam_d = bpy.data.cameras.new("cam")
    cam = link(bpy.data.objects.new("cam", cam_d))
    bpy.context.scene.camera = cam
    shot = cfg.get("shot", "medium")
    on = cfg.get("on")
    targets = [chars_by_name[n] for n in (on if isinstance(on, list) else [on]) if n in chars_by_name] if on else []
    if not targets:
        targets = chars[:1] if shot != "wide" else chars

    def head_pos(ch):
        ch.root.matrix_world  # ensure update
        bpy.context.view_layer.update()
        return ch.neck.matrix_world @ Vector((0, 0, 0.66))

    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    heads = [head_pos(t) for t in targets]
    tgt = sum(heads, Vector()) / len(heads)
    if len(targets) == 1:
        tgt.z -= {"extreme": 0.0, "close": 0.12, "medium": 0.3, "wide": 0.5, "full": 0.5}.get(shot, 0.3)
    else:
        tgt.z -= 0.2
    if cfg.get("prop_focus"):
        tgt.z -= 0.35
    spread = max([(h - tgt).length for h in heads] + [0])
    dist = {"extreme": 1.3, "close": 1.9, "medium": 3.0, "full": 4.4, "wide": 6.5}.get(shot, 3.0)
    lens = {"extreme": 55, "close": 50, "medium": 40, "full": 35, "wide": 28}.get(shot, 40)
    if len(targets) > 1:
        lens = min(lens, 30)
        half_w = 36 * 9 / 16 / 2  # portrait frame: 36mm sensor maps to the height
        dist = max(dist, (spread + 0.5) / (half_w / lens))
    cam_d.lens = lens
    # base direction: in front of the (first) target character
    yaw = targets[0].root.rotation_euler.z if len(targets) == 1 else 0.0
    if cfg.get("front") == "scene":
        yaw = 0.0
    yaw += math.radians(cfg.get("angle", 0))
    if cfg.get("over"):  # over-the-shoulder from another character
        o = chars_by_name[cfg["over"]]
        op = head_pos(o)
        d = (op - tgt)
        d.z = 0
        d.normalize()
        side = Vector((-d.y, d.x, 0)) * 0.75
        base_pos = op + d * 1.5 + side + Vector((0, 0, 0.15))
        dirv = None
    else:
        dirv = Vector((math.sin(yaw), -math.cos(yaw), 0))
    hgt = {"eye": 0.05, "low": -0.55, "high": 0.9, "top": 2.6}.get(cfg.get("height", "eye"), 0.05)
    move = cfg.get("move", "drift")
    dof = cam_d.dof
    dof.use_dof = True
    dof.aperture_fstop = {"extreme": 4.0, "close": 5.6, "medium": 8.0, "full": 11.0, "wide": 16.0}.get(shot, 8.0)
    if interior and dirv is not None:
        # keep the camera inside the open front of the set
        dirv.y = min(dirv.y, -0.2)
        dirv.normalize()
    follow = cfg.get("follow", any(getattr(t_, "moving", False) for t_ in targets))
    tgt0 = Vector(tgt)
    for f in range(1, NF + 2, 2):
        u = (f - 1) / max(1, NF - 1)
        t = (f - 1) / FPS
        if follow:
            bpy.context.scene.frame_set(f)
            hs = [head_pos(t_) for t_ in targets]
            tgt = sum(hs, Vector()) / len(hs) + (tgt0 - sum(heads, Vector()) / len(heads))
        k = dist
        lat = 0.0
        ang = 0.0
        if move == "push":
            k = dist * (1.18 - 0.3 * u)
        elif move == "pull":
            k = dist * (0.9 + 0.3 * u)
        elif move == "pan_l":
            lat = -0.5 + 1.0 * u
        elif move == "pan_r":
            lat = 0.5 - 1.0 * u
        elif move == "orbit":
            ang = math.radians(-18 + 36 * u)
        elif move == "zoom":  # dramatic fast push in at the start
            k = dist * (1.0 + 0.6 * max(0, 1 - u * 4))
        if dirv is not None:
            dv = Vector(dirv)
            dv.rotate(Euler((0, 0, ang)))
            side = Vector((-dv.y, dv.x, 0))
            pos = tgt + dv * k + side * lat + Vector((0, 0, hgt))
            look = tgt + side * lat * 0.6
        else:
            pos = base_pos
            look = tgt
        # handheld drift
        pos += Vector((0.02 * math.sin(t * 0.9), 0.015 * math.sin(t * 0.7 + 1), 0.015 * math.sin(t * 1.1 + 2)))
        if cfg.get("shake"):
            pos += Vector((0.03 * math.sin(t * 37), 0, 0.03 * math.sin(t * 29)))
        cam.location = pos
        dvec = look - pos
        q = dvec.to_track_quat("-Z", "Y")
        if cfg.get("tilt"):  # dutch angle
            q = q @ Quaternion((0, 0, 1), math.radians(cfg["tilt"]))
        cam.rotation_euler = q.to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        dof.focus_distance = max(0.3, dvec.length)
        cam_d.keyframe_insert("dof.focus_distance", frame=f)
    return cam


# ----------------------------------------------------------------- main

def main():
    sc = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = ARGS.get("res", [720, 1280])
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, NF
    ee = sc.eevee
    ee.taa_render_samples = ARGS.get("samples", 12)
    ee.use_gtao = True
    ee.gtao_distance = 0.6
    ee.use_bloom = True
    ee.bloom_intensity = 0.03
    ee.bloom_threshold = 1.2
    ee.use_soft_shadows = True
    ee.shadow_cube_size = "1024"
    ee.shadow_cascade_size = "2048"
    ee.use_ssr = False
    sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    try:
        sc.view_settings.look = "AgX - Punchy" if sc.view_settings.view_transform == "AgX" else "Medium High Contrast"
    except Exception:
        pass
    sc.view_settings.exposure = ARGS.get("exposure", -0.1)

    slots, interior = build_set(ARGS["set"], ARGS.get("time", "day"))
    chars = []
    by_name = {}
    used = set()
    free_slots = [s for s in "ABCDEFG" if s in slots]
    for cfg in ARGS["chars"]:
        spec = dict(ARGS["cast"][cfg["who"]])
        at = cfg.get("at")
        if at is None:
            at = next(s for s in free_slots if s not in used)
        used.add(at if isinstance(at, str) else str(at))
        if isinstance(at, str):
            s = slots[at]
        else:
            s = (at[0], at[1], at[2] if len(at) > 2 else 0) + ((at[3],) if len(at) > 3 else ())
        yaw = cfg.get("yaw", s[2] if len(s) > 2 else 0)
        c = make_char(cfg["who"], spec, s[0], s[1], yaw)
        if len(s) > 3:
            cfg["_seat"] = s[3]
        chars.append(c)
        by_name[cfg["who"]] = c
    for cfg, c in zip(ARGS["chars"], chars):
        set_face(c, cfg.get("face", "neutral"), cfg.get("talk", False), 1, NF + 1)
        animate(c, cfg, slots, by_name, ARGS.get("cam", {}))
        if cfg.get("prop"):
            make_prop(cfg["prop"], c.arms["r"][1], inv_scale=1 / c.scale)
        if cfg.get("fx") == "sparkle":
            sparkles(c, cfg.get("fx_color", "#7fe7ff"))
        if cfg.get("bubble"):
            bubble(c)
        if cfg.get("tag") is not None:
            tag(c, str(cfg["tag"]), cfg.get("tag_color", "#7fe7ff"))
    for pr in ARGS.get("props", []):
        make_prop(pr["kind"], None, tuple(pr["at"]))
    for fc in bpy.data.actions:
        for cu in fc.fcurves:
            for kp in cu.keyframe_points:
                if kp.interpolation != "CONSTANT" and "hide" not in cu.data_path:
                    kp.interpolation = "LINEAR"
                if "hide" in cu.data_path:
                    kp.interpolation = "CONSTANT"
    cam = setup_camera(ARGS.get("cam", {}), chars, by_name, interior)
    rng = ARGS.get("range")
    if rng:
        sc.frame_start, sc.frame_end = rng[0], rng[1]
    # where each head is on screen (for 2D speech bubbles)
    from bpy_extras.object_utils import world_to_camera_view
    mid = ARGS.get("still_frame") if ARGS.get("still") else (rng[0] if rng else 1) + 2
    sc.frame_set(mid)
    bpy.context.view_layer.update()
    heads = {}
    for cfg, c in zip(ARGS["chars"], chars):
        top = c.neck.matrix_world @ Vector((0, 0, 1.45))
        v = world_to_camera_view(sc, cam, top)
        heads[cfg["who"]] = [v.x, 1 - v.y, v.z]
    hp = (ARGS["out"][:-4] + "_heads.json") if ARGS.get("still") else os.path.join(ARGS["out"], "heads.json")
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    json.dump(heads, open(hp, "w"))
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.filepath = os.path.join(ARGS["out"], "f_")
    sc.render.use_overwrite = False  # resume a half-rendered shot
    if ARGS.get("still"):
        sc.frame_set(ARGS.get("still_frame", 1))
        sc.render.filepath = ARGS["out"]
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)


main()
