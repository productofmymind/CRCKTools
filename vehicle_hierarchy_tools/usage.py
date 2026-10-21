"""Material usage of a vehicle: which materials the exported models use, where, how many polygons, and what is wrong with their textures.

Read-only except `replace_everywhere` and `select_users`. Counts are for the displayed (high) LOD meshes, as in the paint list.
"""
import bpy

from . import analysis, paint, sollumz_bridge as sz

LOD_NAMES = {"very_high": "0", "high": "1", "medium": "2", "low": "3", "very_low": "4"}


def rows(v):
    """[{material, objects, polys, lods}] for every Sollumz material the exported models use, in export order."""
    usage, _ = analysis.material_usage(v)
    base, hi = analysis.export_order(v)
    out = []
    for m in base + [x for x in hi if x not in base]:
        info = usage.get(m)
        if info is None:
            continue
        polys = 0
        for o in v.models:
            for attr, me in sz.lod_meshes(o):
                if attr in ("high", "very_high"):
                    for slot, mm in enumerate(me.materials):
                        if mm is m:
                            polys += sum(1 for p in me.polygons if p.material_index == slot)
        out.append({"material": m, "objects": sorted(info["objects"]), "polys": polys,
                    "lods": "".join(sorted(LOD_NAMES[a] for a in info["lods"]))})
    return out


def texture_report(v):
    """Lines describing texture problems: empty samplers (the export names no texture), embedded textures with no data, and one texture name
    held by several images."""
    lines, by_name = [], {}
    for m in (r["material"] for r in rows(v)):
        empty = []
        for n in m.node_tree.nodes:
            if n.type != "TEX_IMAGE":
                continue
            name = n.sollumz_texture_name
            if not name:
                if n.name != "DamageSampler":
                    empty.append(n.name)
                continue
            img = n.image
            if n.texture_properties.embedded and img is not None and not img.packed_file and not bpy.path.abspath(img.filepath).lower().endswith(".dds"):
                lines.append(f"{m.name}: {n.name} '{name}' is embedded but has no DDS data or file")
            by_name.setdefault(name, set()).add(img)
        if empty:
            lines.append(f"{m.name}: no texture on {', '.join(empty)}")
    for name, imgs in sorted(by_name.items()):
        if len(imgs) > 1:
            lines.append(f"texture '{name}' is held by {len(imgs)} separate images (Remap Users in the Blender File view merges them)")
    return lines


def users(v, mat):
    """Models whose displayed LOD meshes use the material."""
    return [o for o in v.models if any(m is mat for _, me in sz.lod_meshes(o) for m in me.materials)]


def replace_everywhere(v, old, new):
    """Every slot holding `old` on every exported model and LOD mesh now holds `new`; polygon indices untouched. Returns (slots, models)."""
    models = users(v, old)
    slots = paint.replace_in_models(v, models, old, new)
    for o in models:
        sz.prepare_mesh_for_material(o, new)
    return slots, len(models)


def select_users(context, v, mat):
    """Object mode: select the models that use the material. Edit mode: select the faces of the active mesh that use it. Returns a report line."""
    obj = context.active_object
    if context.mode == "EDIT_MESH" and obj is not None and obj.type == "MESH":
        import bmesh
        slots = {i for i, m in enumerate(obj.data.materials) if m is mat}
        if not slots:
            return f"{obj.name} does not use {mat.name}."
        bm = bmesh.from_edit_mesh(obj.data)
        n = 0
        for f in bm.faces:
            f.select = f.material_index in slots
            n += f.select
        bmesh.update_edit_mesh(obj.data)
        return f"{n} face(s) of {obj.name} use {mat.name}"
    chosen = users(v, mat)
    for o in context.view_layer.objects:
        o.select_set(False)
    for o in chosen:
        if not o.hide_get():
            o.select_set(True)
    if chosen:
        context.view_layer.objects.active = next((o for o in chosen if o.select_get()), context.view_layer.objects.active)
    return f"{len(chosen)} model(s) use {mat.name}"
