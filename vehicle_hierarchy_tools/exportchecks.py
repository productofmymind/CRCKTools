"""Export-time problems Sollumz does not report: too few LODs. Read-only."""
from . import sollumz_bridge as sz
from .analysis import INFO, Finding

MIN_LODS = 4  # vehicles normally carry four LOD meshes


def validate_exports(v):
    out = []
    most = max((len(sz.lod_meshes(m)) for m in v.models), default=0)  # whole vehicle: wheels and glass may have fewer
    if 0 < most < MIN_LODS:
        out.append(Finding(INFO, "FEW_LODS",
                           f"No model has more than {most} LOD mesh(es); vehicles normally carry {MIN_LODS}. "
                           "Generate LODs fills the missing ones.", v.frag.name, "object"))
    return out
