"""Export-time problems that Sollumz only reports while exporting (cloth rules) or not at all (too few LODs). Read-only."""
from . import sollumz_bridge as sz
from .analysis import INFO, WARNING, Finding

CLOTH_MAX_VERTS = 255  # a cloth control mesh cannot have more vertices than this
MIN_LODS = 4           # vehicles normally carry four LOD meshes


def _shader_manager():
    from szio.gta5 import ShaderManager  # Sollumz's own shader table, as its cloth code uses
    return ShaderManager


def cloth_material_counts(mesh):
    """(cloth materials, other materials) of a mesh, by Sollumz's shader definitions."""
    sm = _shader_manager()
    cloth = other = 0
    for mat in mesh.materials:
        props = getattr(mat, "shader_properties", None)
        d = sm.find_shader(props.filename) if props is not None else None
        if d is not None and d.is_cloth:
            cloth += 1
        else:
            other += 1
    return cloth, other


def validate_exports(v):
    out = []
    for m in v.models:
        me = m.data
        if m.type != "MESH" or me is None:
            continue
        cloth, other = cloth_material_counts(me)
        if cloth == 0:
            continue
        if cloth > 1 or other:
            out.append(Finding(WARNING, "CLOTH_MATERIALS",
                               f"'{m.name}' has a cloth material but {cloth} cloth and {other} other material slots; "
                               "a cloth mesh must have exactly one material.", m.name, "object"))
        elif len(me.vertices) > CLOTH_MAX_VERTS:
            out.append(Finding(WARNING, "CLOTH_VERTS",
                               f"Cloth mesh '{m.name}' has {len(me.vertices)} vertices; a cloth mesh can have at most {CLOTH_MAX_VERTS}.",
                               m.name, "object"))

    most = max((len(sz.lod_meshes(m)) for m in v.models), default=0)  # whole vehicle: wheels and glass may have fewer
    if 0 < most < MIN_LODS:
        out.append(Finding(INFO, "FEW_LODS",
                           f"No model has more than {most} LOD mesh(es); vehicles normally carry {MIN_LODS}. "
                           "Generate LODs fills the missing ones.", v.frag.name, "object"))
    return out
