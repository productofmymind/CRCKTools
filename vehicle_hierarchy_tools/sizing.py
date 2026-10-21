"""Estimate the GPU-side size of an export by running Sollumz's own exporter to a temp folder and measuring it.

A GPU section above 256 MiB is commonly cited as a problem in game. This is an
estimate from buffer layouts and embedded DDS files, not the resource header, so treat it as approximate.
"""
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET

import bpy

LIMIT = 256 * 1024 * 1024
# bytes per vertex element in the exported layout (GTAV1)
ELEMENT_BYTES = {"Position": 12, "Normal": 12, "BlendWeights": 4, "BlendIndices": 4, "Tangent": 16,
                 **{f"Colour{i}": 4 for i in range(2)}, **{f"TexCoord{i}": 8 for i in range(8)}}
LODS = ("High", "Medium", "Low", "VeryLow")


def measure(directory, xml_name):
    """{"vertex", "index", "textures": [(name, bytes)], "total"} for an exported CodeWalker XML folder."""
    root = ET.parse(os.path.join(directory, xml_name)).getroot()
    vertex = index = 0
    for lod in LODS:
        for g in root.iterfind(f"Drawable/DrawableModels{lod}/Item/Geometries/Item"):
            layout = g.find("VertexBuffer/Layout")
            stride = sum(ELEMENT_BYTES.get(e.tag, 0) for e in layout) if layout is not None else 0
            rows = [r for r in (g.findtext("VertexBuffer/Data") or "").split("\n") if r.strip()]
            vertex += stride * len(rows)
            index += 2 * len((g.findtext("IndexBuffer/Data") or "").split())
    textures = []
    for r, _, files in os.walk(directory):
        textures += [(f, os.path.getsize(os.path.join(r, f))) for f in files if f.lower().endswith(".dds")]
    tex = sum(b for _, b in textures)
    return {"vertex": vertex, "index": index, "textures": sorted(textures, key=lambda t: -t[1]), "total": vertex + index + tex}


def estimate(context, frag):
    """Run the real export for `frag` into a temp folder (selection and active object restored) and measure it."""
    out = tempfile.mkdtemp(prefix="vht_size_")
    view = context.view_layer
    prev_active, prev_sel = view.objects.active, [o for o in view.objects if o.select_get()]
    try:
        for o in prev_sel:
            o.select_set(False)
        frag.select_set(True)
        view.objects.active = frag
        bpy.ops.sollumz.export_assets(directory=out, direct_export=True, use_custom_settings=True,
                                      target_formats={"CWXML"}, target_versions={"GEN8"}, limit_to_selected=True)
        return measure(out, f"{frag.name}.yft.xml")
    finally:
        frag.select_set(False)
        for o in prev_sel:
            o.select_set(True)
        view.objects.active = prev_active
        shutil.rmtree(out, ignore_errors=True)


def describe(m):
    mb = lambda b: f"{b / 1048576:.1f} MiB"
    lines = [f"Estimated GPU data: {mb(m['total'])} of {mb(LIMIT)} (commonly cited limit)",
             f"  vertex buffers {mb(m['vertex'])}, index buffers {mb(m['index'])}, textures {mb(sum(b for _, b in m['textures']))}"]
    lines += [f"  {n}: {mb(b)}" for n, b in m["textures"][:5]]
    if m["total"] >= LIMIT:
        lines.append("WARNING: over the commonly cited limit; this can cause resource problems in game. "
                     "Reduce texture sizes first.")
    return "\n".join(lines)
