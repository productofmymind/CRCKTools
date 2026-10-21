"""Auto Arrange: the moves that put a vehicle's parts where vanilla vehicles have them. Read-only; the result is a list of fix dicts
(fixes.py) for the preview/apply flow.

What counts as "the right place", and the evidence:
- A bone's parent: the parent rules (hand-written, plus those counted from vanilla vehicles).
- A model or collision sits on the bone it is named after (all 977 bound ones on 12 vanilla vehicles, 'wheel_lf.child' being on wheel_lf).
- Models hang directly under the Drawable, collisions under the Bound Composite, because Sollumz exports nothing else.
Sibling order is deliberately left alone: vanilla vehicles have no common order (their bone order is each vehicle's own creation order).
"""
import bpy

from . import analysis, fixes

PLACEMENT = ("HV020_PARENT", "HV021_WINDOW_NOT_IN_DOOR", "HV022_BIKE_WHEEL_PARENT", "NESTED_MODEL", "MODEL_UNBOUND",
             "BOUND_UNBOUND", "BOUND_OUTSIDE_COMPOSITE", "BOUND_ELSEWHERE")


def plan(v, profile="AUTO"):
    """(fixes, notes): the placement fixes, and a line for every misplaced thing that has no fix (nothing says where it goes)."""
    found = [f for f in analysis.validate(v, profile) if f.code in PLACEMENT]
    planned = [f.fix for f in found if f.fix]
    in_bounds = {o.name for o in v.bounds}
    bones = v.frag.data.bones
    need_physics = {f["bone"] for f in planned if f["op"] == "bind_objects" and not f.get("optin")
                    and any(n in in_bounds for n in f["objects"]) and not bones[f["bone"]].sollumz_use_physics}
    planned = fixes.merge_binds(planned) + [{"op": "enable_physics", "bone": b} for b in sorted(need_physics)]
    notes = [f"{f.target}: {f.message}" for f in found if not f.fix and f.code != "BOUND_ELSEWHERE"]
    return fixes.dedupe(planned), notes
