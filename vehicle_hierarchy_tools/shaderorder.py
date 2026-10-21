"""Shader order like vanilla vehicles: a stable sort by the position each shader usually has in the shader group.

Vanilla vehicles share one sequence (paint first, then the inner glass, shutters and lights, badges and generic mesh, plate, detail, dashboard, the outer glass,
interior, cutout and tyres last; measured on 11 vehicles). Nothing requires a particular order; the ranking here is what the vanilla files show.
"""
import json
import os

BUNDLED = os.path.join(os.path.dirname(__file__), "data", "shader_order.json")
UNKNOWN_RANK = 0.5      # a shader not seen in vanilla files sits in the middle, in the order it already has
PAINT_RANK = 0.05       # any other vehicle_paint* shader sorts with the paints
_cache = {}


def table(path=""):
    path = path or BUNDLED
    if path not in _cache:
        with open(path, encoding="utf-8") as fh:
            _cache[path] = {k: v["rank"] for k, v in json.load(fh)["shaders"].items()}
    return _cache[path]


def firm(path=""):
    """[(first, second, vehicles)]: pairs of shaders that were in this order in every vanilla vehicle that has both (at least 6 of them)."""
    with open(path or BUNDLED, encoding="utf-8") as fh:
        return [tuple(x) for x in json.load(fh)["firm"]]


def violations(shaders, pairs=None):
    """The firm pairs `shaders` (a list of shader names in their current order) breaks: [(first, second)] where a copy of `first` comes after a copy of `second`."""
    names = [base_name(s) for s in shaders]
    out = []
    for first, second, _ in (pairs if pairs is not None else firm()):
        a = [i for i, n in enumerate(names) if n == first]
        b = [i for i, n in enumerate(names) if n == second]
        if a and b and max(a) > min(b):
            out.append((first, second))
    return out


def base_name(shader):
    return (shader or "").lower().replace(".sps", "")


def rank(shader, ranks=None):
    ranks = ranks if ranks is not None else table()
    n = base_name(shader)
    if n in ranks:
        return ranks[n]
    return PAINT_RANK if n.startswith("vehicle_paint") else UNKNOWN_RANK


def sorted_items(items, ranks=None):
    """`items` = [(key, shader name)] in their current order -> the same items in vanilla order (stable: equal ranks keep their order)."""
    return sorted(items, key=lambda it: rank(it[1], ranks))


def agreement(actual, ranks):
    """Share of pairs of different shaders that `ranks` puts in the order `actual` (a list of shader names) has them; None when there is no pair."""
    ok = n = 0
    for i in range(len(actual)):
        for j in range(i + 1, len(actual)):
            if base_name(actual[i]) == base_name(actual[j]):
                continue
            a, b = rank(actual[i], ranks), rank(actual[j], ranks)
            if a == b:
                continue
            n += 1
            ok += a < b
    return ok / n if n else None
