"""Vehicle paint layers and liveries, built on Sollumz's own mechanism.

In GTA V the colour a vehicle part is painted with comes from its material's `matDiffuseColor` parameter: (2, n, n) means "use paint
layer n" (1 Primary, 2 Secondary, 3 Pearlescent, 4 Wheel, 6 Interior Trim, 7 Dashboard), anything else is the part's own fixed colour.
Sollumz reads and writes that through `Material.sz_paint_layer` (and appends [PRIMARY], [SECONDARY]... to the name). Colour variants are
therefore *materials*: the same shader and textures, differing only in that layer. This module finds, creates and assigns those materials.

A livery is the shader `vehicle_paint3_lvr`: `vehicle_paint3` with its second diffuse sampler (DiffuseSampler2) replaced by a livery
diffuse (DiffuseSampler3, on the second UV map). It still carries `matDiffuseColor`, so it keeps a paint layer.
"""
import bpy

from . import analysis, sollumz_bridge as sz, textures

LAYERS = ("PRIMARY", "SECONDARY", "PEARLESCENT", "WHEEL", "INTERIOR_TRIM", "INTERIOR_DASH", "CUSTOM", "DEFAULT")
LAYER_LABELS = {"PRIMARY": "Primary", "SECONDARY": "Secondary", "PEARLESCENT": "Pearlescent", "WHEEL": "Wheel",
                "INTERIOR_TRIM": "Interior Trim", "INTERIOR_DASH": "Dashboard", "CUSTOM": "Custom (fixed colour)",
                "DEFAULT": "Default (white)"}
LIVERY_SHADER = "vehicle_paint3_lvr.sps"
# Paint shaders worth offering when adding a material (all carry matDiffuseColor). The numbers differ in samplers, not in purpose
# that could be verified.
PAINT_SHADERS = ("vehicle_paint1.sps", "vehicle_paint2.sps", "vehicle_paint3.sps", "vehicle_paint4.sps", "vehicle_paint6.sps",
                 "vehicle_paint7.sps", "vehicle_paint8.sps", "vehicle_paint9.sps", LIVERY_SHADER)


# What each paint shader has, from Sollumz's shader definitions and how often vanilla uses it.
# The files do not say which part each is meant for, so these are features, not recommendations.
SHADER_NOTES = {
    "vehicle_paint1.sps": ("basic, one diffuse, no second layer",
                           "One diffuse, spec and dirt; no second diffuse layer. Has a second specular colour that paint2 lacks."),
    "vehicle_paint2.sps": ("basic, one diffuse, no second layer",
                           "One diffuse, spec and dirt; no second diffuse layer. Like paint1 without its second specular colour."),
    "vehicle_paint3.sps": ("adds a second diffuse layer",
                           "Paint1/2 plus a second diffuse layer (decals, stripes). Without paint4's extra specular controls."),
    "vehicle_paint3_lvr.sps": ("livery layer on UV map 2",
                               "Paint3 with a livery diffuse (DiffuseSampler3, second UV map) in place of the second diffuse."),
    "vehicle_paint4.sps": ("second diffuse + extra specular controls, the most used in vanilla",
                           "Paint3 plus extra specular controls (specular2 intensity and factor, spec tiling). 15 of the 24 paint materials on "
                           "10 vanilla vehicles."),
    "vehicle_paint6.sps": ("paint4 + a second normal map",
                           "Paint4 plus a second normal map (BumpSampler2, bumpiness)."),
    "vehicle_paint7.sps": ("second diffuse layer, like paint3",
                           "Same samplers and parameters as paint3."),
    "vehicle_paint8.sps": ("paint4 + normal map, dirt normal, worn/snow layers",
                           "Paint4 plus a normal map, a dirt normal map and two environment-effect layers (SnowSampler0/1)."),
    "vehicle_paint9.sps": ("like paint8, used on worn vehicles",
                           "Same samplers as paint8. On vanilla cargobob5 and similar worn vehicles."),
}


def shader_items():
    """(identifier, label, description) for the shader dropdown: 'vehicle_paint4 (what it has)'."""
    out = []
    for s in PAINT_SHADERS:
        note, text = SHADER_NOTES.get(s, ("", ""))
        label = s.replace(".sps", "") + (f" ({note})" if note else "")
        out.append((s, label, text))
    return out


def is_paint_material(mat):
    return (sz.is_shader_material(mat) and mat.node_tree is not None
            and "matDiffuseColor" in mat.node_tree.nodes)


def layer_of(mat):
    return mat.sz_paint_layer


def texture_signature(mat):
    """Shader and texture names, i.e. everything that makes two paint materials 'the same paint' apart from the layer."""
    tex = tuple(sorted((n.name, n.sollumz_texture_name) for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"))
    return mat.shader_properties.filename, tex


def vehicle_paint_materials(v):
    """[(material, polygon count, bones)] for the paint materials the exported models use, in export order."""
    base, hi = analysis.export_order(v)
    mats = [m for m in base + [m for m in hi if m not in base] if is_paint_material(m)]
    names = set(v.frag.data.bones.keys())
    out = []
    for m in mats:
        polys, bones = 0, set()
        for o in v.models:
            for attr, me in sz.lod_meshes(o):
                if attr not in ("high", "very_high"):
                    continue
                for slot, mm in enumerate(me.materials):
                    if mm is m:
                        n = sum(1 for p in me.polygons if p.material_index == slot)
                        polys += n
                        if n:
                            bones |= set(analysis.bone_links(o, names)[:1])
        out.append((m, polys, sorted(bones)))
    return out


def next_shader_index(v):
    base, hi = analysis.export_order(v)
    return max([m.shader_properties.index for m in base + hi] + [-1]) + 1


def find_variant(v, base, layer, shader=None):
    """An existing paint material with the same shader and textures as `base` (or `shader`) and the wanted layer."""
    want_file = shader or base.shader_properties.filename
    for m in bpy.data.materials:
        if m is base or not is_paint_material(m) or layer_of(m) != layer:
            continue
        if m.shader_properties.filename == want_file and (shader is not None or texture_signature(m) == texture_signature(base)):
            return m
    return None


def make_variant(v, base, layer, shader=None):
    """Copy of `base` with the wanted paint layer (and optionally another shader). Reuses an existing identical variant."""
    if shader is None and layer_of(base) == layer:
        return base, False
    found = find_variant(v, base, layer, shader)
    if found is not None and shader is None:
        return found, False
    new = base.copy()
    if shader and shader != base.shader_properties.filename:
        sz.switch_shader(new, shader)
        textures.apply_defaults(new)  # samplers the old shader lacked
    new.sz_paint_layer = layer  # writes matDiffuseColor and renames to "<name> [LAYER]"
    new.shader_properties.index = next_shader_index(v)
    return new, True


def replace_in_models(v, objs, old, new):
    """Swap `old` for `new` in every material slot of the given models (all LOD meshes). Polygon indices are untouched."""
    slots, seen = 0, set()
    for o in objs:
        for _, me in sz.lod_meshes(o):
            if me in seen:
                continue
            seen.add(me)
            for i, m in enumerate(me.materials):
                if m is old:
                    me.materials[i] = new
                    slots += 1
    return slots


def selected_face_count(context):
    """Selected faces of the active mesh in Edit mode (0 outside Edit mode)."""
    import bmesh
    obj = context.active_object
    if context.mode != "EDIT_MESH" or obj is None or obj.type != "MESH":
        return 0
    return sum(1 for f in bmesh.from_edit_mesh(obj.data).faces if f.select)


def assign_to_faces(context, obj, mat):
    """Edit mode: give the selected faces of the active model `mat` (added as a slot if the mesh does not have it)."""
    import bmesh
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return 0
    idx = next((i for i, m in enumerate(me.materials) if m is mat), None)
    if idx is None:
        me.materials.append(mat)
        idx = len(me.materials) - 1
    for f in faces:
        f.material_index = idx
    bmesh.update_edit_mesh(me)
    return len(faces)


def give_first_material(v, context, mat):
    """Object mode, selected models with no material (no slot, or an empty active slot): `mat` becomes their material on every LOD mesh.
    Polygons already point at slot 0, so they all use it."""
    models = [o for o in context.selected_objects if o in v.models] or ([context.active_object] if context.active_object in v.models else [])
    done = []
    for o in models:
        for _, me in sz.lod_meshes(o):
            if not len(me.materials):
                me.materials.append(mat)
            elif me.materials[min(o.active_material_index, len(me.materials) - 1)] is None:
                me.materials[min(o.active_material_index, len(me.materials) - 1)] = mat
            else:
                continue
            if o.name not in done:
                done.append(o.name)
        sz.prepare_mesh_for_material(o, mat)
    if done:
        return f"{mat.name} is now the material of {', '.join(done[:4])}{'...' if len(done) > 4 else ''}"
    return "Select a model to put it on (one that already has a material keeps it: make that the active slot and use Paint Layers)."


def assign(context, v, base, new):
    """Put `new` where `base` is used: the selected faces in Edit mode, or every slot holding `base` on the selected models."""
    obj = context.active_object
    if context.mode == "EDIT_MESH" and obj is not None and obj.type == "MESH":
        n = assign_to_faces(context, obj, new)
        sz.prepare_mesh_for_material(obj, new)
        return f"{n} selected face(s) now use {new.name}" if n else "Select some faces first."
    models = [o for o in context.selected_objects if o in v.models] or ([obj] if obj in v.models else [])
    n = replace_in_models(v, models, base, new)
    for o in models:
        sz.prepare_mesh_for_material(o, new)
    return f"{n} slot(s) on {len(models)} model(s) now use {new.name}"
