"""Vehicle rules loaded from data/vehicle_rules.json. Name tokens use {1..3} / {a..z} / {a,b} expansion."""
import fnmatch
import json
import os
import re

BUNDLED = os.path.join(os.path.dirname(__file__), "data", "vehicle_rules.json")
SEVERITY_BY_CONF = {"H": "ERROR", "M": "WARNING", "L": "INFO"}
_cache = {}


def expand(token):
    m = re.search(r"\{([^{}]+)\}", token)
    if not m:
        return [token]
    body, out = m.group(1), []
    if ".." in body:
        a, b = body.split("..")
        items = [str(i) for i in range(int(a), int(b) + 1)] if a.isdigit() else [chr(c) for c in range(ord(a), ord(b) + 1)]
    else:
        items = body.split(",")
    for it in items:
        out += expand(token[:m.start()] + it + token[m.end():])
    return out


class Rules:
    def __init__(self, data):
        self.data = data
        self.names = {n for line in data["names"] for tok in line.split() for n in expand(tok)}
        self.names |= set(data.get("observed_in_vanilla", {}).get("names", []))
        self.lower = {n.lower(): n for n in self.names}
        self.parents = data["parents"]
        self.profiles = data["profiles"]
        self.observed = data.get("observed_parents", {}).get("counts", {})
        self._merged = {}

    def seen(self, name):
        """{parent: number of vanilla vehicles} counted over vanilla vehicles."""
        return self.observed.get(name, {})

    def known(self, name):
        return name.lower() in self.lower

    def _hand_rule(self, name):
        """Exact name first, then the first matching wildcard entry."""
        if name in self.parents:
            return self.parents[name]
        for pat, rule in self.parents.items():
            if "*" in pat and fnmatch.fnmatchcase(name, pat):
                return rule
        return None

    def parent_rule(self, name):
        """The rule for a bone name: {parents (the usual one first), conf, why, ...} or None.

        Hand-written rules supply the parents and confidence. Counts from vanilla vehicles add every parent
        vanilla has used (so a vanilla placement is never flagged), and lower the confidence to L (reported, never applied) when 3 or more
        vehicles are counted and fewer than 80% agree, as with sirens. A name with no hand-written rule gets one from the counts alone:
        M when 5 or more vehicles are counted and 80% or more agree, L when 2 or more all agree. misc_* are generic slots that vanilla
        puts anywhere, so they never get one."""
        if name in self._merged:
            return self._merged[name]
        hand, obs = self._hand_rule(name), self.seen(name)
        total = sum(obs.values())
        top, n_top = max(obs.items(), key=lambda kv: kv[1]) if obs else (None, 0)
        by_use = [p for p, _ in sorted(obs.items(), key=lambda kv: -kv[1])]
        why = ("Vanilla: " + ", ".join(f"{p} x{n}" for p, n in sorted(obs.items(), key=lambda kv: -kv[1])[:4]) + ".") if obs else ""
        rule = None
        if hand is not None:
            rule = dict(hand)
            if not hand.get("door"):
                rule["parents"] = list(hand["parents"]) + [p for p in by_use if p not in hand["parents"]]
            if total >= 3 and n_top / total < 0.8 and hand["conf"] != "H":
                rule["conf"] = "L"
            if why:
                rule["why"] = (hand.get("why", "") + " " + why).strip()
        elif not name.startswith("misc_") and total:
            if total >= 5 and n_top / total >= 0.8:
                rule = {"parents": by_use, "conf": "M", "why": why, "learned": True}
            elif total >= 2 and n_top == total:
                rule = {"parents": [top], "conf": "L", "why": why, "learned": True}
        self._merged[name] = rule
        return rule

    @staticmethod
    def parent_ok(parent_name, allowed):
        return any(fnmatch.fnmatchcase(parent_name, a) for a in allowed)

    def profile(self, key):
        p = dict(self.profiles[key])
        if "extends" in p:
            base = self.profile(p["extends"])
            for k in ("required", "forbidden", "recommended"):
                p[k] = base.get(k, []) + p.get(k, [])
        return p


def load(path=""):
    path = path or BUNDLED
    mtime = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, encoding="utf-8") as f:
        rules = Rules(json.load(f))
    _cache[path] = (mtime, rules)
    return rules
