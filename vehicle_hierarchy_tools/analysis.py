"""Read-only inspection and validation. Nothing here modifies Blender data."""
import re
from dataclasses import dataclass, field

from . import sollumz_bridge as sz, textures

ERROR, WARNING, INFO, REVIEW = "ERROR", "WARNING", "INFO", "REVIEW"
SEVERITIES = (ERROR, WARNING, INFO, REVIEW)

BOUND_PREFIX = "sollumz_bound_"


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    target: str = ""        # object, bone or material name
    kind: str = ""          # "object" | "bone" | "material"
    fix: dict | None = None  # see fixes.py


@dataclass
class Vehicle:
    frag: object
    drawable: object = None
    composite: object = None
    models: list = field(default_factory=list)      # Drawable Models that Sollumz exports
    nested_models: list = field(default_factory=list)  # Drawable Models Sollumz skips
    bounds: list = field(default_factory=list)


def load(frag):
    v = Vehicle(frag)
    drawables = [c for c in frag.children if sz.sollum_type(c) == sz.DRAWABLE and ".damaged" not in c.name]
    composites = [c for c in frag.children if sz.sollum_type(c) == sz.BOUND_COMPOSITE and ".damaged" not in c.name]
    v.drawable = drawables[0] if drawables else None
    v.composite = composites[0] if composites else None
    v.extra_drawables = drawables[1:]
    v.extra_composites = composites[1:]
    for o in frag.children_recursive:
        t = sz.sollum_type(o)
        if t == sz.DRAWABLE_MODEL:
            (v.models if o.parent == v.drawable else v.nested_models).append(o)
        elif t.startswith(BOUND_PREFIX) and t != sz.BOUND_COMPOSITE:
            v.bounds.append(o)
    return v


def bone_links(obj, bone_names):
    """Bones an object is bound to: its Sollumz bone constraint, else vertex groups named after bones."""
    b = sz.child_of_bone(obj)
    if b is not None:
        return [b.name]
    return [g.name for g in getattr(obj, "vertex_groups", ()) if g.name in bone_names]


_STEM_RX = re.compile(r"(\.(col|child|bound_geom|poly_mesh|bvh))?(\.\d{3})*$")


def name_stem(name):
    """An object's name without Blender's .001 and the suffixes Sollumz adds (.col, .child, .bound_geom ...)."""
    prev = None
    while prev != name:
        prev, name = name, _STEM_RX.sub("", name)
    return name


def bone_named(obj_name, bone_names):
    """The bone an object is named after. Sollumz names models and collisions after their bone ('window_lf', 'window_lf.col');
    all 550 bound models and 427 bound collisions on 12 vanilla vehicles follow it ('wheel_lf.child' is on wheel_lf).
    Exact match first, then case-insensitive if that is unambiguous."""
    stem = name_stem(obj_name)
    if stem in bone_names:
        return stem
    same = [b for b in bone_names if b.lower() == stem.lower()]
    return same[0] if len(same) == 1 else None


# --- hierarchy -------------------------------------------------------------

def tree(v):
    """Rows for the part view: bone tree with the objects bound to each bone."""
    arm = v.frag.data
    names = {b.name for b in arm.bones}
    attached = {}
    for o in v.models + v.bounds:
        for b in bone_links(o, names):
            attached.setdefault(b, []).append(o.name)
    index = {b.name: i for i, b in enumerate(arm.bones)}
    rows = []

    def walk(bone, depth):
        rows.append({"depth": depth, "bone": bone.name, "index": index[bone.name],
                     "objects": attached.get(bone.name, [])})
        for c in bone.children:
            walk(c, depth + 1)

    for b in arm.bones:
        if b.parent is None:
            walk(b, 0)
    return rows


def model_sort_key(obj, index):
    """Key Sollumz sorts models by: lowest bone index among vertex groups named after bones, else 0."""
    keys = [index[g.name] for g in obj.vertex_groups if g.name in index]
    return min(keys) if keys else 0


def order_report(v):
    """What Sollumz will write, in order, independent of Outliner sorting.
    Returns {"bones": [(index, name, depth, parent)], "models": [(name, kind, key)],
             "groups": [bone name], "materials": [name]}."""
    arm = v.frag.data
    index = {b.name: i for i, b in enumerate(arm.bones)}
    bones = []
    for b in arm.bones:
        depth, p = 0, b.parent
        while p is not None:
            depth, p = depth + 1, p.parent
        bones.append((index[b.name], b.name, depth, b.parent.name if b.parent else ""))
    models = []
    if v.drawable is not None:
        for o in sz.export_model_objs(v.drawable, v.frag):
            skinned = any(g.name in index for g in o.vertex_groups)
            models.append((o.name, "skinned" if skinned else "rigid", model_sort_key(o, index)))
    with_col = {sz.child_of_bone(b).name for b in v.bounds if sz.child_of_bone(b) is not None}
    groups = [b.name for b in arm.bones if b.sollumz_use_physics and b.name in with_col]  # bone index order
    base, _ = export_order(v)
    return {"bones": bones, "models": models, "groups": groups, "materials": [m.name for m in base]}


def validate_order(v):
    out = []
    if v.drawable is None:
        return out
    rep = order_report(v)
    by_key = {}
    for name, kind, key in rep["models"]:
        by_key.setdefault(key, []).append(name)
    for key, names in sorted(by_key.items()):
        if len(names) > 1:
            out.append(Finding(INFO, "MODEL_ORDER_BY_NAME",
                               f"{len(names)} models share sort key {key}, so Sollumz exports them in object-name order "
                               f"(case-insensitive): {', '.join(names[:6])}{'...' if len(names) > 6 else ''}. "
                               "Renaming one of them reorders the exported models.", names[0], "object"))
    return out


LOD_SLOTS = (("very_high", "0"), ("high", "1"), ("medium", "2"), ("low", "3"), ("very_low", "4"))


def hierarchy_rows(v):
    """Rows for the structure view, in bone order.

    The view is one tree: a node is a bone, a "compound" node holds one geometry slot per LOD (L0-L4) and a
    collision slot for its part, and nesting is what defines parents, bone indices and the binding of geometry and
    collision to a bone. In Blender those live in three places (armature, bound objects, Bound Composite), so the rows
    here put them back together: root (the fragment) > bone nodes in bone order > per part: LOD slots present
    (the compound) and one [COL] row per collision.

    Row: kind "root" | "node" | "col", depth, key (collapse key), label, bone, index (bone index or -1),
    objects (own geometry + collisions, "|"-joined), lods (digits of LOD slots present), n_geo, n_col, has_children.
    """
    arm = v.frag.data
    index = {b.name: i for i, b in enumerate(arm.bones)}
    geo, col = {}, {}
    for o in v.models:
        links = bone_links(o, set(index))
        if links:
            geo.setdefault(min(links, key=index.get), []).append(o)
    for o in v.bounds:
        b = sz.child_of_bone(o)
        if b is not None:
            col.setdefault(b.name, []).append(o)
    rows = [{"kind": "root", "depth": 0, "key": "(root)", "label": v.frag.name, "bone": "", "index": -1,
             "objects": "", "lods": "", "n_geo": 0, "n_col": 0, "has_children": bool(arm.bones)}]

    def lods_of(objs):
        present = set()
        for o in objs:
            present |= {attr for attr, _ in sz.lod_meshes(o)}
        return "".join(d for attr, d in LOD_SLOTS if attr in present)

    def walk(bone, depth):
        g, c = geo.get(bone.name, []), col.get(bone.name, [])
        rows.append({"kind": "node", "depth": depth, "key": bone.name, "label": bone.name, "bone": bone.name,
                     "index": index[bone.name], "objects": "|".join(o.name for o in g + c), "lods": lods_of(g),
                     "n_geo": len(g), "n_col": len(c), "has_children": bool(bone.children) or bool(c)})
        for child in bone.children:
            walk(child, depth + 1)
        for o in c:
            rows.append({"kind": "col", "depth": depth + 1, "key": f"{bone.name}|{o.name}",
                         "label": f"{bone.name} [COL]" if len(c) == 1 else f"{o.name} [COL]", "bone": bone.name,
                         "index": index[bone.name], "objects": o.name, "lods": "", "n_geo": 0, "n_col": 1,
                         "has_children": False})

    for b in arm.bones:
        if b.parent is None:
            walk(b, 1)
    return rows


def collapse_visible(rows, open_keys):
    """[bool] per row: False when an ancestor node is collapsed. `rows` need depth, key and has_children."""
    out, hide_below = [], None
    for r in rows:
        if hide_below is not None and r.depth > hide_below:
            out.append(False)
            continue
        hide_below = None
        out.append(True)
        if r.has_children and r.key not in open_keys:
            hide_below = r.depth
    return out


def validate_structure(v):
    out = []
    frag = v.frag
    if frag.type != "ARMATURE":
        out.append(Finding(ERROR, "FRAG_NOT_ARMATURE", "Fragment is not an armature; Sollumz refuses to export it.", frag.name, "object"))
        return out
    if v.drawable is None:
        out.append(Finding(ERROR, "NO_DRAWABLE", "Fragment has no Drawable child; Sollumz refuses to export it.", frag.name, "object"))
    for d in getattr(v, "extra_drawables", []):
        out.append(Finding(WARNING, "EXTRA_DRAWABLE", "Second Drawable under the fragment; Sollumz exports only the first.", d.name, "object"))
    for c in getattr(v, "extra_composites", []):
        out.append(Finding(WARNING, "EXTRA_COMPOSITE", "Second Bound Composite; Sollumz exports only the first.", c.name, "object"))
    for m in v.nested_models:
        out.append(Finding(ERROR, "NESTED_MODEL",
                           f"Drawable Model is parented to '{m.parent.name}', not directly to the Drawable. "
                           "Sollumz only exports direct children of the Drawable, so this mesh is dropped. "
                           "Keep models flat and express the hierarchy with bones.", m.name, "object",
                           {"op": "unnest_model", "object": m.name}))

    names = {b.name for b in frag.data.bones}
    for m in v.models:
        links = bone_links(m, names)
        if not links:
            home = bone_named(m.name, names)
            out.append(Finding(WARNING, "MODEL_UNBOUND",
                               "Not bound to any bone (no bone constraint, no vertex group named after a bone). "
                               "Exported on bone 0, so it will not move with any part."
                               + (f" Its name says '{home}'." if home else ""), m.name, "object",
                               {"op": "bind_objects", "bone": home, "objects": [m.name]} if home else None))
        else:
            bound, home = sz.child_of_bone(m), bone_named(m.name, names)
            if bound is not None and home is not None and home != bound.name:
                out.append(Finding(INFO, "BOUND_ELSEWHERE",
                                   f"Bound to '{bound.name}' but named after '{home}'. Vanilla models sit on the bone they are named after.",
                                   m.name, "object", {"op": "bind_objects", "bone": home, "objects": [m.name], "optin": True}))
        pb = sz.child_of_bone(m)
        if getattr(m, "sollumz_is_physics_child_mesh", False) and pb is not None and not pb.sollumz_use_physics:
            out.append(Finding(WARNING, "PHYSICS_MESH_NO_PHYSICS",
                               f"This mesh is the physical part of '{pb.name}' (a wheel or a piece that breaks off), but '{pb.name}' has Use Physics "
                               "off. Sollumz then writes no physics group for the bone and leaves the mesh out of the file, so it is missing in game.",
                               m.name, "object", {"op": "enable_physics", "bone": pb.name}))
        stray = [g.name for g in m.vertex_groups if g.name not in names]
        if stray and sz.child_of_bone(m) is None:
            out.append(Finding(WARNING, "STRAY_VGROUPS",
                               f"Vertex groups with no matching bone are ignored on export: {', '.join(stray[:6])}"
                               + ("..." if len(stray) > 6 else ""), m.name, "object"))

    if v.composite is not None:
        for b in v.bounds:
            if v.composite not in _ancestors(b):
                out.append(Finding(WARNING, "BOUND_OUTSIDE_COMPOSITE",
                                   "Collision is not under the Bound Composite; Sollumz will not export it.", b.name, "object",
                                   {"op": "adopt_bound", "object": b.name}))
            bone = sz.child_of_bone(b)
            home = bone_named(b.name, names)
            if bone is None:
                out.append(Finding(WARNING, "BOUND_UNBOUND",
                                   "Collision is not bound to a bone, so it never becomes a physics child."
                                   + (f" Its name says '{home}'." if home else ""), b.name, "object",
                                   {"op": "bind_objects", "bone": home, "objects": [b.name]} if home else None))
            else:
                if home is not None and home != bone.name:
                    out.append(Finding(INFO, "BOUND_ELSEWHERE",
                                       f"Bound to '{bone.name}' but named after '{home}'. Vanilla collisions sit on the bone they are named after.",
                                       b.name, "object", {"op": "bind_objects", "bone": home, "objects": [b.name], "optin": True}))
                if not bone.sollumz_use_physics:
                    out.append(Finding(WARNING, "BOUND_BONE_NO_PHYSICS",
                                       f"Bound to '{bone.name}', which has Use Physics off; Sollumz skips this collision.",
                                       b.name, "object", {"op": "enable_physics", "bone": bone.name}))
    for b in v.bounds:
        bone = sz.child_of_bone(b)
        if bone is not None and bone.sollumz_use_physics and getattr(b, "child_properties", None) is not None                 and b.child_properties.mass <= 0:
            out.append(Finding(WARNING, "COLLISION_MASS_ZERO",
                               f"Physics collision on '{bone.name}' has mass 0. A fragment whose physics children weigh "
                               "nothing has no usable mass; vehicles can freeze in place or ignore gravity. Use Sollumz "
                               "Tools > Fragment > Set Mass.",
                               b.name, "object"))
    with_col = {sz.child_of_bone(b).name for b in v.bounds if sz.child_of_bone(b) is not None}
    for bone in frag.data.bones:
        if WHEEL_BONE.match(bone.name):
            if bone.name not in with_col:
                donor = wheel_donor(bone.name, with_col)
                model = None if donor else next((m.name for m in v.models if (sz.child_of_bone(m) is not None and WHEEL_BONE.match(sz.child_of_bone(m).name))
                                                 or name_stem(m.name).lower().startswith("wheel")), None)
                if donor is None and model is None:
                    continue  # no wheel has a collision and no wheel model exists: a vehicle without working wheels (conada2 is one), not a forgotten one
                out.append(Finding(WARNING, "WHEEL_NO_COLLISION",
                                   "A wheel needs Use Physics on and a collision (a disc) bound to its bone: that is what makes the game place a wheel here. "
                                   "Vanilla vehicles carry the wheel mesh on wheel_lf only and give every other wheel just the collision. "
                                   + ("Use Physics is on, but there is no collision." if bone.sollumz_use_physics else "There is no collision and Use Physics is off.")
                                   + (f" The quick fix copies the collision of '{donor}' to this bone." if donor else
                                      f" No wheel has a collision to copy; the quick fix builds a disc from the size of '{model}'."),
                                   bone.name, "bone", {"op": "add_wheel_collision", "bone": bone.name, "donor": donor, "model": model}))
            continue
        if bone.sollumz_use_physics and bone.name not in with_col:
            out.append(Finding(WARNING, "PHYSICS_NO_COLLISION",
                               "Use Physics is on but no collision is bound to this bone; Sollumz drops the physics group.",
                               bone.name, "bone"))
    return out


TEXTURE_SAMPLERS = ("DiffuseSampler", "SpecSampler", "BumpSampler")


def validate_textures(v):
    out = []
    usage, _ = material_usage(v)
    for mat in usage:
        empty = [n.name for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.name in TEXTURE_SAMPLERS
                 and not getattr(n, "sollumz_texture_name", "")]
        if empty:
            fillable = any(textures.default_name(mat.shader_properties.filename, n.name) for n in mat.node_tree.nodes
                           if n.type == "TEX_IMAGE" and not getattr(n, "sollumz_texture_name", ""))
            out.append(Finding(WARNING, "EMPTY_TEXTURE_SAMPLER",
                               f"{', '.join(empty)} has no texture, so the export names none for it. Assign textures in the Sollumz shader "
                               "panel" + ("; the fix fills the samplers vanilla vehicles give a generic texture (a sampler that takes "
                                          "the vehicle's own texture stays empty)." if fillable else "."), mat.name, "material",
                               {"op": "fill_textures", "material": mat.name} if fillable else None))
    return out


SUFFIX_RX = re.compile(r"^(.+)\.(\d{3,})$")


def validate_hierarchy(v):
    out = []
    bones = v.frag.data.bones
    if not bones:
        return [Finding(ERROR, "NO_BONES", "Fragment armature has no bones.", v.frag.name, "object")]
    roots = [b for b in bones if b.parent is None]
    if len(roots) > 1:
        out.append(Finding(ERROR, "MULTIPLE_ROOTS", f"{len(roots)} root bones; a fragment skeleton has exactly one root "
                           f"(bones: {', '.join(b.name for b in roots[:5])}).", roots[1].name, "bone"))
    names = {b.name for b in bones}
    for bone in bones:
        suffix = SUFFIX_RX.match(bone.name)
        if suffix:
            stem = suffix.group(1)
            free = stem not in names
            out.append(Finding(WARNING, "BONE_NAME_SUFFIX",
                               f"Blender added '.{suffix.group(2)}' (duplicate). The tag is hashed from the full name, so "
                               f"this exports as tag {sz.tag_hash(bone.name)} instead of '{stem}' ({sz.tag_hash(stem)}); "
                               "the game will not recognise a part by its expected name."
                               + ("" if free else f" '{stem}' already exists: rename one of them yourself."),
                               bone.name, "bone", {"op": "rename_bone", "bone": bone.name, "to": stem} if free else None))
        props = getattr(bone, "bone_properties", None)
        if props is not None and bone.parent is not None and props.use_manual_tag:
            expect = sz.tag_hash(bone.name)
            if props.manual_tag != expect:
                out.append(Finding(WARNING, "TAG_MISMATCH",
                                   f"Manual tag {props.manual_tag} differs from the name hash {expect}. The "
                                   "game identifies parts by tag, so it will not match the name.", bone.name, "bone",
                                   {"op": "auto_tag", "bone": bone.name}))
    return out


# --- materials -------------------------------------------------------------

def material_usage(v):
    """{material: {"lods": set(lod_attr), "objects": set(names), "bad_slots": [...]}} for exported models."""
    usage = {}
    bad = []
    for m in v.models:
        for lod, mesh in sz.lod_meshes(m):
            counts = [0] * len(mesh.materials)
            for p in mesh.polygons:
                if p.material_index < len(counts):
                    counts[p.material_index] += 1
            for i, mat in enumerate(mesh.materials):
                if not counts[i]:
                    continue
                if not sz.is_shader_material(mat):
                    bad.append((m.name, lod, i, mat.name if mat else None, counts[i]))
                    continue
                u = usage.setdefault(mat, {"lods": set(), "objects": set()})
                u["lods"].add(lod)
                u["objects"].add(m.name)
    return usage, bad


def export_order(v):
    """(base, hi) material lists exactly as Sollumz will order the shader groups."""
    base = sz.export_materials(v.frag)
    hi = sz.export_materials(v.frag, hi=True) if any(
        lod == "very_high" for m in v.models for lod, _ in sz.lod_meshes(m)) else []
    return base, hi


def shader_name(mat):
    return mat.shader_properties.name


def validate_materials(v):
    out = []
    base, hi = export_order(v)
    usage, bad = material_usage(v)
    for obj, lod, slot, mat, n in bad:
        out.append(Finding(WARNING, "NON_SOLLUMZ_SLOT",
                           f"{lod} slot {slot} ({mat or 'empty'}) holds {n} polygons but is not a Sollumz shader "
                           "material; Sollumz does not export those polygons with a shader.", obj, "object"))
    union = base + [m for m in hi if m not in base]
    idx = [m.shader_properties.index for m in union]
    dupes = sorted({i for i in idx if idx.count(i) > 1})
    if dupes:
        out.append(Finding(WARNING, "MAT_INDEX_TIES",
                           f"Materials share Sollumz shader index {', '.join(map(str, dupes[:8]))}. Ties are broken by "
                           "alphabetical object order, so renaming or adding meshes silently reorders the shader group. "
                           "New materials default to index 0.", union[idx.index(dupes[0])].name, "material",
                           {"op": "lock_material_order"}))
    if hi:
        common_b = [m for m in base if m in hi]
        common_h = [m for m in hi if m in base]
        if common_b != common_h:
            out.append(Finding(WARNING, "HI_ORDER_DIFFERS",
                               "Materials shared by the _hi and base models are in a different relative order. "
                               "Both are normally exported from one material list, so their order agrees.",
                               v.frag.name, "object", {"op": "lock_material_order"}))
        for m in hi:
            if m not in base:
                out.append(Finding(INFO, "HI_ONLY_MATERIAL", "Used only by the very-high (_hi) LOD.", m.name, "material"))
        missing = [m.name for m in base if m not in hi]
        if missing:
            out.append(Finding(INFO, "HI_MATERIAL_SET_DIFFERS",
                               f"{len(missing)} base materials are not in the _hi shader group ({', '.join(missing[:5])}). "
                               "Both are normally exported from one material list.", v.frag.name, "object"))
    for m in base:
        lods = usage.get(m, {}).get("lods", set())
        if lods and "high" not in lods and "very_high" not in lods:
            out.append(Finding(INFO, "LOW_LOD_ONLY", f"Used only in {', '.join(sorted(lods))}.", m.name, "material"))
    return out


def duplicate_material_groups(v):
    """[[material, ...]] with identical export signature, in export order. First of each group is the one to keep."""
    base, hi = export_order(v)
    groups = {}
    for m in base + [m for m in hi if m not in base]:
        groups.setdefault(sz.shader_signature(m), []).append(m)
    return [g for g in groups.values() if len(g) > 1]


def validate_duplicates(v):
    out = []
    for g in duplicate_material_groups(v):
        out.append(Finding(WARNING, "DUPLICATE_MATERIALS",
                           f"{len(g)} materials export identical shaders (same shader, parameters and textures): "
                           f"{', '.join(m.name for m in g[:5])}{'...' if len(g) > 5 else ''}. Each becomes its own entry in "
                           "the shader group. Merging keeps the first and points every slot at it; polygon indices do not change.",
                           g[0].name, "material",
                           {"op": "merge_materials", "keep": g[0].name, "drop": [m.name for m in g[1:]]}))
    return out


def validate_mesh_attrs(v):
    """Vehicle-wide version of Sollumz's per-mesh Data-tab warnings: UV maps and colour attributes the shaders use."""
    out = []
    for m in v.models:
        for lod, mesh in sz.lod_meshes(m):
            uv, col = sz.mesh_missing_attrs(mesh)
            if uv:
                out.append(Finding(WARNING, "MISSING_UV_MAP",
                                   f"{lod} mesh lacks UV maps its shaders use: {', '.join(uv)}. Select the object and use "
                                   "Sollumz Data tab > UV Maps > Add Missing (or Rename by Order).", m.name, "object"))
            if col:
                out.append(Finding(WARNING, "MISSING_COLOR_ATTR",
                                   f"{lod} mesh lacks colour attributes its shaders use (must be Face Corner, Byte Color): "
                                   f"{', '.join(col)}. Use Sollumz Data tab > Color Attributes > Add Missing.", m.name, "object"))
    return out


WHEEL_BONE = re.compile(r"^wheel_([lr][fmr]\d?|[fr])$")  # wheel_lf, wheel_rr, wheel_lm1 ... and the bike wheels wheel_f, wheel_r; not wheelmesh_*


def wheel_donor(bone, with_collision):
    """The wheel bone whose collision is the best one to copy to `bone`: one with a collision, preferring the same axle (the f, m or r part of the name)."""
    cands = sorted(b for b in with_collision if WHEEL_BONE.match(b) and b != bone)
    cands.sort(key=lambda b: b[7:] != bone[7:] and b[-1] != bone[-1])
    return cands[0] if cands else None


def validate(v, profile=None):
    """All findings. `profile` (None, "AUTO" or a profile name) switches on the profile-required-bone checks."""
    from . import rulecheck  # imported late: rulecheck imports this module
    return (validate_structure(v) + validate_hierarchy(v) + validate_materials(v) + validate_textures(v)
            + validate_order(v) + validate_duplicates(v) + validate_mesh_attrs(v)
            + rulecheck.validate_rules(v, profile))


def _ancestors(obj):
    out = []
    while obj.parent is not None:
        obj = obj.parent
        out.append(obj)
    return out
