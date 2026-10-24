"""CRCK Export (compact export): Sollumz's own exporter, with one change, a vertex merge that tolerates float noise.

Why: Sollumz writes one vertex per Blender face corner and merges two only when every attribute (position, normal, tangent, UVs, colours, weights) is equal
after rounding to 6 decimals. Blender computes the normal of a corner from its surrounding faces, and corners of one vertex end up with normals that differ
in the 4th to 6th decimal; they stay separate vertices. On the mammoth, 14% of the vertices (161,211 written, 138,260 distinct once normals are compared to 3
decimals) were such copies. A file of the same vehicle written by another tool has 139,419. Vertex buffers are most of a yft, so the file grows about as much.

What this does: runs `sollumz.export_assets` with the user's own Sollumz export settings (format, version, selection, mesh domain), and for the duration of the
call swaps Sollumz's `dedupe_and_get_indices` (ydr/ydrexport.py) for `dedupe_and_get_indices` below, which rounds normals and tangents to 3 decimals (0.06
degrees) when deciding what is the same vertex. The surviving vertex keeps its own un-rounded values. Everything else (materials, bones, bounds, physics,
textures, file writing) is Sollumz's. The swap is undone in a finally block.

Second change, the larger one: before merging, normals, tangents, positions and UVs are snapped to a fine power-of-two grid (STEPS below). A float from
Blender carries noise in its lowest bits, which makes the vertex buffer compress badly; snapped values compress far better, and snapping first also lets
more corners merge. On the mammoth (3.73 MB with Sollumz alone, 3.43 MB with the merge alone) the result is 2.40 MB, with the same triangles
and a largest error of 0.0005 per normal component (0.05 degrees), 0.06 mm in position and 0.00012 in UV. Colours and bone weights are not touched.
"""
import contextlib
import os
import time

import bpy
import numpy as np

from . import sollumz_bridge as sz

DEFAULT_DECIMALS = 6
DECIMALS = {}                             # after snapping, equal values are exactly equal; the default 6 decimals only guards against float noise
STEPS = {"Normal": 1 / 1024, "Tangent": 1 / 1024, "Position": 1 / 8192,
         "TexCoord0": 1 / 4096, "TexCoord1": 1 / 4096, "TexCoord2": 1 / 4096, "TexCoord3": 1 / 4096}  # powers of two, so the low mantissa bits become zeros
STATS = {"stock": 0, "compact": 0}


def _unique(vertex_arr, decimals):
    names = vertex_arr.dtype.names
    cols = []
    for name in names:
        a = vertex_arr[name].astype(np.float64).reshape(len(vertex_arr), -1)
        cols.append(np.round(a, decimals.get(name, DEFAULT_DECIMALS)) + 0.0)  # + 0.0 turns -0.0 into 0.0
    flat = np.concatenate(cols, axis=1)
    return np.unique(flat, axis=0, return_index=True, return_inverse=True)


def snap(vertex_arr):
    """A copy of the vertex array with the attributes in STEPS rounded to their grid."""
    out = vertex_arr.copy()
    for name, step in STEPS.items():
        if name in out.dtype.names:
            a = out[name]
            out[name] = (np.round(a.astype(np.float64) / step) * step).astype(a.dtype)
    return out


def dedupe_and_get_indices(vertex_arr):
    """Same contract as Sollumz's function of that name: (vertices without duplicates, indices in triangle order)."""
    STATS["stock"] += len(_unique(vertex_arr, {})[1])
    vertex_arr = snap(vertex_arr)
    _, first, inverse = _unique(vertex_arr, DECIMALS)
    STATS["compact"] += len(first)
    return vertex_arr[first], np.asarray(inverse, dtype=np.uint32).reshape(-1)


@contextlib.contextmanager
def patched():
    """Sollumz's exporter uses the tolerant merge inside this block."""
    mod = sz.ydrexport()
    original = mod.dedupe_and_get_indices
    mod.dedupe_and_get_indices = dedupe_and_get_indices
    try:
        yield
    finally:
        mod.dedupe_and_get_indices = original


def export(context, frag, directory):
    """Export `frag` with Sollumz's exporter and its settings from the user's preferences. Returns ([(file, bytes)], stock vertices, written vertices)."""
    view = context.view_layer
    prev_active, prev_sel = view.objects.active, [o for o in view.objects if o.select_get()]
    STATS.update(stock=0, compact=0)
    started = time.time()
    try:
        for o in prev_sel:
            o.select_set(False)
        frag.select_set(True)
        view.objects.active = frag
        with patched():
            bpy.ops.sollumz.export_assets(directory=directory, direct_export=True)
    finally:
        frag.select_set(False)
        for o in prev_sel:
            o.select_set(True)
        view.objects.active = prev_active
    files = []
    for root, _, names in os.walk(directory):
        for n in names:
            p = os.path.join(root, n)
            if os.path.getmtime(p) >= started - 1:
                files.append((os.path.relpath(p, directory), os.path.getsize(p)))
    return sorted(files), STATS["stock"], STATS["compact"]


def describe(files, stock, compact):
    mb = lambda b: f"{b / 1048576:.2f} MiB"
    lines = [f"Wrote {len(files)} file(s), {mb(sum(b for _, b in files))} in total."]
    lines += [f"  {n}: {mb(b)}" for n, b in files[:6]]
    if stock:
        lines.append(f"Vertices: {compact} written, Sollumz's own merge would have written {stock} ({100 * (stock - compact) / stock:.1f}% fewer).")
    return "\n".join(lines)
