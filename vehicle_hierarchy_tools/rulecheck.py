"""Hierarchy rules from data/vehicle_rules.json (the GTA V vehicle hierarchy reference, corrected against vanilla vehicles
research and a real vehicle). Read-only: findings only. Severity follows the rule's confidence: H error, M warning, L info."""
import re

from . import rules as rules_mod, shaderorder, sollumz_bridge as sz
from .analysis import ERROR, INFO, SUFFIX_RX, WARNING, Finding, bone_links, export_order

PROFILES = ("AUTO", "car", "bike", "truck", "trailer", "heli", "plane", "emergency")


def detect_profile(names):
    n = set(names)
    if "rotor_main" in n:
        return "heli"
    if "swingarm" in n:
        return "bike"
    if {"aileron_l", "aileron_r", "elevator_l", "elevators"} & n:
        return "plane"
    if "attach_female" in n or "attach_male" in n or ("engine" not in n and "seat_dside_f" not in n and "wheel_lr" in n):
        return "trailer"
    if any(x.startswith("siren") for x in n):
        return "emergency"
    return "car"


def edit_distance(a, b, limit=2):
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _numbered(names, prefix):
    out = set()
    for n in names:
        m = re.match(r"^" + prefix + r"(\d+)$", n)
        if m:
            out.add(int(m.group(1)))
    return out


def validate_rules(v, profile=None):
    """`profile` None skips the profile checks; "AUTO" guesses one and downgrades its errors to warnings."""
    rules = rules_mod.load()
    bones = list(v.frag.data.bones)
    if not bones:
        return []
    out = []
    names = [b.name for b in bones]
    name_set = set(names)
    index = {n: i for i, n in enumerate(names)}
    sev = rules_mod.SEVERITY_BY_CONF
    roots = [b for b in bones if b.parent is None]

    if roots and roots[0].name != rules.data["root"]["name"]:
        out.append(Finding(WARNING, "HV001_ROOT_NAME", f"Root bone is '{roots[0].name}'; vehicles use '{rules.data['root']['name']}'.",
                           roots[0].name, "bone"))
    seen = {}
    for n in names:
        seen.setdefault(n.lower(), []).append(n)
    for group in seen.values():
        if len(group) > 1:
            out.append(Finding(ERROR, "HV002_DUPLICATE_NAME", f"Bone names differ only by case ({', '.join(group)}); tags are hashed "
                               "from the upper-cased name, so they collide.", group[1], "bone"))

    for b in bones:
        m = SUFFIX_RX.match(b.name)
        base = m.group(1) if m else b.name
        if rules.known(base):
            continue
        near = sorted(((edit_distance(base.lower(), k), k) for k in rules.lower if len(k) >= 5))[:2]
        close = [rules.lower[k] for d, k in near if d <= 2]
        fix = None
        if len(close) == 1 and close[0] not in name_set and not m:
            fix = {"op": "rename_bone", "bone": b.name, "to": close[0]}
        out.append(Finding(WARNING, "HV003_UNKNOWN_BONE",
                           f"'{b.name}' is not an engine vehicle bone name, so the game will not treat it as a vehicle part "
                           "(fine for helper/custom bones)." + (f" Did you mean '{close[0]}'?" if len(close) == 1 else ""),
                           b.name, "bone", fix))

    props = getattr(roots[0], "bone_properties", None) if roots else None
    if props is not None and props.tag != 0:
        out.append(Finding(WARNING, "HV004_ROOT_TAG", f"Root bone tag is {props.tag}; the root bone uses tag 0.", roots[0].name, "bone",
                           {"op": "auto_tag", "bone": roots[0].name}))
    by_tag = {}
    for b in bones:
        if getattr(b, "bone_properties", None) is not None:
            by_tag.setdefault(b.bone_properties.tag, []).append(b.name)
    for tag, group in by_tag.items():
        if len(group) > 1:
            out.append(Finding(ERROR, "HV005_DUPLICATE_TAG", f"Bones share tag {tag}: {', '.join(group)}. The game resolves parts by tag.",
                               group[1], "bone"))

    if profile:
        key = detect_profile(names) if profile == "AUTO" else profile
        prof = rules.profile(key)
        guess = " (profile guessed from the bones present; choose one to be sure)" if profile == "AUTO" else ""
        for n in prof.get("required", []):
            if n not in name_set:
                out.append(Finding(WARNING if profile == "AUTO" else ERROR, "HV010_MISSING_REQUIRED",
                                   f"Profile '{key}' needs bone '{n}'{guess}.", v.frag.name, "object"))
        for n in prof.get("forbidden", []):
            if n in name_set:
                out.append(Finding(WARNING, "HV011_FORBIDDEN_PRESENT", f"Profile '{key}' should not have bone '{n}'{guess}.", n, "bone"))
        for n in prof.get("recommended", []):
            if n not in name_set:
                out.append(Finding(INFO, "HV010_MISSING_RECOMMENDED", f"Profile '{key}' usually has bone '{n}'{guess}.", v.frag.name, "object"))

    for b in bones:
        rule = rules.parent_rule(b.name)
        if rule is None or b.parent is None or rules.parent_ok(b.parent.name, rule["parents"]):
            continue
        allowed = rule["parents"]
        door = rule.get("door")
        if door:
            if door in name_set:
                out.append(Finding(ERROR, "HV021_WINDOW_NOT_IN_DOOR",
                                   f"'{b.name}' is under '{b.parent.name}', not its door '{door}'. "
                                   "The glass stays put when the door opens.",
                                   b.name, "bone", {"op": "reparent_bone", "bone": b.name, "parent": door}))
            continue
        target = next((a for a in allowed if "*" not in a and a in name_set), None)
        code = "HV022_BIKE_WHEEL_PARENT" if b.name in ("wheel_f", "wheel_r") else "HV020_PARENT"
        out.append(Finding(sev[rule["conf"]], code,
                           f"'{b.name}' is under '{b.parent.name}'; expected {' or '.join(allowed)} ({rule['conf']}). " + rule.get("why", ""),
                           b.name, "bone",
                           {"op": "reparent_bone", "bone": b.name, "parent": target} if target and rule["conf"] in ("H", "M") else None))

    for b in bones:
        rule = rules.parent_rule(b.name)
        if rule and rule.get("joint") and not sz.has_joint_limit(v.frag, b.name):
            out.append(Finding(sev[rule["conf"]], "HV032_NO_JOINT",
                               f"'{b.name}' is an opening part without a rotation or translation limit, so it is not an articulated link "
                               "and never swings or slides open. Add a Limit Rotation/Location constraint (Sollumz exports it as a joint).",
                               b.name, "bone"))

    with_col = {sz.child_of_bone(c).name for c in v.bounds if sz.child_of_bone(c) is not None}
    for b in bones:
        rule = rules.parent_rule(b.name)
        if not (rule and rule.get("glass")):
            continue
        s = sev[rule["conf"]]
        bound = [m for m in v.models if b.name in bone_links(m, name_set)]
        if not (b.sollumz_use_physics and b.name in with_col):
            if b.name in with_col:  # the collision exists: only Use Physics is missing
                fix, how = {"op": "enable_physics", "bone": b.name}, ""
            elif bound and v.composite is not None:  # a window model but no collision: build one from the pane
                fix, how = {"op": "make_glass_collision", "bone": b.name, "object": bound[0].name}, ""
            else:
                fix, how = None, " Nothing is bound to it" + ("" if bound else " (no model), so there is no pane to build a collision from.")
            out.append(Finding(s, "HV040_GLASS_NO_COLLISION",
                               f"Glass bone '{b.name}' needs Use Physics and a collision to shatter.{how}", b.name, "bone", fix))
        if not any(mat is not None and getattr(mat, "shader_properties", None) is not None
                   and mat.shader_properties.name.startswith("vehicle_vehglass")
                   for m in bound for _, me in sz.lod_meshes(m) for mat in me.materials):
            out.append(Finding(s, "HV040_GLASS_NO_SHADER", f"Nothing bound to glass bone '{b.name}' uses a vehicle_vehglass shader.",
                               b.name, "bone",
                               {"op": "glass_shader", "bone": b.name, "objects": [m.name for m in bound]} if bound else None))

    from . import axes
    for b in bones:  # a rotor spins on its local Z: that axis must be the normal of its own blade disc, whatever the tilt
        if re.match(r"^rotor_(main|rear)", b.name):
            wobble = axes.spin_wobble(v.frag, b.name, v.models)
            if wobble is not None and wobble > 1.0:
                out.append(Finding(WARNING, "HV090_ROTOR_AXIS",
                                   f"'{b.name}' spins on its local Z, which is {wobble:.1f} degrees off the normal of its blades' "
                                   "disc, so the rotor wobbles instead of spinning flat. (Vanilla rotors are tilted on purpose but "
                                   "within 0.1 degrees of their disc.) Align the spin axis to the geometry; nothing moves.",
                                   b.name, "bone", {"op": "set_axes", "bone": b.name, "mode": "ALIGN"}))

    for b in bones:
        if b.parent is not None and index[b.parent.name] >= index[b.name]:
            out.append(Finding(ERROR, "HV061_PARENT_ORDER", f"'{b.name}' comes before its parent '{b.parent.name}' in the skeleton.",
                               b.name, "bone"))
    if len(bones) > 128:
        out.append(Finding(INFO, "HV060_NODE_COUNT", f"{len(bones)} bones. Some guides cite a 128-node limit; "
                           "it is unconfirmed.", v.frag.name, "object"))

    base, hi = export_order(v)
    for label, mats in (("base", base), ("_hi", hi)):
        shaders = [m.shader_properties.name for m in mats]
        inner = [i for i, n in enumerate(shaders) if n == "vehicle_vehglass_inner"]
        outer = [i for i, n in enumerate(shaders) if n == "vehicle_vehglass"]
        if inner and outer and max(inner) > min(outer):
            moved = [mats[i] for i in inner]
            rest = [m for i, m in enumerate(mats) if i not in inner]
            at = min(i for i, m in enumerate(rest) if m.shader_properties.name == "vehicle_vehglass")
            rest[at:at] = moved
            out.append(Finding(INFO, "HV062_GLASS_ORDER",
                               f"[{label}] inner glass is ordered after outer glass; transparent materials draw in shader order, so the "
                               "inner pane can be hidden behind the outer one.", mats[max(inner)].name, "material",
                               {"op": "set_material_order", "names": [m.name for m in rest]}))

    for label, mats in (("base", base), ("_hi", hi)):
        broken = [(a, b) for a, b in shaderorder.violations([m.shader_properties.name for m in mats])
                  if (a, b) != ("vehicle_vehglass_inner", "vehicle_vehglass")]  # that pair has its own finding above
        if broken:
            ordered = shaderorder.sorted_items([(m.name, m.shader_properties.name) for m in mats])
            out.append(Finding(INFO, "HV063_SHADER_ORDER",
                               f"[{label}] shader order differs from every vanilla vehicle that has both shaders: "
                               + "; ".join(f"{a} should come before {b}" for a, b in broken[:4]) + (" ..." if len(broken) > 4 else "") + ".",
                               mats[0].name, "material", {"op": "set_material_order", "names": [n for n, _ in ordered]}))

    sirens, glass = _numbered(names, "siren"), _numbered(names, "siren_glass")
    if sirens and sorted(sirens) != list(range(1, max(sirens) + 1)):
        out.append(Finding(INFO, "HV080_SIREN_GAP", f"Siren bones have gaps: {sorted(sirens)}. Missing slots stay dark.", v.frag.name, "object"))
    for g in sorted(glass - sirens):
        out.append(Finding(INFO, "HV080_SIREN_GLASS_ORPHAN", f"siren_glass{g} has no matching siren{g}.", f"siren_glass{g}", "bone"))
    return out
