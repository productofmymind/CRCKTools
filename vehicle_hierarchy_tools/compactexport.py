"""Compact export: Sollumz's own exporter, with one change, a vertex merge that tolerates float noise.

Why: Sollumz writes one vertex per Blender face corner and merges two only when every attribute (position, normal, tangent, UVs, colours, weights) is equal
after rounding to 6 decimals. Blender computes the normal of a corner from its surrounding faces, and corners of one vertex end up with normals that differ
in the 4th to 6th decimal; they stay separate vertices. On the mammoth, 14% of the vertices (161,211 written, 138,260 distinct once normals are compared to 3
decimals) were such copies. A file of the same vehicle written by another tool has 139,419. Vertex buffers are most of a yft, so the file grows about as much.

What this does: runs `sollumz.export_assets` with the user's own Sollumz export settings (format, version, selection, mesh domain), and for the duration of the
call swaps Sollumz's `dedupe_and_get_indices` (ydr/ydrexport.py) for `dedupe_and_get_indices` below, which rounds normals and tangents to 3 decimals (0.06
degrees) when deciding what is the same vertex. The surviving vertex keeps its own un-rounded values. Everything else (materials, bones, bounds, physics,
textures, file writing) is Sollumz's. The swap is undone in a finally block.
"""
import contextlib
import os
import time

import bpy
import numpy as np

from . import sollumz_bridge as sz

DEFAULT_DECIMALS = 6
DECIMALS = {"Normal": 3, "Tangent": 3}   # normals and tangents: 0.001 is about 0.06 degrees
STATS = {"stock": 0, "compact": 0}


def _unique(vertex_arr, decimals):
    names = vertex_arr.dtype.names
    cols = []
    for name in names:
        a = vertex_arr[name].astype(np.float64).reshape(len(vertex_arr), -1)
        cols.append(np.round(a, decimals.get(name, DEFAULT_DECIMALS)) + 0.0)  # + 0.0 turns -0.0 into 0.0
    flat = np.concatenate(cols, axis=1)
    return np.unique(flat, axis=0, return_index=True, return_inverse=True)


def dedupe_and_get_indices(vertex_arr):
    """Same contract as Sollumz's function of that name: (vertices without duplicates, indices in triangle order)."""
    _, first, inverse = _unique(vertex_arr, DECIMALS)
    STATS["compact"] += len(first)
    STATS["stock"] += len(_unique(vertex_arr, {})[1])
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
