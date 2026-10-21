"""Edit a bone's local axes without moving anything you can see .

The local axes of a bone are its rest matrix: Sollumz exports its rotation as the bone's orientation and the game spins or swings a
part around those axes (a rotor turns on its local Z). If the axes are tilted or off-centre, the part turns about the wrong line.
The axes change and the geometry stays where it is:

  CENTER  move the origin to the centre of the part's geometry, keep the orientation
  PARENT  take the orientation of the parent bone (a top-level bone takes the world orientation)
  WORLD   world orientation (X right, Y forward, Z up), origin unchanged
  COPY    take the origin and orientation of another bone
  CURSOR  move the origin to the 3D cursor, keep the orientation 
  ALIGN   turn local Z onto the normal of the part's own blade disc, origin unchanged (the fix for a wobbling rotor)

What keeps its place: children bones (their rest pose is absolute), skinned geometry (at rest it does not depend on the rest matrix)
and rigid geometry and collisions bound by constraint (their basis is re-solved). What does not adapt: rotation or location limits
on the bone are written in its local axes, so they are reported for you to re-check.
"""
import math

import bpy
from mathutils import Matrix, Vector

from . import analysis, boneorder, sollumz_bridge as sz

MODES = ("CENTER", "PARENT", "WORLD", "COPY", "CURSOR", "ALIGN")
TOLERANCE = 1e-4


def _rot3(m):
    return m.to_3x3().normalized()


def target_matrix(frag, bone, mode, source=None, objs=(), rotation=True, position=False):
    """Armature-space 4x4 the bone should have afterwards. WORLD, PARENT and COPY take separate rotation and position
    switches; CENTER and CURSOR only move the origin."""
    cur = bone.matrix_local
    pos, rot = cur.to_translation(), _rot3(cur)
    world_rot = _rot3(frag.matrix_world)
    world_origin = frag.matrix_world.inverted() @ Vector((0, 0, 0))
    if mode == "WORLD":
        if rotation:
            rot = world_rot.inverted()
        if position:
            pos = world_origin
    elif mode == "PARENT":
        if rotation:
            rot = _rot3(bone.parent.matrix_local) if bone.parent else world_rot.inverted()
        if position:
            pos = bone.parent.matrix_local.to_translation() if bone.parent else world_origin
    elif mode == "CURSOR":
        pos = frag.matrix_world.inverted() @ bpy.context.scene.cursor.location
    elif mode == "ALIGN":
        normal = objs  # for ALIGN the caller passes the world-space disc normal here
        if normal is None:
            raise ValueError("no blade geometry to align to")
        n = frag.matrix_world.to_3x3().inverted() @ normal
        z = rot.col[2].copy()
        if z.dot(n) < 0:
            n = -n
        rot = z.rotation_difference(n.normalized()).to_matrix() @ rot  # smallest turn that puts local Z on the disc normal
    elif mode == "COPY":
        if rotation:
            rot = _rot3(source.matrix_local)
        if position:
            pos = source.matrix_local.to_translation()
    elif mode == "CENTER":
        pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
        if not pts:
            raise ValueError("no geometry to centre on")
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        pos = frag.matrix_world.inverted() @ ((lo + hi) / 2)
    return Matrix.Translation(pos) @ rot.to_4x4()


def pose_is_rest(pb):
    return all(abs(a - b) < TOLERANCE for r1, r2 in zip(pb.matrix_basis, Matrix.Identity(4)) for a, b in zip(r1, r2))


def angle_between(a, b):
    return a.angle(b, 0.0) if a.length and b.length else 0.0


def set_axes(context, frag, bone_name, mode, source_name=None, extra_objs=(), rotation=True, position=False):
    """Apply one of MODES to a bone. `rotation` / `position` choose what WORLD, PARENT and COPY change. Returns (report lines, verified)."""
    if mode in ("WORLD", "PARENT", "COPY") and not (rotation or position):
        return ["Switch on rotation, position or both."], False
    arm = frag.data
    bone = arm.bones.get(bone_name)
    if bone is None:
        return [f"{bone_name}: bone missing."], False
    pb = frag.pose.bones[bone_name]
    if not pose_is_rest(pb):
        return [f"{bone_name} is posed. Clear its pose transform (Alt+G/R/S) first so the rest axes can change safely."], False
    source = arm.bones.get(source_name) if source_name else None
    if mode == "COPY" and source is None:
        return ["Grab the part to copy the axes from first."], False
    if mode == "COPY" and source_name == bone_name:
        return [f"{bone_name}: choose a different part to copy from."], False
    v = analysis.load(frag)
    names = set(arm.bones.keys())
    own = [o for o in v.models + v.bounds if bone_name in analysis.bone_links(o, names)]
    bound = [o for o in own if sz.child_of_bone(o) is not None and sz.child_of_bone(o).name == bone_name]
    try:
        geo = [o for o in v.models if o in own] or list(extra_objs) or own
        if mode == "ALIGN":
            geo, _ = disc_normal(frag, bone_name, v.models)
        new = target_matrix(frag, bone, mode, source, geo, rotation, position)
    except ValueError as e:
        return [f"{bone_name}: {e}" + (" (select objects to centre on)." if mode == "CENTER" else ".")], False
    before = boneorder.fingerprint(frag)
    worlds = {o.name: o.matrix_world.copy() for o in bpy.data.objects}
    old_rot = _rot3(bone.matrix_local)
    has_limit = any(c.type in ("LIMIT_ROTATION", "LIMIT_LOCATION") for c in pb.constraints)

    from . import fixes

    def go(ebs):
        ebs[bone_name].use_connect = False
        ebs[bone_name].matrix = new  # head, roll and orientation; the bone keeps its length

    fixes._edit_bones(context, frag, go)
    context.view_layer.update()
    for o in bound:  # rigid geometry follows the bone through its constraint: re-solve the offset so it stays put
        o.matrix_basis = Matrix.Identity(4)
        context.view_layer.update()
        o.matrix_basis = o.matrix_world.inverted() @ worlds[o.name]
    context.view_layer.update()

    after = boneorder.fingerprint(frag)
    changed = [n for n in before if n != bone_name and before[n] != after.get(n)]
    moved = [n for n, w in worlds.items() if n in bpy.data.objects and any(
        abs(a - b) > 1e-3 for r1, r2 in zip(bpy.data.objects[n].matrix_world, w) for a, b in zip(r1, r2))]
    turned = angle_between(old_rot.col[2], _rot3(arm.bones[bone_name].matrix_local).col[2])
    lines = [f"{bone_name}: axes set ({mode.lower()}); {len(bound)} bound object(s) kept in place"]
    if has_limit and (mode != "CENTER"):
        lines.append("It has rotation/location limits. They are written in the bone's local axes, so check they still swing the part "
                     "the right way.")
    if changed or moved:
        lines.append(f"WARNING: other data changed (bones {changed[:4]}, objects {moved[:4]}). Use Ctrl+Z.")
    else:
        lines.append("Verified: no other bone and no object moved.")
    return lines, not (changed or moved)


def disc_normal(frag, bone_name, models=None):
    """(world-space unit normal of the plane the part's geometry lies in, vertex count). The normal is the smallest-variance
    direction of the vertices that follow the bone: weighted > 0.5 to its vertex group, or all vertices of a rigid model bound to it.
    Returns (None, count) when there is too little geometry."""
    import numpy as np
    arm = frag.data
    models = models if models is not None else analysis.load(frag).models
    pts = []
    for o in models:
        if o.type != "MESH":
            continue
        vg = o.vertex_groups.get(bone_name)
        if vg is not None:
            idx = vg.index
            sel = [v.co for v in o.data.vertices if any(g.group == idx and g.weight > 0.5 for g in v.groups)]
        elif sz.child_of_bone(o) is not None and sz.child_of_bone(o).name == bone_name:
            sel = [v.co for v in o.data.vertices]
        else:
            continue
        pts += [tuple(o.matrix_world @ c) for c in sel]
    if len(pts) < 10:
        return None, len(pts)
    a = np.array(pts)
    a -= a.mean(axis=0)
    _, vec = np.linalg.eigh(a.T @ a)
    return Vector(vec[:, 0]).normalized(), len(pts)


def spin_wobble(frag, bone_name, models=None):
    """Degrees between the bone's local Z (the axis a rotor spins on) and the normal of its blade disc, or None without geometry.
    A rotor turns about local Z, so any angle here makes the blades wobble. (Vanilla rotors are tilted on purpose but keep this at ~0.)"""
    bone = frag.data.bones.get(bone_name)
    n, _ = disc_normal(frag, bone_name, models)
    if bone is None or n is None:
        return None
    z = (frag.matrix_world.to_3x3() @ bone.matrix_local.to_3x3().col[2]).normalized()
    return math.degrees(min(z.angle(n, 0.0), z.angle(-n, 0.0)))
