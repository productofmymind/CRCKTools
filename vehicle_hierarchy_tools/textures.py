"""Default textures for new materials.

A material Sollumz creates has blank images with no file name, so it exports every sampler without a texture name. Vanilla vehicles fill them
with a small set of generic textures. The names come from `data/texture_defaults.json`, counted over vanilla vehicles:

- a texture used by at least half the counted vehicles (3 at least) and in no vehicle's own .ytd is *external*: the game has it, so only the name is
  exported (the image is the real DDS if Sollumz's shared textures directories hold it, else a named placeholder, as Sollumz's own import does);
- `blank` and `normal_flat_small` are in vanilla vehicles' own .ytd, always the same 4x4 constant colour. They are generated here (DDS, DXT5 and
  DXT1 as vanilla) and the node is set to Embedded, so the export carries them in the yft's own texture dictionary.
"""
import json
import os
import re
import struct

import bpy

from . import sollumz_bridge as sz

TABLE = os.path.join(os.path.dirname(__file__), "data", "texture_defaults.json")

# Texture name -> (FourCC, one 4x4 block). The images are constant colours, so each mip level is that block.
GENERATED = {
    "blank": (b"DXT5", bytes.fromhex("0100499224499224") + b"\xff\xff\xff\xff\x00\x00\x00\x00"),  # white, alpha 0 (every alpha index picks alpha1 = 0)
    "normal_flat_small": (b"DXT1", bytes.fromhex("ff7b1f84aaaaaaaa")),  # two colours blended 2:1: about (126, 127, 255), a flat normal
}
FALLBACKS = {"SpecSampler": "vehicle_generic_smallspecmap", "DirtSampler": "vehicle_genericmud_car", "DiffuseSampler2": "blank"}
FLAT_NORMAL = "normal_flat_small"
_cache = {}


def dds_bytes(name):
    """A DDS file for a generated texture: 4x4, one mip level, same format and layout as the vanilla files."""
    fourcc, block = GENERATED[name]
    header = struct.pack("<4s7I44xII4s10I", b"DDS ", 124, 0xA1007, 4, 4, len(block), 1, 1,
                         32, 0x4, fourcc, 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
    return header + block


def build(data):
    """{shader: {sampler: texture name or None}} from the counts in texture_defaults.json (see the module doc)."""
    n = len(data["vehicles"])
    need = max(3, (n + 1) // 2)
    usable = {name for name, i in data["names"].items()
              if (i["own"] == 0 and i["vehicles"] >= need) or (name in GENERATED and i["vehicles"] >= 1)}

    def pick(counts):
        cand = {t: c for t, c in counts.items() if t in usable and c >= 2}
        return max(cand.items(), key=lambda kv: kv[1])[0] if cand else None

    by_shader, paint = {}, {}
    for shader, info in data["shaders"].items():
        by_shader[shader] = {s: pick(c) for s, c in info["samplers"].items()}
        if shader.startswith("vehicle_paint"):
            for s, c in info["samplers"].items():
                merged = paint.setdefault(s, {})
                for t, k in c.items():
                    merged[t] = merged.get(t, 0) + k
    by_shader["vehicle_paint*"] = {s: pick(c) for s, c in paint.items()}
    return by_shader


def _table():
    mtime = os.path.getmtime(TABLE)
    if _cache.get("mtime") != mtime:
        with open(TABLE, encoding="utf-8") as fh:
            _cache.update(mtime=mtime, defaults=build(json.load(fh)))
    return _cache["defaults"]


def default_name(shader_filename, sampler, table=None):
    """The texture name vanilla vehicles give this sampler of this shader, or None. Shaders the survey lacks use what `vehicle_paint*` do (paint
    shaders only) or a neutral fallback: the shared spec for a spec sampler, the shared mud for dirt, `blank` for a second diffuse, a flat normal for
    a bump sampler."""
    table = table or _table()
    shader = shader_filename.lower()
    for key in (shader, "vehicle_paint*" if shader.startswith("vehicle_paint") else None):
        if table.get(key, {}).get(sampler):
            return table[key][sampler]
    if sampler in FALLBACKS:
        return FALLBACKS[sampler]
    return FLAT_NORMAL if "bump" in sampler.lower() else None


def texture_image(name, is_data=False):
    """The image for a texture name: one already loaded, else a generated DDS, else the DDS from Sollumz's shared textures directories,
    else a placeholder called after the name (what Sollumz's own import makes for a texture that is not embedded)."""
    dds = f"{name}.dds"
    img = bpy.data.images.get(dds) or bpy.data.images.get(name)
    if img is None and name in GENERATED:
        data = dds_bytes(name)
        img = bpy.data.images.new(name=dds, width=1, height=1)
        img.source = "FILE"
        img.filepath = f"//{dds}"
        img.pack(data=data, data_len=len(data))
    if img is None:
        path = sz._mod("ydr.ydrimport").lookup_texture_file(name, None)
        if path:
            img = bpy.data.images.load(str(path), check_existing=True)
    if img is None:
        img = bpy.data.images.new(name=name, width=4, height=4)
        img.source = "FILE"
        img.filepath = f"//{dds}"
    if is_data:
        img.colorspace_settings.is_data = True
    return img


def apply_defaults(mat):
    """Give every empty sampler of a shader material its default texture. Returns [(sampler, texture name)]. Samplers that already hold a texture
    are left alone."""
    done = []
    for node in mat.node_tree.nodes:
        if node.type != "TEX_IMAGE" or node.sollumz_texture_name:
            continue
        name = default_name(mat.shader_properties.filename, node.name)
        if name is None:
            continue
        old = node.image
        node.image = texture_image(name, is_data="bump" in node.name.lower())
        if name in GENERATED:
            node.texture_properties.embedded = True
        if old is not None and old.users == 0 and not old.filepath and old.name.startswith("Texture"):
            bpy.data.images.remove(old)  # the blank 512x512 Sollumz put there
        done.append((node.name, name))
    return done
