"""The vehicle shaders Sollumz offers (every `vehicle_*` shader) and the textures a new material of each starts with."""
from . import paint, sollumz_bridge as sz, textures

_items = []  # Blender keeps only references to the strings of a dynamic enum, so the list must outlive the callback


def names():
    sm = sz._mod("ydr.shader_materials")
    return sorted(f for f in sm.shadermats_by_filename if f.startswith("vehicle_"))


def items(self=None, context=None):
    """(filename, label, description) for the dropdown."""
    if not _items:
        try:
            for f in names():
                _items.append((f, f.replace(".sps", ""), (paint.SHADER_NOTES.get(f) or ("", ""))[1]))
        except Exception:  # Sollumz not enabled yet
            return [("", "Sollumz is not enabled", "")]
    return _items


def samplers(filename):
    """Names of the texture samplers a shader has, in Sollumz's order."""
    from szio.gta5 import ShaderManager
    d = ShaderManager.find_shader(filename)
    return [p.name for p in d.parameters if type(p).__name__ == "ShaderParameterTextureDef"] if d else []


def preview(filename):
    """[(sampler, texture name or None)]: what a new material of this shader starts with. None = the vehicle's own texture."""
    rules = textures.sampler_rules(filename)
    return [(s, textures.default_name(filename, s)) for s in samplers(filename) if rules.get(s) != "optional"]
