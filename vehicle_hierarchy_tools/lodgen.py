"""Automatic LOD generation for the parts of a vehicle, into Sollumz's LOD slots (no loose copies).
measurements behind each choice.

Levels are Sollumz's: L0 very high (the `_hi` file), L1 high, L2 medium, L3 low, L4 very low. Generation starts from L0 or from L1 and fills the levels
below it. A slot that already has a mesh is left alone unless asked, objects are never created, and the source meshes are never changed.

Reduction of one mesh (`reduce`):
  * meshoptimizer (zeux/meshoptimizer, MIT; `lib/meshoptimizer.dll`) in attribute-aware, permissive mode with vertex update: quadric error with UVs and colours as
    attributes, material borders protected, UV seams free to collapse. Measured on real vehicles: about a quarter to half less surface error than Blender's
    Decimate at 50%, about 10 times faster; at 30% and below Blender's Decimate was as good or better (worst-case distance clearly), so AUTO uses it below
    AUTO_MESHOPT_MIN_RATIO.
  * Vertex-group weights (a vehicle part is bound to its bone by one) travel through the simplifier as extra attributes and are written back, so a
    skinned or rigidly bound part is reduced the same way as any other. A part with more than MAX_GROUPS groups goes to Blender's Decimate.
  * Blender's Decimate (collapse) when meshoptimizer is missing, below about 40% of the triangles, for parts with many vertex groups, or when chosen.
  * If meshoptimizer stalls above the target (topology, locks), Blender finishes the job, so the triangle budget is met.
Shading: the original corner normals are transferred onto the new mesh (nearest point on the source surface, interpolated; the new face normal wins where the
two disagree strongly, which keeps hard edges), so the LODs shade like the source.
Parts that must keep their look (wheels, glass, lights, mirrors) keep more triangles by a factor.
"""
import math
import re

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

from . import meshopt as mo
from . import sollumz_bridge as sz

# slot name in Object.sz_lods, label used in the mesh name
LEVELS = (("very_high", "very high"), ("high", "high"), ("medium", "medium"), ("low", "low"), ("very_low", "very low"))
SLOT_INDEX = {s: i for i, (s, _) in enumerate(LEVELS)}
LABEL = dict(LEVELS)
MIN_TRIANGLES = 4
AUTO_MESHOPT_MIN_RATIO = 0.4   # below this share of the triangles Blender's Decimate measured as good or better
SMALL_MATERIAL_TRIANGLES = 16   # materials with fewer triangles than this (or 3% of the part) are locked so they survive every level
STALL_FACTOR = 1.25            # meshoptimizer result above target * this is finished by Blender
MAX_GROUPS = 8                 # more vertex groups than this on a part: Blender's Decimate (weights as simplifier attributes grow with the count)
WEIGHT_IMPORTANCE = 2.0        # attribute weight of the vertex-group weights, against 1 for normals
# Triangles kept relative to the start mesh, from 11 vanilla vehicles (pooled over the parts that have both levels)
VANILLA = {"very_high": {"high": 0.30, "medium": 0.16, "low": 0.08, "very_low": 0.03},
           "high": {"medium": 0.50, "low": 0.27, "very_low": 0.09}}

CRITICAL = (("wheel", re.compile(r"wheel|tyre|tire")), ("glass", re.compile(r"window|windscreen|glass")),
            ("light", re.compile(r"light|indicator|siren|neon|emissive|lamp")), ("mirror", re.compile(r"mirror")))


def part_class(model, bones):
    """'wheel', 'glass', 'light', 'mirror' or None, from the names of the model and of the bone it is bound to."""
    from . import analysis
    names = [analysis.name_stem(model.name).lower()] + [b.lower() for b in analysis.bone_links(model, bones)]
    for cls, rx in CRITICAL:
        if any(rx.search(n) for n in names):
            return cls
    return None


def triangles(mesh):
    return sum(len(p.vertices) - 2 for p in mesh.polygons)


def slot_counts(models):
    """{slot: number of models that have a mesh in it}."""
    return {slot: sum(1 for o in models if getattr(o.sz_lods, slot).mesh is not None) for slot, _ in LEVELS}


# --- extraction and rebuilding ---------------------------------------------------

def extract(mesh):
    """Numpy view of a mesh: vertex positions, loops, per-corner normals, every UV layer and colour attribute per corner, material per triangle."""
    mesh.calc_loop_triangles()
    t = len(mesh.loop_triangles)
    loops = np.empty(t * 3, np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    mat = np.empty(t, np.int32)
    mesh.loop_triangles.foreach_get("material_index", mat)
    nl = len(mesh.loops)
    vidx = np.empty(nl, np.int32)
    mesh.loops.foreach_get("vertex_index", vidx)
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    nrm = np.empty(nl * 3, np.float32)
    mesh.corner_normals.foreach_get("vector", nrm)
    uvs = []
    for layer in mesh.uv_layers:
        a = np.empty(nl * 2, np.float32)
        layer.uv.foreach_get("vector", a)
        uvs.append(a.reshape(-1, 2))
    cols = []
    for attr in mesh.color_attributes:
        a = np.empty(len(attr.data) * 4, np.float32)
        attr.data.foreach_get("color", a)
        a = a.reshape(-1, 4)
        cols.append(a if attr.domain == "CORNER" else a[vidx])
    return {"co": co.reshape(-1, 3), "vidx": vidx, "loops": loops.reshape(-1, 3), "mat": mat, "nrm": nrm.reshape(-1, 3), "uvs": uvs, "cols": cols}


def _uv_weight(uv, tris):
    """Attribute weight for UVs: 1 / sqrt(average UV triangle area), as meshoptimizer's README suggests (clamped to 10..100)."""
    if uv is None or not len(tris):
        return 10.0
    a, b, c = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    ab, ac = b - a, c - a
    area = np.abs(ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]) * 0.5
    area = area[area > 1e-12]
    if not len(area):
        return 10.0
    return float(min(100.0, max(10.0, 1.0 / math.sqrt(float(area.mean())))))


def skin_of(mesh):
    """(group names, dense (vertices, groups) deform weights or None when no vertex has a weight). The names live on the mesh in current Blender
    versions and are read through a temporary object."""
    tmp = bpy.data.objects.new("vht_lod_tmp", mesh)
    try:
        names = [g.name for g in tmp.vertex_groups]
    finally:
        bpy.data.objects.remove(tmp)
    vi, gi, wi = [], [], []
    for v in mesh.vertices:
        for g in v.groups:
            vi.append(v.index); gi.append(g.group); wi.append(g.weight)
    if not vi:
        return names, None
    width = max(len(names), max(gi) + 1)
    w = np.zeros((len(mesh.vertices), width), np.float32)
    w[vi, gi] = wi
    return names, w


def _set_weights(mesh, names, weights):
    """Give `mesh` the vertex groups `names` and the dense deform weights (in 1/255 steps, which is what a file can hold anyway)."""
    tmp = bpy.data.objects.new("vht_lod_tmp", mesh)
    try:
        for g in range(weights.shape[1]):
            tmp.vertex_groups.new(name=names[g] if g < len(names) else f"group_{g}")
        w = np.round(weights * 255.0) / 255.0
        for g in range(w.shape[1]):
            col = w[:, g]
            for val in np.unique(col[col > 0]):
                tmp.vertex_groups[g].add(np.flatnonzero(col == val).tolist(), float(val), "REPLACE")
    finally:
        bpy.data.objects.remove(tmp)


def _rebuild(src, pos, tri, tri_mat, vertex_uvs, vertex_cols, name, skin=None):
    """A new mesh with `src`'s materials and properties but the geometry given. UV layers and colour attributes keep their names, types and domains;
    `skin` = (names, weights) becomes its vertex groups."""
    layers = [(l.name) for l in src.uv_layers]
    cols = [(a.name, a.data_type, a.domain) for a in src.color_attributes]
    mesh = src.copy()
    mesh.clear_geometry()
    mesh.from_pydata(pos.tolist(), [], tri.tolist())
    mesh.polygons.foreach_set("material_index", tri_mat.astype(np.int32))
    corner = tri.ravel()
    for nm, uv in zip(layers, vertex_uvs):
        layer = mesh.uv_layers.new(name=nm)
        layer.uv.foreach_set("vector", uv[corner].ravel().astype(np.float32))
    for (nm, dtype, domain), col in zip(cols, vertex_cols):
        attr = mesh.color_attributes.new(name=nm, type=dtype, domain=domain)
        data = col[corner] if domain == "CORNER" else col
        attr.data.foreach_set("color", data.ravel().astype(np.float32))
    mesh.update()
    mesh.name = name
    if skin is not None:
        _set_weights(mesh, *skin)
    return mesh


def reduce_meshopt(src, ratio, d=None, skin=None, options=mo.PERMISSIVE, steps=1, keep_small=True):
    """Reduce with meshoptimizer; returns a new mesh, or None when the mesh cannot be handled (no triangles). `ratio` is the share of triangles kept;
    `skin` is `skin_of(src)` when the caller has it; the vertex-group weights are carried along as attributes."""
    d = d or extract(src)
    t = len(d["loops"])
    if t == 0:
        return None
    nl = len(d["vidx"])
    cm = np.zeros((nl, 1), np.float32)
    cm[d["loops"].ravel(), 0] = np.repeat(d["mat"], 3)
    uv0 = d["uvs"][0] if d["uvs"] else np.zeros((nl, 2), np.float32)
    key = np.concatenate([d["co"][d["vidx"]], uv0, cm], axis=1).astype(np.float32)  # position, first UV, material: vertices differing in these are separate
    remap, first = mo.weld_index(key)
    tri = remap[d["loops"]].astype(np.uint32)
    nv = len(first)
    pos = key[first, :3].copy()
    # attributes per vertex from the first corner using it: every UV layer, every colour attribute
    cols = [c[first] for c in d["cols"]] or []
    uvs = [u[first] for u in d["uvs"]]
    names, dense = skin or skin_of(src)
    groups = dense.shape[1] if dense is not None else 0
    wt = dense[d["vidx"]][first] if dense is not None else None  # per welded vertex, from the corner it came from
    parts = uvs + cols + ([wt] if wt is not None else [])
    att = np.concatenate(parts, axis=1).astype(np.float32) if parts else None
    weights = np.array([_uv_weight(u, d["loops"]) for u in d["uvs"] for _ in (0, 1)] + [0.5] * (4 * len(cols))
                       + [WEIGHT_IMPORTANCE] * groups, np.float32) if att is not None else None
    # protect material borders: vertices at one position that belong to different materials
    group, _ = mo.weld(pos)
    mats = key[first, 5]
    lock = np.zeros(nv, np.uint8)
    seen, bad = {}, set()
    for i in range(nv):
        g = int(group[i])
        if seen.setdefault(g, float(mats[i])) != float(mats[i]):
            bad.add(g)
    if bad:
        lock = np.array([mo.V_PROTECT if int(group[i]) in bad else 0 for i in range(nv)], np.uint8)
    if keep_small:  # a material with only a few triangles (a lens, a trim strip) is locked in place so it cannot vanish from the level
        counts = np.bincount(d["mat"], minlength=1)
        small = np.flatnonzero((counts > 0) & (counts < max(SMALL_MATERIAL_TRIANGLES, 0.03 * t)))
        if len(small) and len(small) < len(counts):
            lock = lock.copy()
            lock[np.unique(tri[np.isin(d["mat"], small)].ravel())] = mo.V_LOCK
    target = max(int(t * ratio), MIN_TRIANGLES) * 3
    idx, pos2, att2 = tri.ravel(), pos, att
    cur = 1.0
    for k in range(1, steps + 1):  # steps > 1: reduce in equal geometric steps, each from the previous result
        cur = ratio ** (k / steps)
        step_target = max(int(t * cur), MIN_TRIANGLES) * 3 if k < steps else target
        idx, pos2, att2, _ = mo.simplify_update(idx, pos2, att2, weights, lock, step_target, 1.0, options)
    out = idx.reshape(-1, 3)
    if not len(out):
        return None
    used, inv = np.unique(out.ravel(), return_inverse=True)
    out = inv.reshape(-1, 3).astype(np.uint32)
    k = 0
    new_uvs, new_cols = [], []
    for u in uvs:
        new_uvs.append(att2[used, k:k + 2]); k += 2
    for c in cols:
        new_cols.append(att2[used, k:k + 4]); k += 4
    new_skin = None
    if wt is not None:
        new_w = np.clip(att2[used, k:k + groups], 0.0, 1.0)
        sums = wt.sum(axis=1)
        if np.all(np.abs(sums[sums > 0] - 1.0) < 0.02):  # the source is normalised, so the result is too
            ns = new_w.sum(axis=1, keepdims=True)
            new_w = np.where(ns > 1e-6, new_w / np.maximum(ns, 1e-6), 0.0)
        new_skin = (names, new_w)
    # material of a triangle = material of its vertices (borders are protected, so they agree)
    tri_mat = mats[used][out[:, 0]].astype(np.int32)
    return _rebuild(src, pos2[used], out, tri_mat, new_uvs, new_cols, src.name, new_skin)


def reduce_blender(src, ratio):
    """Reduce with Blender's Decimate (collapse), keeping vertex groups, UVs and colours (the modifier does)."""
    faces = len(src.polygons)
    ratio = max(min(ratio, 1.0), min(1.0, MIN_TRIANGLES / max(faces, 1)))
    tmp = bpy.data.objects.new("vht_lod_tmp", src)
    bpy.context.scene.collection.objects.link(tmp)
    try:
        mod = tmp.modifiers.new("Decimate", "DECIMATE")
        mod.decimate_type, mod.ratio, mod.use_collapse_triangulate = "COLLAPSE", ratio, True
        depsgraph = bpy.context.evaluated_depsgraph_get()
        out = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
    finally:
        bpy.data.objects.remove(tmp)
    return out


def transfer_shading(new, original, strong_disagreement=0.5):
    """Give `new` the corner normals of `original`: the nearest point of the original surface, with its corner normals interpolated. Where that normal
    and the new face's own normal disagree strongly (dot below `strong_disagreement`) the new face normal is kept, which preserves hard edges."""
    if not len(new.polygons) or not len(original.polygons):
        return
    original.calc_loop_triangles()
    ot = len(original.loop_triangles)
    ol = np.empty(ot * 3, np.int32)
    original.loop_triangles.foreach_get("loops", ol)
    ol = ol.reshape(-1, 3)
    ov = np.empty(ot * 3, np.int32)
    original.loop_triangles.foreach_get("vertices", ov)
    ov = ov.reshape(-1, 3)
    oco = np.empty(len(original.vertices) * 3, np.float64)
    original.vertices.foreach_get("co", oco)
    oco = oco.reshape(-1, 3)
    onrm = np.empty(len(original.loops) * 3, np.float64)
    original.corner_normals.foreach_get("vector", onrm)
    onrm = onrm.reshape(-1, 3)
    bvh = BVHTree.FromPolygons([tuple(v) for v in oco], [tuple(t) for t in ov])
    new.calc_loop_triangles()
    nl = len(new.loops)
    nvidx = np.empty(nl, np.int32)
    new.loops.foreach_get("vertex_index", nvidx)
    nco = np.empty(len(new.vertices) * 3, np.float64)
    new.vertices.foreach_get("co", nco)
    nco = nco.reshape(-1, 3)
    fn = np.empty(len(new.polygons) * 3, np.float64)
    new.polygons.foreach_get("normal", fn)
    fn = fn.reshape(-1, 3)
    starts = np.empty(len(new.polygons), np.int32)
    new.polygons.foreach_get("loop_start", starts)
    sizes = np.diff(np.append(starts, nl))
    poly_of_loop = np.repeat(np.arange(len(starts)), sizes)
    # one nearest-point query per vertex (it depends on the position only)
    near_loc = np.empty((len(nco), 3))
    near_tri = np.empty(len(nco), np.int32)
    for i, p in enumerate(nco):
        loc, _, idx, _ = bvh.find_nearest(tuple(p))
        near_loc[i], near_tri[i] = loc, idx
    a, b, c = oco[ov[near_tri, 0]], oco[ov[near_tri, 1]], oco[ov[near_tri, 2]]
    v0, v1, v2 = b - a, c - a, near_loc - a
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-30, 1.0, den)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1 - v - w
    n_at = u[:, None] * onrm[ol[near_tri, 0]] + v[:, None] * onrm[ol[near_tri, 1]] + w[:, None] * onrm[ol[near_tri, 2]]
    n_at /= np.maximum(np.linalg.norm(n_at, axis=1, keepdims=True), 1e-20)
    cand = n_at[nvidx]
    face = fn[poly_of_loop]
    ok = (cand * face).sum(1) >= strong_disagreement
    normals = np.where(ok[:, None], cand, face)
    new.normals_split_custom_set(normals.tolist())


def reduce(src, ratio, method="AUTO", keep_shading=True, shading_from=None):
    """Reduce `src` to `ratio` of its triangles. Returns (mesh, which method produced it)."""
    tris = triangles(src)
    target = max(int(tris * ratio), MIN_TRIANGLES)
    skin = skin_of(src)
    can_mo = mo.available() and (skin[1] is None or skin[1].shape[1] <= MAX_GROUPS)
    use_mo = method != "BLENDER" and can_mo and (method == "MESHOPT" or ratio >= AUTO_MESHOPT_MIN_RATIO)
    used = "blender"
    out = None
    if use_mo:
        out = reduce_meshopt(src, ratio, skin=skin)
        used = "meshoptimizer"
        if out is not None and triangles(out) > target * STALL_FACTOR and method != "MESHOPT":
            finished = reduce_blender(out, target / triangles(out))
            bpy.data.meshes.remove(out)
            out, used = finished, "meshoptimizer+blender"
    if out is None:
        out, used = reduce_blender(src, ratio), "blender"
        if method == "AUTO" and can_mo and triangles(out) > target * STALL_FACTOR + 2:
            # Blender cannot go that low on a tiny mesh (a box stays at 8 triangles); meshoptimizer can go to the floor
            alt = reduce_meshopt(src, ratio, skin=skin)
            if alt is not None and triangles(alt) < triangles(out):
                bpy.data.meshes.remove(out)
                out, used = alt, "meshoptimizer"
            elif alt is not None:
                bpy.data.meshes.remove(alt)
    if method == "AUTO" and can_mo and used == "blender":
        # Blender's Decimate can drop a thin material altogether at strong reductions; meshoptimizer locks such patches, so retry with it
        lost = {p.material_index for p in src.polygons} - {p.material_index for p in out.polygons}
        if lost:
            alt = reduce_meshopt(src, ratio, skin=skin)
            if alt is not None and triangles(alt) > target * STALL_FACTOR:  # locked patches can keep it above the budget: let Blender trim the rest if that keeps the materials
                fin = reduce_blender(alt, target / triangles(alt))
                if len({p.material_index for p in fin.polygons}) >= len({p.material_index for p in alt.polygons}):
                    bpy.data.meshes.remove(alt)
                    alt = fin
                else:
                    bpy.data.meshes.remove(fin)
            if alt is not None and len({p.material_index for p in alt.polygons}) > len({p.material_index for p in out.polygons}):
                bpy.data.meshes.remove(out)
                out, used = alt, "meshoptimizer"
            elif alt is not None:
                bpy.data.meshes.remove(alt)
    if keep_shading:
        transfer_shading(out, shading_from if shading_from is not None else src)
    return out, used


# --- generation ---------------------------------------------------------------------

def generate(models, start="high", ratios=None, make_very_high=False, overwrite=False, method="AUTO", chain=False, protect=1.5,
             keep_shading=True, bones=None):
    """Fill the LOD slots below `start` ('very_high' = L0, `_hi`; or 'high' = L1) for each model. `ratios` maps slot -> share of the *start* mesh's
    triangles (0 or missing skips that slot; defaults are the vanilla ratios). With `chain` every level is reduced from the next higher level that has a
    mesh instead of from the start mesh. `make_very_high` (start 'high' only) copies the high mesh into an empty L0. `protect` multiplies the share kept
    by parts that must keep their look (1 turns it off). Returns {'done': [(model name, [slots], methods)], 'skipped': [(model name, why)], 'triangles': {slot: n}, 'methods': {method: meshes made}}."""
    ratios = ratios or VANILLA[start]
    s = SLOT_INDEX[start]
    below = [slot for slot, _ in LEVELS[s + 1:]]
    report = {"done": [], "skipped": [], "triangles": {slot: 0 for slot, _ in LEVELS}, "methods": {}}
    for o in models:
        lods = o.sz_lods
        src = getattr(lods, start).mesh
        if src is None:
            report["skipped"].append((o.name, f"no {LABEL[start]} (L{s}) mesh to start from"))
            continue
        cls = part_class(o, bones) if bones is not None and protect > 1.0 else None
        factor = protect if cls else 1.0
        base_tris = triangles(src)
        filled, used_methods = [], set()
        source = src
        if start == "high" and make_very_high and getattr(lods, "very_high").mesh is None:
            mesh = src.copy()
            mesh.name = f"{o.name}.{LABEL['very_high']}"
            lods.very_high.mesh = mesh
            filled.append("very_high")
        for slot in below:
            ratio = ratios.get(slot, 0.0)
            lod = getattr(lods, slot)
            if lod.mesh is not None and not overwrite:
                if chain:
                    source = lod.mesh
                continue
            if ratio <= 0:
                continue
            want = max(MIN_TRIANGLES, int(base_tris * min(1.0, ratio * factor)))
            have = triangles(source)
            if want >= have:
                mesh, how = source.copy(), "copy"
            else:
                mesh, how = reduce(source, want / have, method, keep_shading, shading_from=src)
            mesh.name = f"{o.name}.{LABEL[slot]}"
            old = lod.mesh
            lod.mesh = mesh
            if old is not None and old.users == 0:
                bpy.data.meshes.remove(old)
            filled.append(slot)
            used_methods.add(how)
            report["methods"][how] = report["methods"].get(how, 0) + 1
            report["triangles"][slot] += triangles(mesh)
            if chain:
                source = mesh
        report["triangles"][start] += base_tris
        if filled:
            report["done"].append((o.name, filled, "+".join(sorted(used_methods)) or "copy"))
    return report
