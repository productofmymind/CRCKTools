"""Planned changes: describe for preview, then apply. Only apply() writes to Blender data.

Fix ops (dicts produced by analysis.Finding.fix or by the material order UI):
  reparent_bone  {bone, parent}  edit-bone parent change; rest pose and bone data unchanged
  auto_tag       {bone}          turn off Sollumz manual tag so the tag follows the name hash
  bind_objects   {bone, objects}  couple objects to a bone: replace their Sollumz bone constraint (Copy Transforms)
                 with one targeting `bone`; world transform kept
  rename_bone    {bone, to}      drop a Blender ".001" suffix; Blender renames matching vertex groups and bone
                 constraint targets with the bone
  unnest_model   {object}        re-parent a nested Drawable Model to the Drawable, world transform kept
  move_bone      {bone, delta}  move a bone among its siblings (recreates the affected siblings; verified)
  merge_materials {keep, drop}   point every slot of every exported model at `keep` instead of the dropped
                 duplicates (polygon material indices unchanged)
  lock_material_order {}         write the current export order into shader indices (removes ties)
  set_material_order {names}     write an explicit order into shader indices
  enable_physics {bone}          turn Use Physics on, so the collisions bound to the bone become physics children
                 (Sollumz skips collisions on bones without it)
  make_glass_collision {bone, object}  build the bone's collision from the pane of the window model bound to it:
                 a CAR_GLASS bound geometry, mass 1.0, bound to the bone, Use Physics on (vanilla glass is exactly this)
  add_wheel_collision {bone, donor}  copy the collision(s) of another wheel bone to this wheel bone (moved by the distance between the two bones,
                 rotation kept), bound to it, Use Physics on. Wheels need no mesh of their own: only wheel_lf carries the wheel model
  glass_shader {bone, objects}   give the window models vehicle_vehglass copies of their non-glass materials (opt-in)
  fill_textures {material}       give every empty sampler the texture name vanilla vehicles use for that shader and sampler
                 (blank and normal_flat_small are generated and embedded); samplers that hold a texture are untouched
  rename_part {bone, to}         rename a part as one thing: the bone, the models and collisions named after it ("x", "x.col.001",
                 "x.child" follow as "to", "to.col.001", "to.child"), their mesh data and any vertex group that Blender did not
                 already rename. The tag follows the name unless it is manual.
  adopt_bound {object}           move a collision under the Bound Composite (Sollumz exports only those), world transform kept
  bind_objects may carry "optin": True: the item is listed but unticked (it changes a binding that works, just not by name)
"""
import bpy
from mathutils import Matrix

from . import analysis, paint, rules, sollumz_bridge as sz, textures

GLASS_MASS = 1.0  # every window collision in vanilla merula; cargobob5's vary (3 to 11) with the pane size


def material_targets(v, fix):
    """(current, new) export-material lists for a material fix."""
    base, hi = analysis.export_order(v)
    current = base + [m for m in hi if m not in base]
    if fix["op"] == "lock_material_order":
        return current, list(current)
    by_name = {m.name: m for m in current}
    new = [by_name[n] for n in fix["names"] if n in by_name]
    return current, new + [m for m in current if m not in new]


def describe(v, fix):
    """(text, kind, destructive) for the preview list. kind: hierarchy | tag | object | material."""
    op = fix["op"]
    if op == "reparent_bone":
        bone = v.frag.data.bones[fix["bone"]]
        seen = rules.load().seen(fix["bone"])
        vanilla = (" Vanilla: " + ", ".join(f"{p} x{n}" for p, n in sorted(seen.items(), key=lambda kv: -kv[1])[:4]) + ".") if seen else ""
        return (f"Bone {fix['bone']}: parent {bone.parent.name if bone.parent else '-'} -> {fix['parent']} "
                f"(bone indices after it shift; tags, rest pose, vertex groups and constraints unchanged).{vanilla}",
                "hierarchy", False)
    if op == "auto_tag":
        b = v.frag.data.bones[fix["bone"]]
        return f"Bone {fix['bone']}: tag {b.bone_properties.manual_tag} -> {sz.tag_hash(b.name)} (auto from name)", "tag", False
    if op == "rename_bone":
        return (f"Bone {fix['bone']} -> {fix['to']}: tag {sz.tag_hash(fix['bone'])} -> {sz.tag_hash(fix['to'])} "
                "(vertex groups and bone constraints follow the rename)", "name", False)
    if op == "bind_objects":
        return (f"Couple {len(fix['objects'])} object(s) to bone {fix['bone']}: "
                f"{', '.join(fix['objects'][:4])}{'...' if len(fix['objects']) > 4 else ''} "
                "(world transforms kept; replaces their current bone constraint)", "object", bool(fix.get("optin")))
    if op == "adopt_bound":
        return f"Collision {fix['object']}: parent -> {v.composite.name} (world transform kept)", "object", False
    if op == "rename_part":
        objs = part_objects(v, fix["bone"])
        shown = ", ".join(f"{o.name} -> {fix['to']}{o.name[len(fix['bone']):]}" for o in objs[:3]) + ("..." if len(objs) > 3 else "")
        b = v.frag.data.bones[fix["bone"]]
        tag = (f"; tag {b.bone_properties.tag} -> {sz.tag_hash(fix['to'])}" if not b.bone_properties.use_manual_tag else "; manual tag stays")
        return (f"Part {fix['bone']} -> {fix['to']}: the bone{tag}" + (f", {len(objs)} object(s): {shown}" if objs else "")
                + " (vertex groups and bone constraints follow)", "name", False)
    if op == "fill_textures":
        mat = bpy.data.materials[fix["material"]]
        todo = [(n.name, textures.default_name(mat.shader_properties.filename, n.name)) for n in mat.node_tree.nodes
                if n.type == "TEX_IMAGE" and not n.sollumz_texture_name]
        todo = [f"{s} -> {t}" for s, t in todo if t]
        return (f"Material {fix['material']}: default textures for empty samplers: {', '.join(todo)} (names only, except blank and "
                "normal_flat_small, which are generated and embedded in the yft)", "material", False)
    if op == "move_bone":
        from . import boneorder
        shifted = boneorder.simulated_index_shift(v.frag, fix["bone"], fix["delta"])
        return (f"Bone {fix['bone']}: move {fix['delta']:+d} among its siblings; {shifted} bone indices change "
                "(physics group order and any index-based data follow; names, tags, constraints and vertex groups stay)",
                "hierarchy", False)
    if op == "set_axes":
        return (f"Bone {fix['bone']}: local axes -> {fix['mode'].lower()} (geometry, children and collisions stay in place; "
                "rotation limits are in local axes, so re-check them)", "hierarchy", False)
    if op == "merge_materials":
        return (f"Merge duplicate materials into {fix['keep']}: {', '.join(fix['drop'])} "
                "(slots repointed, polygon indices unchanged; the dropped materials stay in the file, unused)", "material", False)
    if op == "unnest_model":
        return f"Object {fix['object']}: parent -> {v.drawable.name} (world transform kept)", "object", False
    if op == "enable_physics":
        cols = [c.name for c in v.bounds if sz.child_of_bone(c) is not None and sz.child_of_bone(c).name == fix["bone"]]
        return (f"Bone {fix['bone']}: Use Physics on, so its {len(cols)} bound collision(s) are exported as a physics child "
                "(it becomes a breakable part with its own group; set the mass afterwards if it shows 0)", "physics", False)
    if op == "make_glass_collision":
        verts, faces = glass_pane(bpy.data.objects[fix["object"]])
        return (f"Bone {fix['bone']}: new collision '{fix['bone']}.col' from the pane of {fix['object']} ({len(faces)} triangles, "
                f"{glass_collision_name(fix['bone'])}, mass {GLASS_MASS}), bound to the bone, Use Physics on", "physics", False)
    if op == "add_wheel_collision" and not fix.get("donor"):
        return (f"Bone {fix['bone']}: Use Physics on, and a new disc collision sized from {fix['model']} (axle along X, collision material DEFAULT, "
                "mass from its size), bound to this bone; the wheel mesh stays on wheel_lf", "physics", False)
    if op == "add_wheel_collision":
        n = len([c for c in v.bounds if sz.child_of_bone(c) is not None and sz.child_of_bone(c).name == fix["donor"]])
        return (f"Bone {fix['bone']}: Use Physics on, and {n} collision(s) copied from {fix['donor']} (moved to this bone, same size and "
                "orientation, named after it); the wheel mesh stays on wheel_lf. Adjust the radius if this wheel is a different size", "physics", False)
    if op == "glass_shader":
        return (f"Bone {fix['bone']}: {', '.join(fix['objects'][:3])} get vehicle_vehglass copies of their materials "
                "(textures kept where the shaders share a sampler; this changes how the window looks, and vanilla windows use an "
                "inner and an outer pane)", "material", True)
    current, new = material_targets(v, fix)
    moved = [f"{m.name} #{current.index(m)}->#{i}" for i, m in enumerate(new) if current.index(m) != i]
    ties = len({m.shader_properties.index for m in current}) < len(current)
    if not moved and not ties and all(m.shader_properties.index == i for i, m in enumerate(current)):
        return "Material order: no change", "material", False
    return ("Material order (Sollumz shader index): " + (", ".join(moved) if moved else "same order, indices made unique"),
            "material", False)


def dedupe(fixes):
    out, seen = [], set()
    for f in fixes:
        key = tuple(sorted((k, str(v)) for k, v in f.items()))
        if f["op"] in ("lock_material_order", "set_material_order"):
            key = ("materials",)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def apply(context, v, fixes):
    """Apply fixes; returns report lines. Caller wraps this in an UNDO operator."""
    report = []
    frag = v.frag
    reparent = [f for f in fixes if f["op"] == "reparent_bone"]
    if reparent:
        before = [b.name for b in frag.data.bones]
        _edit_bones(context, frag, lambda ebs: [_reparent(ebs, f, report) for f in reparent])
        after = [b.name for b in frag.data.bones]
        shifted = sum(1 for i, n in enumerate(after) if before[i] != n)
        report.append(f"{shifted} bone indices changed (depth-first order follows the new hierarchy).")
    for f in fixes:
        op = f["op"]
        if op == "auto_tag":
            b = frag.data.bones[f["bone"]]
            old = b.bone_properties.manual_tag
            b.bone_properties.use_manual_tag = False
            report.append(f"{b.name}: tag {old} -> {b.bone_properties.tag}")
        elif op == "move_bone":
            from . import boneorder
            lines, _ok = boneorder.move(context, frag, f["bone"], f["delta"])
            report.extend(lines)
        elif op == "set_axes":
            from . import axes
            lines, _ok = axes.set_axes(context, frag, f["bone"], f["mode"])
            report.extend(lines)
        elif op == "merge_materials":
            report.append(merge_materials(v, f["keep"], f["drop"]))
        elif op == "bind_objects":
            report.append(bind_objects(frag, f["bone"], [bpy.data.objects[n] for n in f["objects"] if n in bpy.data.objects]))
        elif op == "fill_textures":
            done = textures.apply_defaults(bpy.data.materials[f["material"]])
            report.append(f"{f['material']}: {', '.join(f'{s} -> {t}' for s, t in done) or 'nothing to fill'}")
        elif op == "adopt_bound":
            report.append(adopt_bound(v, f["object"]))
        elif op == "unnest_model":
            report.append(f"{f['object']}: re-parented to {reparent_keep_world(v, f['object'], v.drawable)}")
        elif op == "enable_physics":
            bone = frag.data.bones[f["bone"]]
            bone.sollumz_use_physics = True
            report.append(f"{bone.name}: Use Physics on")
        elif op == "make_glass_collision":
            report.append(make_glass_collision(v, f["bone"], f["object"]))
        elif op == "add_wheel_collision":
            report.append(add_wheel_collision(v, f["bone"], f.get("donor"), f.get("model")))
        elif op == "glass_shader":
            report.append(glass_shader(v, f["objects"]))
        elif op in ("lock_material_order", "set_material_order"):
            current, new = material_targets(v, f)
            for i, m in enumerate(new):
                m.shader_properties.index = i
            report.append(f"Material order written to {len(new)} shader indices.")
    # Renames last: every other op refers to bones by their current name.
    for f in fixes:
        if f["op"] == "rename_part":
            report.extend(rename_part(v, f["bone"], f["to"]))
    for f in fixes:
        if f["op"] == "rename_bone":
            bone = frag.data.bones.get(f["bone"])
            if bone is None or f["to"] in frag.data.bones:
                report.append(f"Skipped rename {f['bone']}: missing, or '{f['to']}' exists.")
                continue
            bone.name = f["to"]
            report.append(f"{f['bone']} renamed to {bone.name}")
    return report


def merge_materials(v, keep, drop):
    keep_m, drop_m = bpy.data.materials.get(keep), {bpy.data.materials.get(n) for n in drop} - {None}
    slots = 0
    seen = set()
    for m in v.models:
        for _, mesh in sz.lod_meshes(m):
            if mesh in seen:
                continue
            seen.add(mesh)
            for i, mat in enumerate(mesh.materials):
                if mat in drop_m:
                    mesh.materials[i] = keep_m
                    slots += 1
    return f"{len(drop_m)} duplicate material(s) merged into {keep}; {slots} slot(s) repointed"


def bind_objects(frag, bone, objs):
    """Bind each object to `bone` the way Sollumz does (Copy Transforms via tools.blenderhelper), keeping world transforms."""
    done = 0
    bpy.context.view_layer.update()
    for o in objs:
        world = o.matrix_world.copy()
        sz.unbind(o)
        sz.bind(o, frag, bone)
        o.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()
        # With the constraint evaluated before the original transform, world = constraint_matrix @ basis.
        o.matrix_basis = o.matrix_world.inverted() @ world
        bpy.context.view_layer.update()
        done += 1
    return f"{done} object(s) coupled to {bone}"


def reparent_keep_world(v, name, parent):
    """Parent an object to `parent`, world transform kept. An object bound to a bone gets its bone constraint rebuilt the way
    bind_objects does, because setting the world matrix of a constrained object would not stick."""
    obj = bpy.data.objects[name]
    bpy.context.view_layer.update()  # bone edits just before this leave matrix_world of bound objects stale
    world, bone = obj.matrix_world.copy(), sz.child_of_bone(obj)
    if bone is not None:
        sz.unbind(obj)
    obj.parent = parent
    obj.matrix_world = world
    if bone is not None:
        bind_objects(v.frag, bone.name, [obj])
    return parent.name


def adopt_bound(v, name):
    return f"{name}: parent -> {reparent_keep_world(v, name, v.composite)}"


def merge_binds(planned):
    """One bind_objects fix per (bone, optin) instead of one per object."""
    out, by_key = [], {}
    for f in planned:
        if f["op"] != "bind_objects":
            out.append(f)
            continue
        key = (f["bone"], bool(f.get("optin")))
        if key in by_key:
            by_key[key]["objects"] = sorted(set(by_key[key]["objects"]) | set(f["objects"]))
        else:
            by_key[key] = dict(f, objects=list(f["objects"]))
            out.append(by_key[key])
    return out


def part_objects(v, bone_name):
    """Models and collisions that belong to a part by name: bound to the bone and named after it (name stem equal to the bone)."""
    names = set(v.frag.data.bones.keys())
    return [o for o in v.models + v.bounds if bone_name in analysis.bone_links(o, names) and analysis.name_stem(o.name) == bone_name]


def rename_problems(v, bone_name, to):
    """Why a part cannot be renamed to `to`, or []."""
    arm = v.frag.data
    if not to or to == bone_name:
        return ["nothing to rename"]
    if bone_name not in arm.bones:
        return [f"no part '{bone_name}'"]
    if to in arm.bones:
        return [f"a bone '{to}' exists"]
    clash = [o.name for o in part_objects(v, bone_name) if to + o.name[len(bone_name):] in bpy.data.objects]
    return [f"objects already named {', '.join(clash[:3])}"] if clash else []


def rename_plan(v, bones, find, replace):
    """(fixes, notes) for renaming `bones`: with `find`, every occurrence of it in the name becomes `replace`; without, the one part becomes `replace`."""
    out, notes, taken = [], [], set()
    for b in bones:
        to = b.replace(find, replace) if find else replace
        if to == b:
            continue
        bad = rename_problems(v, b, to) + ([f"two parts would be called '{to}'"] if to in taken else [])
        if bad:
            notes.append(f"{b} -> {to}: {'; '.join(bad)}")
            continue
        taken.add(to)
        out.append({"op": "rename_part", "bone": b, "to": to})
    return out, notes


def rename_part(v, bone_name, to):
    """The bone, the objects named after it, their mesh data and stray vertex groups, together. Returns report lines."""
    bad = rename_problems(v, bone_name, to)
    if bad:
        return [f"Skipped {bone_name} -> {to}: {'; '.join(bad)}."]
    arm = v.frag.data
    objs = part_objects(v, bone_name)  # found before the rename, while the vertex groups still carry the old name
    arm.bones[bone_name].name = to  # Blender renames the vertex groups of deformed meshes and the constraints that target the bone
    done = []
    for o in objs:
        old = o.name
        o.name = to + old[len(bone_name):]
        for me in {id(m): m for m in [o.data] + [m for _, m in sz.lod_meshes(o)]}.values():
            if me.name.startswith(bone_name):
                me.name = to + me.name[len(bone_name):]
        done.append(o.name)
    stray = 0
    for o in v.models:
        vg = o.vertex_groups.get(bone_name)
        if vg is not None:
            vg.name = to
            stray += 1
    return [f"{bone_name} -> {to}: bone, {len(done)} object(s)" + (f", {stray} vertex group(s) Blender had not renamed" if stray else "")]


def glass_collision_name(bone_name):
    """Collision material by bone name, as vanilla merula does it: windscreens strong, side windows weak."""
    return "CAR_GLASS_STRONG" if bone_name.startswith("windscreen") else "CAR_GLASS_WEAK"


def glass_pane(model):
    """(vertices, triangles) of a window model's pane in its local space: the outer glass material's faces if it has one,
    else every face; inner and outer panes sitting on the same spot merge into one."""
    import bmesh
    lods = sz.lod_meshes(model)
    if not lods:
        return [], []
    mesh = lods[0][1]
    glass = {i for i, m in enumerate(mesh.materials) if sz.is_shader_material(m) and m.shader_properties.name == "vehicle_vehglass"}
    bm = bmesh.new()
    bm.from_mesh(mesh)
    drop = [f for f in bm.faces if glass and f.material_index not in glass]
    if drop:
        bmesh.ops.delete(bm, geom=drop, context="FACES")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.delete(bm, geom=[x for x in bm.verts if not x.link_faces], context="VERTS")
    index = {x: i for i, x in enumerate(bm.verts)}
    out = [x.co.copy() for x in bm.verts], [[index[x] for x in f.verts] for f in bm.faces]
    bm.free()
    return out


def make_glass_collision(v, bone_name, model_name):
    model = bpy.data.objects[model_name]
    verts, faces = glass_pane(model)
    if not faces or v.composite is None:
        return f"{bone_name}: no collision made ({model_name} has no faces or the vehicle has no Bound Composite)."
    name = f"{bone_name}.col"
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.materials.append(sz.collision_material(glass_collision_name(bone_name)))
    obj = sz.new_bound_geometry(name, mesh, v.composite.users_collection[0])
    obj.child_properties.mass = GLASS_MASS
    obj.parent = v.composite
    obj.matrix_world = model.matrix_world
    v.frag.data.bones[bone_name].sollumz_use_physics = True
    bind_objects(v.frag, bone_name, [obj])
    return f"{bone_name}: collision '{obj.name}' ({len(faces)} triangles, {glass_collision_name(bone_name)}) bound to the bone, Use Physics on"


WHEEL_DENSITY = 940.0  # vanilla wheel discs: mass = 940 * radius^2 * length (merula, savage: within 0.3%)


def new_wheel_disc(v, bone_name, model_name):
    """A disc collision on `bone_name`, sized from the world-space box of a wheel model: axle along X, radius from the larger of Y and Z."""
    frag = v.frag
    model = bpy.data.objects[model_name]
    bpy.context.view_layer.update()
    pts = [model.matrix_world @ vert.co for _, me in sz.lod_meshes(model)[:1] for vert in me.vertices]
    if not pts or v.composite is None:
        return f"{bone_name}: no collision made ({model_name} has no vertices, or the vehicle has no Bound Composite)."
    ext = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    radius, length = max(ext[1], ext[2]) * 0.5, ext[0]
    name = f"{bone_name}.col"
    obj = sz.new_bound_disc(name, radius, length, v.composite.users_collection[0])
    obj.parent = v.composite
    obj.child_properties.mass = round(WHEEL_DENSITY * radius * radius * length, 3)
    obj.matrix_world = Matrix.Translation(frag.matrix_world @ frag.data.bones[bone_name].head_local)
    frag.data.bones[bone_name].sollumz_use_physics = True
    bind_objects(frag, bone_name, [obj])
    return f"{bone_name}: Use Physics on, new disc '{obj.name}' (radius {radius:.3f}, length {length:.3f}, mass {obj.child_properties.mass}) from {model_name}"


def add_wheel_collision(v, bone_name, donor_bone, model_name=None):
    """Copy the collisions bound to `donor_bone` onto `bone_name` (or, with no donor, build a disc from `model_name`); the copies keep size and
    rotation and move by the offset between the bones."""
    frag = v.frag
    if not donor_bone:
        return new_wheel_disc(v, bone_name, model_name)
    bpy.context.view_layer.update()
    donors = [b for b in v.bounds if sz.child_of_bone(b) is not None and sz.child_of_bone(b).name == donor_bone]
    if not donors or v.composite is None:
        return f"{bone_name}: nothing copied ({donor_bone} has no collision, or the vehicle has no Bound Composite)."
    shift = frag.matrix_world @ frag.data.bones[bone_name].head_local - frag.matrix_world @ frag.data.bones[donor_bone].head_local
    made = []
    for i, d in enumerate(donors):
        world = d.matrix_world.copy()
        obj = d.copy()
        name = f"{bone_name}.col" if i == 0 else f"{bone_name}.col.{i:03d}"
        if d.data is not None:
            obj.data = d.data.copy()
            obj.data.name = name
        obj.name = name
        for c in list(obj.constraints):
            obj.constraints.remove(c)
        for coll in d.users_collection:
            coll.objects.link(obj)
        obj.parent = v.composite
        obj.matrix_world = Matrix.Translation(shift) @ world
        bind_objects(frag, bone_name, [obj])
        made.append(obj.name)
    frag.data.bones[bone_name].sollumz_use_physics = True
    return f"{bone_name}: Use Physics on, collision(s) {', '.join(made)} copied from {donor_bone}"


def glass_shader(v, names):
    copies, slots, seen = {}, 0, set()
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj is None:
            continue
        for _, me in sz.lod_meshes(obj):
            if me in seen:
                continue
            seen.add(me)
            for i, m in enumerate(me.materials):
                if not sz.is_shader_material(m) or m.shader_properties.name.startswith("vehicle_vehglass"):
                    continue
                if m not in copies:
                    copies[m] = m.copy()
                    sz.switch_shader(copies[m], "vehicle_vehglass.sps")
                    textures.apply_defaults(copies[m])
                    copies[m].shader_properties.index = paint.next_shader_index(v)
                me.materials[i] = copies[m]
                slots += 1
        for new in copies.values():
            sz.prepare_mesh_for_material(obj, new)
    return f"{len(copies)} glass material(s) made; {slots} slot(s) on {len(names)} model(s) use them"


def reparent_bone_to(context, frag, bone_name, parent_name):
    """Make `bone_name` a child of `parent_name` (None = unlink it into its own top-level tree). Rest pose, tags, bound objects
    and every other bone property stay as they are. Returns (report lines, verified)."""
    from . import boneorder
    arm = frag.data
    bone = arm.bones.get(bone_name)
    if bone is None or (parent_name is not None and parent_name not in arm.bones):
        return [f"{bone_name}: bone or target missing."], False
    if parent_name is not None:
        p = arm.bones[parent_name]
        while p is not None:
            if p.name == bone_name:
                return [f"{bone_name}: cannot move a part into itself or its own descendant ({parent_name})."], False
            p = p.parent
    before = boneorder.fingerprint(frag)
    old_parent = bone.parent.name if bone.parent else None

    def go(ebs):
        eb = ebs[bone_name]
        eb.use_connect = False
        eb.parent = ebs[parent_name] if parent_name else None

    _edit_bones(context, frag, go)
    after = boneorder.fingerprint(frag)

    def comparable(n, snap):
        d = dict(snap)
        if n == bone_name:  # its parent changes by design, and its tag is derived from it (a top-level bone gets tag 0)
            d.pop("parent", None)
            bone = dict(d["bone"])
            props = dict(bone.get("bone_properties", {}))
            props.pop("tag", None)
            bone["bone_properties"] = props
            d["bone"] = bone
        return d

    bad = [n for n in before if comparable(n, before[n]) != comparable(n, after.get(n, {}))]
    lines = [f"{bone_name}: parent {old_parent or '-'} -> {parent_name or '- (own top-level tree)'}"]
    if parent_name is None:
        lines.append("It is now a top-level bone: Sollumz gives those tag 0 (like the chassis), and a skeleton needs exactly "
                     "one root, so re-attach it before exporting.")
    lines.append("Verified: no other property changed." if not bad
                 else f"WARNING: {len(bad)} bone(s) differ: {', '.join(bad[:6])}. Use Ctrl+Z.")
    return lines, not bad


def _reparent(ebs, f, report):
    eb, parent = ebs.get(f["bone"]), ebs.get(f["parent"])
    if eb is None or parent is None:
        report.append(f"Skipped {f['bone']}: bone missing.")
        return
    p = parent
    while p is not None:
        if p == eb:
            report.append(f"Skipped {f['bone']}: {f['parent']} is its descendant.")
            return
        p = p.parent
    eb.use_connect = False
    eb.parent = parent
    report.append(f"{f['bone']}: parent -> {f['parent']}")


def _edit_bones(context, arm_obj, fn):
    """Run fn(edit_bones) in edit mode on arm_obj, restoring mode, active object and selection."""
    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_mode = context.mode
    prev_sel = [o for o in context.selected_objects]
    if prev_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in prev_sel:
        o.select_set(False)
    arm_obj.hide_set(False)
    arm_obj.select_set(True)
    view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn(arm_obj.data.edit_bones)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        arm_obj.select_set(False)
        for o in prev_sel:
            o.select_set(True)
        view_layer.objects.active = prev_active


# --- Outliner view: collections that mirror the bone tree ---------------------
# Only collection membership changes. Parents, constraints, transforms and names are never touched, and Sollumz
# never reads collections when exporting, so the export is unchanged.

def _owned(frag):
    return [c for c in bpy.data.collections if c.get("vht_frag") == frag.name]


def _unlink_from_parents(col, keep):
    for p in list(bpy.data.collections) + [s.collection for s in bpy.data.scenes]:
        if p is not keep and col.name in p.children:
            p.children.unlink(col)


def build_part_collections(v):
    """Create/refresh one collection per bone, nested like the bones, and put each bound object in its part's
    collection. Returns (collections created, objects moved). Idempotent."""
    frag, arm = v.frag, v.frag.data
    owned = {c["vht_bone"]: c for c in _owned(frag) if "vht_bone" in c}
    root = next((c for c in _owned(frag) if c.get("vht_root")), None)
    created = 0
    if root is None:
        root = bpy.data.collections.new(f"{frag.name} parts")
        root["vht_frag"], root["vht_root"] = frag.name, True
        created += 1
    _unlink_from_parents(root, bpy.context.scene.collection)
    if root.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(root)
    cols = {}
    for bone in arm.bones:  # armature order == export bone order
        c = owned.get(bone.name)
        if c is None:
            c = bpy.data.collections.new(bone.name)
            c["vht_frag"], c["vht_bone"] = frag.name, bone.name
            created += 1
        parent = cols[bone.parent.name] if bone.parent else root
        _unlink_from_parents(c, parent)
        if c.name not in parent.children:
            parent.children.link(c)
        cols[bone.name] = c
    index = {b.name: i for i, b in enumerate(arm.bones)}
    moved = 0
    for o in v.models + v.bounds:
        links = analysis.bone_links(o, set(index))
        if not links:
            continue
        target = cols[min(links, key=index.get)]  # same tie-break Sollumz uses for skinned models
        if list(o.users_collection) == [target]:
            continue
        if "vht_prev" not in o:
            o["vht_prev"] = [c.name for c in o.users_collection if not c.get("vht_frag")]
        for c in list(o.users_collection):
            c.objects.unlink(o)
        target.objects.link(o)
        moved += 1
    return created, moved


def remove_part_collections(frag):
    """Undo build_part_collections: objects go back to the collections they came from. Returns objects restored."""
    cols = _owned(frag)
    restored = 0
    for c in cols:
        for o in list(c.objects):
            prev = [n for n in (o.get("vht_prev") or []) if n in bpy.data.collections]
            c.objects.unlink(o)
            targets = [bpy.data.collections[n] for n in prev] or [bpy.context.scene.collection]
            for t in targets:
                if o.name not in t.objects:
                    t.objects.link(o)
            if "vht_prev" in o:
                del o["vht_prev"]
            restored += 1
    for c in sorted(cols, key=lambda c: -len(c.name)):
        bpy.data.collections.remove(c)
    return restored
