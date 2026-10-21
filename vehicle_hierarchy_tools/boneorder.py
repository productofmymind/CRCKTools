"""Reorder sibling bones (bone index = depth-first position in sibling order).

Blender has no operator for this and re-parenting does not change sibling order, but a newly created edit bone is
appended, so the affected siblings are recreated in the wanted order. Everything on the old bones is copied
generically (edit-bone, Bone, PoseBone, constraints, custom properties, bone collections) and then verified by
comparing a fingerprint of every bone before and after. Nothing is trusted to a hand-picked property list.
"""
import bpy

_SKIP_EDIT = {"name", "parent", "matrix", "children", "children_recursive", "parent_recursive", "collections",
              "bbone_custom_handle_start", "bbone_custom_handle_end", "length", "basename", "rna_type"}
_SKIP_BONE = {"name", "parent", "children", "children_recursive", "parent_recursive", "collections", "rna_type",
              "bbone_custom_handle_start", "bbone_custom_handle_end", "head", "tail", "head_local", "tail_local",
              "matrix", "matrix_local", "length", "basename", "select", "select_head", "select_tail"}
_SKIP_POSE = {"name", "bone", "parent", "child", "children", "children_recursive", "parent_recursive", "rna_type",
              "matrix", "matrix_basis", "matrix_channel", "head", "tail", "length", "basename", "constraints",
              "bbone_custom_handle_start", "bbone_custom_handle_end", "custom_shape_transform", "select"}
_SKIP_CONSTRAINT = {"type", "is_override_data_valid", "error_location", "error_rotation", "rna_type"}


def _plain(v):
    if isinstance(v, (set, frozenset)):  # enum-flag properties (e.g. Sollumz bone flags) must stay sets
        return set(v)
    try:
        return tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
    except TypeError:
        return v


def _custom(v):
    """Plain custom-property values only (str/int/float/bool and lists of them); anything Blender stores as a
    group or array object is skipped because writing it back is not safe."""
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "to_list"):
        v = v.to_list()
    if isinstance(v, list) and v and all(isinstance(x, (str, int, float, bool)) for x in v):
        return list(v)
    return None


def serialize(struct, skip=()):
    """Writable properties of an RNA struct as plain data; nested property groups and collections recurse."""
    out = {}
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in skip or k == "rna_type":
            continue
        try:
            if p.type == "POINTER":
                v = getattr(struct, k)
                if v is None:
                    out[k] = ("ptr", None)
                elif isinstance(v, bpy.types.ID):
                    if not p.is_readonly:
                        out[k] = ("id", v)
                else:
                    out[k] = ("group", serialize(v))
            elif p.type == "COLLECTION":
                items = getattr(struct, k)
                if hasattr(items, "add") and not p.is_readonly:
                    out[k] = ("coll", [serialize(i) for i in items])
            elif not p.is_readonly:
                out[k] = ("val", _plain(getattr(struct, k)))
        except (AttributeError, RuntimeError, TypeError):
            continue
    # custom (ID) properties set from Python
    try:
        registered = {p.identifier for p in struct.bl_rna.properties}
        out["__idprops__"] = ("val", {k: _custom(struct[k]) for k in struct.keys()
                                      if k not in registered and _custom(struct[k]) is not None})
    except (AttributeError, TypeError):
        pass
    return out


def apply(struct, data):
    for k, (kind, v) in data.items():
        try:
            if k == "__idprops__":
                for ik, iv in v.items():
                    struct[ik] = iv
            elif kind == "val":
                setattr(struct, k, v)
            elif kind in ("id", "ptr"):
                setattr(struct, k, v)
            elif kind == "group":
                apply(getattr(struct, k), v)
            elif kind == "coll":
                coll = getattr(struct, k)
                coll.clear()
                for item in v:
                    apply(coll.add(), item)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue


def _constraints(pb):
    return [(c.type, serialize(c, _SKIP_CONSTRAINT)) for c in pb.constraints]


def fingerprint(frag):
    """{bone name: comparable snapshot of everything we copy} (order-independent)."""
    arm = frag.data
    fp = {}
    for b in arm.bones:
        pb = frag.pose.bones[b.name]
        fp[b.name] = {
            "parent": b.parent.name if b.parent else None,
            "matrix_local": tuple(tuple(round(x, 5) for x in r) for r in b.matrix_local),
            "bone": _flat(serialize(b, _SKIP_BONE)),
            "pose": _flat(serialize(pb, _SKIP_POSE)),
            "constraints": [(t, _flat(d)) for t, d in _constraints(pb)],
            "collections": sorted(c.name for c in b.collections),
        }
    return fp


def _flat(d):
    """Make serialize() output comparable: IDs by name, floats rounded."""
    out = {}
    for k, (kind, v) in d.items():
        if kind == "id" or kind == "ptr":
            out[k] = getattr(v, "name", v)
        elif kind == "group":
            out[k] = _flat(v)
        elif kind == "coll":
            out[k] = [_flat(i) for i in v]
        else:
            out[k] = _round(v)
    return out


def _round(v):
    if isinstance(v, (set, frozenset)):
        return ("set", tuple(sorted(v)))
    if isinstance(v, float):
        return round(v, 5)
    if isinstance(v, (tuple, list)):
        return tuple(_round(x) for x in v)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def siblings(bone, arm):
    """Siblings in current order, including the bone itself."""
    if bone.parent is not None:
        return list(bone.parent.children)
    return [b for b in arm.bones if b.parent is None]


def plan_move(frag, bone_name, delta):
    """(new sibling order as names, first changed position) or None when the move is impossible."""
    arm = frag.data
    bone = arm.bones.get(bone_name)
    if bone is None:
        return None
    sibs = [b.name for b in siblings(bone, arm)]
    i = sibs.index(bone_name)
    j = i + delta
    if not 0 <= j < len(sibs) or len(sibs) < 2:
        return None
    new = list(sibs)
    new.insert(j, new.pop(i))
    return new, min(i, j)


def move(context, frag, bone_name, delta):
    """Move a bone `delta` places among its siblings. Returns (report lines, verified: bool)."""
    arm = frag.data
    plan = plan_move(frag, bone_name, delta)
    if plan is None:
        return [f"{bone_name}: cannot move {delta:+d} among its siblings."], True
    new_order, first = plan
    todo = new_order[first:]  # siblings from the first changed position on are recreated in the new order
    before = fingerprint(frag)
    snap = {}
    for n in todo:
        b, pb = arm.bones[n], frag.pose.bones[n]
        snap[n] = {"bone": serialize(b, _SKIP_BONE), "pose": serialize(pb, _SKIP_POSE),
                   "constraints": _constraints(pb), "collections": [c.name for c in b.collections],
                   "active": arm.bones.active is not None and arm.bones.active.name == n}
    from . import fixes
    fixes._edit_bones(context, frag, lambda ebs: _rebuild(ebs, todo))
    for n in todo:
        b, pb, s = arm.bones[n], frag.pose.bones[n], snap[n]
        apply(b, s["bone"])
        apply(pb, s["pose"])
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        for ctype, cdata in s["constraints"]:
            apply(pb.constraints.new(ctype), cdata)
        for cname in s["collections"]:
            col = arm.collections_all.get(cname)
            if col is not None:
                col.assign(b)
        if s["active"]:
            arm.bones.active = b
    after = fingerprint(frag)
    bad = [n for n in before if before[n] != after.get(n)]
    lines = [f"{bone_name}: moved {delta:+d} among its siblings; {len(todo)} sibling bone(s) recreated"]
    if bad:
        lines.append(f"WARNING: {len(bad)} bone(s) differ from before the move: {', '.join(bad[:6])}. Use Ctrl+Z.")
    else:
        lines.append(f"Verified: all {len(before)} bones keep identical properties, constraints and collections.")
    return lines, not bad


def _rebuild(ebs, todo):
    for n in todo:
        old = ebs[n]
        new = ebs.new("__vht_" + n)
        for p in old.bl_rna.properties:
            k = p.identifier
            if k in _SKIP_EDIT or p.is_readonly or p.type == "POINTER":
                continue
            try:
                setattr(new, k, getattr(old, k))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        new.parent = old.parent
        new.use_connect = old.use_connect
        for ch in list(old.children):
            connected = ch.use_connect
            ch.parent = new
            ch.use_connect = connected
        ebs.remove(old)
        new.name = n


def simulated_index_shift(frag, bone_name, delta):
    """Number of bones whose export index changes if `bone_name` moves `delta` places (depth-first walk)."""
    arm = frag.data
    plan = plan_move(frag, bone_name, delta)
    if plan is None:
        return 0
    new_order, _ = plan
    parent = arm.bones[bone_name].parent
    before = [b.name for b in arm.bones]
    order = []

    def walk(b):
        order.append(b.name)
        kids = [c.name for c in b.children]
        if parent is not None and b.name == parent.name:
            kids = new_order
        for k in kids:
            walk(arm.bones[k])

    roots = [b.name for b in arm.bones if b.parent is None]
    if parent is None:
        roots = new_order
    for r in roots:
        walk(arm.bones[r])
    return sum(1 for a, b in zip(before, order) if a != b)
