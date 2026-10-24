import json

import bpy
from bpy.props import EnumProperty, StringProperty

from . import analysis, arrange, boneorder, compactexport, fixes, shaderorder, sizing, sollumz_bridge as sz, textures


def get_vehicle(op, context):
    ok, msg = sz.status()
    if not ok:
        op.report({"ERROR"}, msg)
        return None
    frag = sz.find_fragment(context.active_object)
    if frag is None:
        op.report({"ERROR"}, "Select an object inside a Sollumz Fragment (or the fragment itself).")
        return None
    return analysis.load(frag)


def state(context):
    return context.window_manager.vht


def fill_tree(st, v):
    """(Re)build the hierarchy rows. Collapse state is kept; a fresh vehicle opens the root and the chassis only."""
    if st.fragment != v.frag.name or not st.tree_open:
        st.tree_open = "\n".join(["(root)"] + [b.name for b in v.frag.data.bones if b.parent is None])
    st.tree.clear()
    for r in analysis.hierarchy_rows(v):
        it = st.tree.add()
        for k, val in r.items():
            setattr(it, k, val)
    st.fragment = v.frag.name


def tree_objects(v, bone_name, subtree=True):
    """Objects bound to a node (geometry + collisions), and to everything under it when `subtree`."""
    arm = v.frag.data
    bone = arm.bones.get(bone_name)
    if bone is None:
        return []
    keep = {bone_name} | ({b.name for b in bone.children_recursive} if subtree else set())
    names = set(arm.bones.keys())
    return [o for o in v.models + v.bounds if keep & set(analysis.bone_links(o, names))]


def select_node(context, frag_name, row):
    """Click on a hierarchy row: select the part (and everything under it) or one collision."""
    frag = bpy.data.objects.get(frag_name)
    if frag is None:
        return
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.selected_objects:
        o.select_set(False)
    v = analysis.load(frag)
    if row.kind == "root":
        picks = [frag]
    elif row.kind == "col":
        picks = [bpy.data.objects.get(row.objects)]
    else:
        bone = frag.data.bones.get(row.bone)
        picks = tree_objects(v, row.bone, subtree=False)  # this part's own objects only, not those of the parts under it
        if bone is not None:
            frag.data.bones.active = bone
            for pb in frag.pose.bones:  # only this bone is selected
                pb.select = pb.name == row.bone
            if not picks:  # a part with no geometry: select the bone itself (Pose mode shows just that one)
                for o in context.view_layer.objects:
                    o.select_set(False)
                context.view_layer.objects.active = frag
                frag.select_set(True)
                bpy.ops.object.mode_set(mode="POSE")
                return
    picks = [p for p in picks if p is not None]
    for p in picks:
        if not p.hide_get():
            p.select_set(True)
    sel = [p for p in picks if p.select_get()]
    context.view_layer.objects.active = sel[0] if sel else frag
    state(context).seen_bone = bone_token(frag)


def on_tree_index(context):
    st = state(context)
    if 0 <= st.tree_index < len(st.tree) and st.fragment:
        select_node(context, st.fragment, st.tree[st.tree_index])


class VHT_OT_inspect(bpy.types.Operator):
    bl_idname = "vht.inspect"
    bl_label = "Inspect Vehicle"
    bl_description = "Read-only. Show the bone hierarchy with the objects bound to each bone"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        fill_tree(st, v)
        st.order.clear()
        rep = analysis.order_report(v)
        for i, name, depth, parent in rep["bones"]:
            st.order.add().section, st.order[-1].text = "Bones (index = export order)", f"{i:>3}  {'   ' * depth}{name}"
        for i, (name, kind, key) in enumerate(rep["models"]):
            st.order.add().section, st.order[-1].text = "Models (as Sollumz processes them)", f"{i:>3}  {name}  [{kind}, key {key}]"
        for i, name in enumerate(rep["groups"]):
            st.order.add().section, st.order[-1].text = "Physics groups (bone index order)", f"{i:>3}  {name}"
        for i, name in enumerate(rep["materials"]):
            st.order.add().section, st.order[-1].text = "Shaders (export order)", f"{i:>3}  {name}"
        st.fragment = v.frag.name
        self.report({"INFO"}, f"{len(st.tree)} bones")
        return {"FINISHED"}


class VHT_OT_validate(bpy.types.Operator):
    bl_idname = "vht.validate"
    bl_label = "Check Vehicle"
    bl_description = "Read-only. Check structure, bone names and tags, material order and textures"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        st.findings.clear()
        found = analysis.validate(v, st.profile)
        found.sort(key=lambda f: analysis.SEVERITIES.index(f.severity))
        for f in found:
            it = st.findings.add()
            it.severity, it.code, it.message, it.target, it.kind = f.severity, f.code, f.message, f.target, f.kind
            it.fix = json.dumps(f.fix) if f.fix else ""
        st.fragment = v.frag.name
        counts = {s: sum(1 for f in found if f.severity == s) for s in analysis.SEVERITIES}
        self.report({"INFO"}, " | ".join(f"{k}: {n}" for k, n in counts.items()))
        return {"FINISHED"}


class VHT_OT_suggest(bpy.types.Operator):
    bl_idname = "vht.suggest"
    bl_label = "Preview All Quick Fixes"
    bl_description = "Dry run. Validate, then list the safe fixes with what each would change. Nothing is modified"

    def execute(self, context):
        bpy.ops.vht.validate()
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        planned = fixes.dedupe([json.loads(f.fix) for f in st.findings if f.fix])
        fill_plan(st, v, planned)
        manual = sum(1 for f in st.findings if f.severity in ("ERROR", "WARNING", "REVIEW") and not f.fix)
        self.report({"INFO"}, f"{len(st.plan)} fixes proposed; {manual} findings need manual work")
        return {"FINISHED"}


class VHT_OT_fix_finding(bpy.types.Operator):
    bl_idname = "vht.fix_finding"
    bl_label = "Preview This Fix"
    bl_description = "Show what the quick fix for the selected problem would change. Nothing changes until you press Apply Changes"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        if not 0 <= st.findings_index < len(st.findings) or not st.findings[st.findings_index].fix:
            self.report({"ERROR"}, "The selected problem has no quick fix. Follow the steps under How to fix.")
            return {"CANCELLED"}
        fill_plan(st, v, fixes.dedupe([json.loads(st.findings[st.findings_index].fix)]))
        st.arrange_notes = ""
        if not st.plan:
            self.report({"INFO"}, "Nothing to change.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Fix previewed: check it, then press Apply Changes.")
        return {"FINISHED"}


class VHT_OT_rename_part(bpy.types.Operator):
    bl_idname = "vht.rename_part"
    bl_label = "Preview Rename"
    bl_description = ("Rename parts as one thing: the bone, the models and collisions named after it, their mesh data and vertex groups. "
                      "With Find text every occurrence in the part names is replaced; without it the part gets the Replace text as its name. "
                      "Shows the change first; nothing changes until Apply Changes")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        if not st.rename_replace and not st.rename_find:
            self.report({"ERROR"}, "Type the new name (or Find and Replace with).")
            return {"CANCELLED"}
        if st.rename_scope == "ACTIVE":
            if not st.rename_find and not st.rename_replace:
                return {"CANCELLED"}
            if not st.tree or st.fragment != v.frag.name:
                bpy.ops.vht.inspect()  # the part comes from the hierarchy list
            bone = active_node_bone(self, context, v, follow_selection=True)
            if bone is None:
                return {"CANCELLED"}
            bones = [bone]
        elif st.rename_scope == "SELECTED":
            bones = sz.selected_bones(v.frag) if context.mode == "POSE" else []
            if not bones:
                self.report({"ERROR"}, "Select the bones in Pose mode first.")
                return {"CANCELLED"}
        else:
            if not st.rename_find:
                self.report({"ERROR"}, "For the whole vehicle, give the Find text.")
                return {"CANCELLED"}
            bones = [b.name for b in v.frag.data.bones if st.rename_find in b.name]
        planned, notes = fixes.rename_plan(v, bones, st.rename_find, st.rename_replace)
        fill_plan(st, v, planned)
        st.arrange_notes = "\n".join(notes)
        if not planned:
            self.report({"WARNING"}, "Nothing to rename" + (": " + notes[0] if notes else "."))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(planned)} part(s) to rename; check the preview, then Apply Changes")
        return {"FINISHED"}


class VHT_OT_arrange(bpy.types.Operator):
    bl_idname = "vht.arrange"
    bl_label = "Auto Arrange"
    bl_description = ("Dry run. List the moves that put bones under their usual parents and models and collisions on the bones "
                      "they are named after, as vanilla vehicles have them. Sibling order is left alone. Nothing is modified")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        planned, notes = arrange.plan(v, st.profile)
        fill_plan(st, v, planned)
        st.arrange_notes = "\n".join(notes)
        self.report({"INFO"}, f"{len(st.plan)} moves proposed; {len(notes)} things have no known place")
        return {"FINISHED"}


def fill_plan(st, v, planned):
    st.plan.clear()
    for fx in planned:
        text, kind, destructive = fixes.describe(v, fx)
        if text.endswith("no change"):
            continue
        it = st.plan.add()
        it.text, it.kind, it.fix, it.enabled, it.destructive = text, kind, json.dumps(fx), not destructive, destructive


class VHT_OT_apply(bpy.types.Operator):
    bl_idname = "vht.apply"
    bl_label = "Apply Changes"
    bl_description = "Apply the checked changes from the preview. Undo with Ctrl+Z"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(p.enabled for p in context.window_manager.vht.plan)

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        chosen = [json.loads(p.fix) for p in st.plan if p.enabled]
        try:
            lines = fixes.apply(context, v, chosen)
        except Exception as e:  # report instead of leaving a half-applied state unexplained
            self.report({"ERROR"}, f"Apply failed: {e}. Use Ctrl+Z to revert any partial change.")
            return {"CANCELLED"}
        st.report = "\n".join(lines)
        st.plan.clear()
        st.arrange_notes = ""
        bpy.ops.vht.validate()
        if st.tree:
            bpy.ops.vht.inspect()
        self.report({"INFO"}, f"Applied {len(chosen)} changes")
        return {"FINISHED"}


class VHT_OT_clear(bpy.types.Operator):
    bl_idname = "vht.clear"
    bl_label = "Clear"
    bl_description = "Clear results and the change preview"

    def execute(self, context):
        st = state(context)
        st.plan.clear()
        st.findings.clear()
        st.tree.clear()
        st.order.clear()
        st.report = ""
        st.arrange_notes = ""
        st.size_report = ""
        return {"FINISHED"}


class VHT_OT_select(bpy.types.Operator):
    bl_idname = "vht.select"
    bl_label = "Select"
    bl_description = "Select the object, bone or material users"
    bl_options = {"REGISTER", "UNDO"}

    target: StringProperty()
    kind: EnumProperty(items=[("object", "", ""), ("bone", "", ""), ("material", "", ""), ("part", "", "")])

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        frag = bpy.data.objects.get(state(context).fragment)
        for o in context.selected_objects:
            o.select_set(False)
        picks = []
        if self.kind == "object":
            picks = [bpy.data.objects.get(self.target)]
        elif self.kind == "bone" and frag is not None:
            bone = frag.data.bones.get(self.target)
            if bone is not None:
                frag.data.bones.active = bone
            picks = [frag]
        elif self.kind == "part" and frag is not None:
            bone = frag.data.bones.get(self.target)
            if bone is not None:
                frag.data.bones.active = bone
                v = analysis.load(frag)
                tree = {bone.name} | {b.name for b in bone.children_recursive}
                names = {b.name for b in frag.data.bones}
                picks = [o for o in v.models + v.bounds if tree & set(analysis.bone_links(o, names))]
        elif self.kind == "material" and frag is not None:
            mat = bpy.data.materials.get(self.target)
            v = analysis.load(frag)
            picks = [m for m in v.models if any(mat in me.materials[:] for _, me in sz.lod_meshes(m))]
        picks = [p for p in picks if p is not None]
        for p in picks:
            p.hide_set(False)
            p.select_set(True)
        if picks:
            context.view_layer.objects.active = picks[0]
        return {"FINISHED"}


# --- coupling (several parts under one node) ---------------------

class VHT_OT_couple_objects(bpy.types.Operator):
    bl_idname = "vht.couple_objects"
    bl_label = "Couple Selected Objects to Part"
    bl_description = ("Preview binding every selected Drawable Model / collision of the fragment to the chosen bone, "
                      "using Sollumz's own bone constraint. Nothing changes until Apply Changes")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        if st.couple_bone not in v.frag.data.bones:
            self.report({"ERROR"}, "Choose the target bone first.")
            return {"CANCELLED"}
        ours = {o.name for o in v.models + v.bounds}
        names = [o.name for o in context.selected_objects if o.name in ours]
        if not names:
            self.report({"ERROR"}, "Select Drawable Models or collisions of this fragment.")
            return {"CANCELLED"}
        st.fragment = v.frag.name
        fill_plan(st, v, [{"op": "bind_objects", "bone": st.couple_bone, "objects": sorted(names)}])
        return {"FINISHED"}


class VHT_OT_couple_bones(bpy.types.Operator):
    bl_idname = "vht.couple_bones"
    bl_label = "Couple Selected Bones under Active"
    bl_description = ("Preview parenting every selected bone to the active bone (rest pose, tags and bound objects "
                      "unchanged; bone indices shift). Select bones in Pose mode, active last")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        arm = v.frag.data
        parent = arm.bones.active
        if parent is None:
            self.report({"ERROR"}, "Make the intended parent the active bone.")
            return {"CANCELLED"}
        anc = set()
        p = parent
        while p is not None:
            anc.add(p.name)
            p = p.parent
        picks = [n for n in sz.selected_bones(v.frag) if n != parent.name and arm.bones[n].parent != parent and n not in anc]
        if not picks:
            self.report({"INFO"}, "No other selected bone needs a new parent.")
            return {"CANCELLED"}
        st = state(context)
        st.fragment = v.frag.name
        fill_plan(st, v, [{"op": "reparent_bone", "bone": n, "parent": parent.name} for n in picks])
        return {"FINISHED"}


class VHT_OT_move_bone(bpy.types.Operator):
    bl_idname = "vht.move_bone"
    bl_label = "Move Bone"
    bl_description = ("Preview moving the active bone one place among its siblings. Bone index is the depth-first position "
                      "in sibling order. Nothing changes until Apply Changes")
    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        bone = v.frag.data.bones.active
        delta = -1 if self.direction == "UP" else 1
        if bone is None or boneorder.plan_move(v.frag, bone.name, delta) is None:
            self.report({"INFO"}, "The active bone cannot move that way among its siblings.")
            return {"CANCELLED"}
        state(context).fragment = v.frag.name
        fill_plan(state(context), v, [{"op": "move_bone", "bone": bone.name, "delta": delta}])
        return {"FINISHED"}


# --- hierarchy view -------------------------------

LOD_LEVELS = ("sollumz_veryhigh", "sollumz_high", "sollumz_medium", "sollumz_low", "sollumz_verylow")  # L0..L4


def active_row(st):
    return st.tree[st.tree_index] if 0 <= st.tree_index < len(st.tree) else None


def bone_token(frag):
    """Identifies what the user has selected outside the hierarchy list: the active bone and the active object."""
    obj = bpy.context.view_layer.objects.active
    return f"{viewport_bones(frag)}|{obj.name if obj else ''}"


def viewport_bones(frag):
    """The bones selected in the viewport, with the active one first: 'active+other+other'. Works in Pose and Edit mode, where Blender keeps
    the selection in different places."""
    arm = frag.data
    if arm.is_editmode:
        sel = [e.name for e in arm.edit_bones if e.select or e.select_head or e.select_tail]
        act = arm.edit_bones.active.name if arm.edit_bones.active else ""
    else:
        sel = sz.selected_bones(frag)
        act = arm.bones.active.name if arm.bones.active else ""
    return "+".join(([act] if act else []) + [n for n in sel if n != act])


def selected_part(v):
    """The bone the user picked in the viewport or Outliner: the one the active model or collision is bound to, else the active bone."""
    obj = bpy.context.view_layer.objects.active
    if obj is not None and obj is not v.frag:
        links = analysis.bone_links(obj, set(v.frag.data.bones.keys()))  # the bone constraint, else the vertex groups named after bones
        if len(links) == 1:
            return links[0]
    picked = viewport_bones(v.frag).split("+")
    return picked[0] if picked and picked[0] else None


def active_node_bone(op, context, v, follow_selection=False):
    """The part the tools act on: the hierarchy row, unless the selection changed elsewhere (viewport, Outliner) since the last click on a row,
    in which case that part becomes the row. Only the tools that act on the part itself ask for this; attach and adopt use the selection as
    their input, so for them the row is the target."""
    st = state(context)
    token = bone_token(v.frag)
    if follow_selection and token != st.seen_bone:
        st.seen_bone = token
        picked = selected_part(v)
        if picked in v.frag.data.bones:
            for i, r in enumerate(st.tree):
                if r.kind == "node" and r.bone == picked:
                    st.seen_bone = token
                    st.tree_index = i  # fires select_node, which resets the token: set it again after
                    st.seen_bone = bone_token(v.frag)
                    break
    row = active_row(st)
    if row is None or row.kind == "root" or row.bone not in v.frag.data.bones:
        op.report({"ERROR"}, "Click a part in the hierarchy first.")
        return None
    return row.bone


def reselect_row(st, bone_name):
    for i, r in enumerate(st.tree):
        if r.kind == "node" and r.bone == bone_name:
            st.tree_index = i
            return


class VHT_OT_tree_toggle(bpy.types.Operator):
    bl_idname = "vht.tree_toggle"
    bl_label = "Expand / Collapse"
    bl_description = "Open or close this node"
    key: StringProperty()

    def execute(self, context):
        st = state(context)
        keys = [k for k in st.tree_open.split("\n") if k]
        if self.key in keys:
            keys.remove(self.key)
        else:
            keys.append(self.key)
        st.tree_open = "\n".join(keys)
        # The list keeps its active row in view when rows appear or vanish; making the clicked row the active one keeps the list in place.
        at = next((i for i, r in enumerate(st.tree) if r.key == self.key), None)
        if at is not None and st.tree_index != at:
            st.tree_index = at
        return {"FINISHED"}


class VHT_OT_tree_expand(bpy.types.Operator):
    bl_idname = "vht.tree_expand"
    bl_label = "Expand / Collapse All"
    bl_description = "Open every node, or close all but the root and chassis"
    mode: EnumProperty(items=[("ALL", "Expand", ""), ("NONE", "Collapse", "")])

    def execute(self, context):
        st = state(context)
        if self.mode == "ALL":
            st.tree_open = "\n".join(r.key for r in st.tree if r.has_children)
        else:
            st.tree_open = "\n".join(["(root)"] + [r.key for r in st.tree if r.kind == "node" and r.depth == 1])
        return {"FINISHED"}


class VHT_OT_tree_visible(bpy.types.Operator):
    bl_idname = "vht.tree_visible"
    bl_label = "Show / Hide Node"
    bl_description = "Hide or show this part and everything under it in the viewport. Does not change the export"
    key: StringProperty()
    bone: StringProperty()

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        if self.key.count("|"):
            objs = [bpy.data.objects[self.key.split("|", 1)[1]]]
        else:
            objs = tree_objects(v, self.bone)
        hide = any(not o.hide_get() for o in objs)
        for o in objs:
            o.hide_set(hide)
        return {"FINISHED"}


class VHT_OT_tree_show(bpy.types.Operator):
    bl_idname = "vht.tree_show"
    bl_label = "Visibility"
    bl_description = "Show all, hide all, or isolate the selected part and what is under it. Does not change the export"
    mode: EnumProperty(items=[("SHOW", "Show All", ""), ("HIDE", "Hide All", ""), ("ISOLATE", "Isolated", "")])

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        everything = v.models + v.bounds
        if self.mode == "ISOLATE":
            bone = active_node_bone(self, context, v)
            if bone is None:
                return {"CANCELLED"}
            keep = set(o.name for o in tree_objects(v, bone))
            for o in everything:
                o.hide_set(o.name not in keep)
        else:
            for o in everything:
                o.hide_set(self.mode == "HIDE")
        return {"FINISHED"}


class VHT_OT_tree_lod(bpy.types.Operator):
    bl_idname = "vht.tree_lod"
    bl_label = "Show LOD"
    bl_description = ("Display one LOD slot (L0 very high ... L4 very low) on every part. "
                      "Uses Sollumz's active LOD level; the export is unchanged")
    level: bpy.props.IntProperty(min=0, max=4)

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        for m in v.models:
            if m.type == "MESH" and m.mode == "OBJECT":
                m.sz_lods.active_lod_level = LOD_LEVELS[self.level]
        return {"FINISHED"}


class VHT_OT_tree_col(bpy.types.Operator):
    bl_idname = "vht.tree_col"
    bl_label = "Show Collisions"
    bl_description = "Show or hide every collision . Uses Sollumz's own operators"

    def execute(self, context):
        if context.scene.sollumz_show_collisions:
            bpy.ops.sollumz.hide_collisions()
        else:
            bpy.ops.sollumz.show_collisions()
        return {"FINISHED"}


class VHT_OT_tree_move(bpy.types.Operator):
    bl_idname = "vht.tree_move"
    bl_label = "Move Node"
    bl_description = ("Move the active part up or down among its siblings; bone indices follow the new order. "
                      "Recreates the affected sibling bones and verifies every bone afterwards. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}
    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        bone = active_node_bone(self, context, v)
        if bone is None:
            return {"CANCELLED"}
        delta = -1 if self.direction == "UP" else 1
        if boneorder.plan_move(v.frag, bone, delta) is None:
            self.report({"INFO"}, f"'{bone}' cannot move {self.direction.lower()} among its siblings.")
            return {"CANCELLED"}
        lines, ok = boneorder.move(context, v.frag, bone, delta)
        st = state(context)
        fill_tree(st, analysis.load(v.frag))
        reselect_row(st, bone)
        self.report({"INFO" if ok else "WARNING"}, " ".join(lines))
        return {"FINISHED"}


class VHT_OT_tree_grab(bpy.types.Operator):
    bl_idname = "vht.tree_grab"
    bl_label = "Grab"
    bl_description = ("Pick up the active part (or a [COL] row) so it can be dropped into another part, placed before or after a "
                      "sibling, or unlinked. Blender cannot drag rows with the mouse from Python, so this is grab and drop")
    cancel: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        st = state(context)
        if self.cancel:
            st.tree_grab = ""
            return {"FINISHED"}
        row = active_row(st)
        if row is None or row.kind == "root":
            self.report({"ERROR"}, "Click a part or a [COL] row first.")
            return {"CANCELLED"}
        st.tree_grab = ("col:" + row.objects) if row.kind == "col" else ("node:" + row.bone)
        return {"FINISHED"}


class VHT_OT_tree_drop(bpy.types.Operator):
    bl_idname = "vht.tree_drop"
    bl_label = "Drop"
    bl_description = ("Drop the grabbed part relative to the active row: into it (as a child), before or after it (as a sibling), or "
                      "unlink it from its parent into its own top-level tree. With nothing grabbed, Unlink acts on the active part. "
                      "A skeleton needs one root, so re-attach before exporting. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}
    mode: EnumProperty(items=[("INTO", "Into", ""), ("BEFORE", "Before", ""), ("AFTER", "After", ""), ("UNLINK", "Unlink", "")])

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        grabbed = st.tree_grab
        target = active_row(st)
        arm = v.frag.data
        if self.mode == "UNLINK" and not grabbed:
            if target is None or target.kind != "node":
                self.report({"ERROR"}, "Click a part first.")
                return {"CANCELLED"}
            grabbed = "node:" + target.bone
        if not grabbed:
            self.report({"ERROR"}, "Grab a part first.")
            return {"CANCELLED"}
        kind, _, name = grabbed.partition(":")
        if self.mode != "UNLINK" and (target is None or target.kind == "col"):
            self.report({"ERROR"}, "Click the part to drop onto.")
            return {"CANCELLED"}
        if kind == "col":  # dropping a collision into a part binds it to that part's bone
            if self.mode != "INTO" or target.kind != "node":
                self.report({"ERROR"}, "A collision can only be dropped Into a part.")
                return {"CANCELLED"}
            obj = bpy.data.objects.get(name)
            if obj is None:
                st.tree_grab = ""
                return {"CANCELLED"}
            line = fixes.bind_objects(v.frag, target.bone, [obj])
            st.tree_grab = ""
            fill_tree(st, analysis.load(v.frag))
            self.report({"INFO"}, line)
            return {"FINISHED"}
        # a part
        if name not in arm.bones:
            st.tree_grab = ""
            self.report({"ERROR"}, f"'{name}' no longer exists.")
            return {"CANCELLED"}
        if self.mode == "UNLINK":
            new_parent = None
        elif self.mode == "INTO":
            new_parent = None if target.kind == "root" else target.bone
        else:
            if target.kind == "root" or target.bone == name:
                self.report({"ERROR"}, "Click a different part to place it before or after.")
                return {"CANCELLED"}
            tb = arm.bones[target.bone]
            new_parent = tb.parent.name if tb.parent else None
        lines, ok = [], True
        if (arm.bones[name].parent.name if arm.bones[name].parent else None) != new_parent:
            lines, ok = fixes.reparent_bone_to(context, v.frag, name, new_parent)
            if not ok and any(("cannot move" in l or "missing" in l) for l in lines):
                self.report({"ERROR"}, " ".join(lines))
                return {"CANCELLED"}
        if self.mode == "INTO":  # always the last child: Blender's own placement after a reparent is not predictable
            bone = arm.bones[name]
            sibs = [b.name for b in boneorder.siblings(bone, arm)]
            delta = len(sibs) - 1 - sibs.index(name)
            if delta:
                more, ok2 = boneorder.move(context, v.frag, name, delta)
                lines += more
                ok = ok and ok2
        if self.mode in ("BEFORE", "AFTER"):
            bone = arm.bones[name]
            sibs = [b.name for b in boneorder.siblings(bone, arm)]
            i = sibs.index(name)
            rest = [n for n in sibs if n != name]
            final = rest.index(target.bone) + (1 if self.mode == "AFTER" else 0)  # position once the bone is lifted out
            delta = final - i
            if delta:
                more, ok2 = boneorder.move(context, v.frag, name, delta)
                lines += more
                ok = ok and ok2
        st.tree_grab = ""
        fill_tree(st, analysis.load(v.frag))
        reselect_row(st, name)
        self.report({"INFO" if ok else "WARNING"}, " ".join(lines))
        return {"FINISHED"}


class VHT_OT_tree_axes(bpy.types.Operator):
    def each(self, context, v, bones):
        """The same tool on every selected bone separately: its own target, its own check, its own line in the report."""
        from . import axes
        st = state(context)
        if self.mode == "COPY":
            self.report({"ERROR"}, "Copy From Grabbed takes one part: select a single bone.")
            return {"CANCELLED"}
        lines, bad = [], 0
        for name in bones:
            out, ok = axes.set_axes(context, v.frag, name, self.mode, None, [], st.axes_rotation, st.axes_position)
            lines.append(" ".join(out))
            bad += 0 if ok else 1
        fill_tree(st, analysis.load(v.frag))
        st.report = chr(10).join(lines)
        self.report({"INFO" if not bad else "WARNING"}, f"{len(bones)} bones, each on its own; {bad} with a problem" if bad
                    else f"{len(bones)} bones, each on its own")
        return {"FINISHED"}

    bl_idname = "vht.tree_axes"
    bl_label = "Local Axes"
    bl_description = ("Change the active part's local axes without moving anything: Center to Object (origin to the geometry), "
                      "Reset to Parent, Reset to World, or Copy From Grabbed. A rotor spins on its local Z, so tilted or "
                      "off-centre axes make the wrong thing turn. Children, geometry and collisions stay in place. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}
    mode: EnumProperty(items=[("CENTER", "Center to Object", ""), ("PARENT", "Reset to Parent", ""),
                              ("WORLD", "Reset to World", ""), ("COPY", "Copy From Grabbed", ""),
                              ("CURSOR", "Origin to 3D Cursor", ""), ("ALIGN", "Align Spin Axis to Geometry", "")])
    def execute(self, context):
        from . import axes
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        picked = sz.selected_bones(v.frag) if context.mode == "POSE" else []
        if len(picked) > 1:  # several bones selected in Pose mode: each one on its own, parents first
            order = {b.name: i for i, b in enumerate(v.frag.data.bones)}
            return self.each(context, v, sorted(picked, key=order.get))
        bone = active_node_bone(self, context, v, follow_selection=True)
        if bone is None:
            return {"CANCELLED"}
        st = state(context)
        source = None
        if self.mode == "COPY":
            kind, _, name = st.tree_grab.partition(":")
            if kind != "node":
                self.report({"ERROR"}, "Grab the part to copy the axes from, then click the part that receives them.")
                return {"CANCELLED"}
            source = name
        extra = [o for o in context.selected_objects if o.type == "MESH"]
        lines, ok = axes.set_axes(context, v.frag, bone, self.mode, source, extra, st.axes_rotation, st.axes_position)
        if self.mode == "COPY":
            st.tree_grab = ""
        fill_tree(st, analysis.load(v.frag))
        reselect_row(st, bone)
        if lines and not any(l.startswith(bone + ": axes set") for l in lines):
            self.report({"ERROR"}, " ".join(lines))
            return {"CANCELLED"}
        self.report({"INFO" if ok else "WARNING"}, " ".join(lines))
        return {"FINISHED"}


class VHT_OT_tree_attach(bpy.types.Operator):
    bl_idname = "vht.tree_attach"
    bl_label = "Attach Selected Here"
    bl_description = ("Bind the selected objects (geometry, collisions) to the active part, by dropping them "
                      "into it. World positions are kept. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        bone = active_node_bone(self, context, v)
        if bone is None:
            return {"CANCELLED"}
        ours = {o.name for o in v.models + v.bounds}
        objs = [o for o in context.selected_objects if o.name in ours]
        if not objs:
            self.report({"ERROR"}, "Select Drawable Models or collisions of this fragment first (the click on the part selects its own objects).")
            return {"CANCELLED"}
        line = fixes.bind_objects(v.frag, bone, objs)
        fill_tree(state(context), analysis.load(v.frag))
        self.report({"INFO"}, line)
        return {"FINISHED"}


class VHT_OT_tree_adopt(bpy.types.Operator):
    bl_idname = "vht.tree_adopt"
    bl_label = "Move Selected Bones Here"
    bl_description = ("Parent the bones selected in Pose mode under the active part (relink), keeping rest pose and tags. "
                      "Bone indices shift. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        parent = active_node_bone(self, context, v)
        if parent is None:
            return {"CANCELLED"}
        arm = v.frag.data
        anc, p = set(), arm.bones[parent]
        while p is not None:
            anc.add(p.name)
            p = p.parent
        picks = [n for n in sz.selected_bones(v.frag) if n not in anc and arm.bones[n].parent != arm.bones[parent]]
        if not picks:
            self.report({"INFO"}, "Select other bones in Pose mode first (ancestors of the target are skipped).")
            return {"CANCELLED"}
        lines = fixes.apply(context, v, [{"op": "reparent_bone", "bone": n, "parent": parent} for n in picks])
        st = state(context)
        fill_tree(st, analysis.load(v.frag))
        self.report({"INFO"}, " ".join(lines))
        return {"FINISHED"}


# --- vehicle materials: paint layers and liveries ---------------------------

def fill_paint(st, v):
    from . import paint
    st.paint.clear()
    for mat, polys, bones in paint.vehicle_paint_materials(v):
        it = st.paint.add()
        it.name, it.shader = mat.name, mat.shader_properties.name
        it.layer, it.polys, it.parts = paint.layer_of(mat), polys, ", ".join(bones[:3])


def on_paint_index(context):
    """Clicking a row makes that material the active slot of the active model (if the model has it)."""
    st = state(context)
    obj = context.active_object
    if obj is None or obj.type != "MESH" or not (0 <= st.paint_index < len(st.paint)):
        return
    name = st.paint[st.paint_index].name
    for i, m in enumerate(obj.data.materials):
        if m is not None and m.name == name:
            obj.active_material_index = i
            return


def active_paint_base(op, context):
    from . import paint
    obj = context.active_object
    mat = obj.active_material if obj is not None and obj.type == "MESH" else None
    if mat is None or not paint.is_paint_material(mat):
        op.report({"ERROR"}, "Make a vehicle paint material the active slot of the active model first "
                             "(click a row in the list, or pick the slot in the Material tab).")
        return None
    return mat


class VHT_OT_paint_refresh(bpy.types.Operator):
    bl_idname = "vht.paint_refresh"
    bl_label = "Refresh Paint Materials"
    bl_description = "Read-only. List the paint materials the exported models use, with their paint layer and where they are used"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        fill_paint(state(context), v)
        self.report({"INFO"}, f"{len(state(context).paint)} paint materials")
        return {"FINISHED"}


class VHT_OT_paint_assign(bpy.types.Operator):
    bl_idname = "vht.paint_assign"
    bl_label = "Assign Paint Layer"
    bl_description = ("Paint the selection with a paint layer. Edit mode: the selected faces. Object mode: the active material "
                      "slot of the selected models. The material is copied from the active one (same shader and textures) with "
                      "the layer set, or reused if that variant already exists. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}
    layer: EnumProperty(items=[(n, n.replace("_", " ").title(), "") for n in ("PRIMARY", "SECONDARY", "PEARLESCENT", "WHEEL",
                                                                             "INTERIOR_TRIM", "INTERIOR_DASH", "CUSTOM", "DEFAULT")])

    def execute(self, context):
        from . import paint
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        base = active_paint_base(self, context)
        if base is None:
            return {"CANCELLED"}
        if context.mode == "EDIT_MESH" and not paint.selected_face_count(context):
            self.report({"ERROR"}, "Select some faces first.")
            return {"CANCELLED"}
        new, created = paint.make_variant(v, base, self.layer)
        line = paint.assign(context, v, base, new)
        fill_paint(state(context), analysis.load(v.frag))
        self.report({"INFO"}, f"{'Created' if created else 'Reused'} {new.name}. {line}")
        return {"FINISHED"}


class VHT_OT_paint_add(bpy.types.Operator):
    bl_idname = "vht.paint_add"
    bl_label = "Add Paint Material"
    bl_description = ("Create a new vehicle paint material with the chosen shader and paint layer and put it on the selection "
                      "(Edit mode: selected faces; Object mode: the active material slot of the selected models). "
                      "Textures start with the names vanilla vehicles use. A model with no material gets it as its first one")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import paint
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        obj = context.active_object
        old = obj.active_material if obj is not None and obj.type == "MESH" else None
        mat = sz.create_shader_material(st.paint_shader)
        sz._mod("ydr.operators.materials").post_create_shader_add_default_images(mat)
        textures.apply_defaults(mat)
        mat.sz_paint_layer = st.paint_layer
        mat.shader_properties.index = paint.next_shader_index(v)
        if context.mode == "EDIT_MESH" or old is not None:
            line = paint.assign(context, v, old, mat)
        else:  # models with no material yet: the new one becomes their first slot, so every polygon uses it
            line = paint.give_first_material(v, context, mat)
        fill_paint(st, analysis.load(v.frag))
        self.report({"INFO"}, f"Created {mat.name}. {line}")
        return {"FINISHED"}


class VHT_OT_shader_add(bpy.types.Operator):
    bl_idname = "vht.shader_add"
    bl_label = "Create Material"
    bl_description = ("Create a new material with the chosen vehicle shader and put it on the selection (Edit mode: selected faces; Object "
                      "mode: the active material slot of the selected models). The shared textures vanilla vehicles use for that shader "
                      "are attached; a sampler meant for the vehicle's own texture stays empty. A model with no material gets it as its first one")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import paint
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        if not st.vehicle_shader:
            self.report({"ERROR"}, "Pick a shader first.")
            return {"CANCELLED"}
        obj = context.active_object
        old = obj.active_material if obj is not None and obj.type == "MESH" else None
        mat = sz.create_shader_material(st.vehicle_shader)
        sz._mod("ydr.operators.materials").post_create_shader_add_default_images(mat)
        done = textures.apply_defaults(mat)
        if paint.is_paint_material(mat):
            mat.sz_paint_layer = st.paint_layer
        mat.shader_properties.index = paint.next_shader_index(v)
        if context.mode == "EDIT_MESH" or old is not None:
            line = paint.assign(context, v, old, mat)
        else:
            line = paint.give_first_material(v, context, mat)
        fill_paint(st, analysis.load(v.frag))
        self.report({"INFO"}, f"Created {mat.name} with {len(done)} texture(s). {line}")
        return {"FINISHED"}


class VHT_OT_paint_livery(bpy.types.Operator):
    bl_idname = "vht.paint_livery"
    bl_label = "Make Livery Material"
    bl_description = ("Copy the active paint material onto the livery shader (vehicle_paint3_lvr: a second diffuse for the livery on "
                      "UV map 2), keeping its textures and paint layer, and put it on the selection like Assign Paint Layer does. "
                      "Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import paint
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        base = active_paint_base(self, context)
        if base is None:
            return {"CANCELLED"}
        if context.mode == "EDIT_MESH" and not paint.selected_face_count(context):
            self.report({"ERROR"}, "Select some faces first.")
            return {"CANCELLED"}
        new, _ = paint.make_variant(v, base, paint.layer_of(base), shader=paint.LIVERY_SHADER)
        line = paint.assign(context, v, base, new)
        fill_paint(state(context), analysis.load(v.frag))
        self.report({"INFO"}, f"Created {new.name}. {line}")
        return {"FINISHED"}


class VHT_OT_mat_transfer(bpy.types.Operator):
    bl_idname = "vht.mat_transfer"
    bl_label = "Transfer Materials"
    bl_description = ("Copy GTA V materials from the active model (the source) to the other selected models. The targets share the very same "
                      "materials, so the shader group gets no duplicates. Done on every LOD mesh. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}
    mode: EnumProperty(items=[("ALL", "All Slots", "Give the targets the source's material slots, in the same order"),
                              ("ACTIVE", "Active Material", "Put the source's active material in the targets' active slot")])

    def execute(self, context):
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Go to Object mode first.")
            return {"CANCELLED"}
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        src = context.active_object
        if src is None or src.type != "MESH" or not any(sz.is_shader_material(m) for m in src.data.materials):
            self.report({"ERROR"}, "Make the model that has the materials the active one (select it last).")
            return {"CANCELLED"}
        targets = [o for o in context.selected_objects if o is not src and o.type == "MESH"]
        if not targets:
            self.report({"ERROR"}, "Select the models that should receive the materials, then the source last.")
            return {"CANCELLED"}
        src_mats = list(src.data.materials)
        active = src.active_material
        for o in targets:
            meshes = [me for _, me in sz.lod_meshes(o)] or [o.data]
            slot = o.active_material_index
            for me in dict.fromkeys(meshes):
                if self.mode == "ALL":
                    me.materials.clear()
                    for m in src_mats:
                        me.materials.append(m)
                    last = len(src_mats) - 1
                    for p in me.polygons:
                        if p.material_index > last:
                            p.material_index = last
                elif len(me.materials):
                    me.materials[min(slot, len(me.materials) - 1)] = active
                else:
                    me.materials.append(active)
            for m in (src_mats if self.mode == "ALL" else [active]):
                if sz.is_shader_material(m):
                    sz.prepare_mesh_for_material(o, m)
        self.report({"INFO"}, f"{len(targets)} model(s) now use the materials of {src.name}")
        return {"FINISHED"}


def fill_usage(st, v):
    from . import usage
    st.usage.clear()
    for r in usage.rows(v):
        it = st.usage.add()
        it.name, it.shader, it.polys, it.objects, it.lods = r["material"].name, r["material"].shader_properties.name, r["polys"], len(r["objects"]), r["lods"]
    st.usage_report = chr(10).join(usage.texture_report(v))


class VHT_OT_usage_refresh(bpy.types.Operator):
    bl_idname = "vht.usage_refresh"
    bl_label = "Refresh Usage"
    bl_description = "List the materials the exported models use, with polygon counts, LODs and the texture problems found"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        fill_usage(state(context), v)
        self.report({"INFO"}, f"{len(state(context).usage)} materials")
        return {"FINISHED"}


def usage_material(op, context):
    st = state(context)
    if not 0 <= st.usage_index < len(st.usage):
        op.report({"ERROR"}, "Refresh the list and click a material first.")
        return None
    mat = bpy.data.materials.get(st.usage[st.usage_index].name)
    if mat is None:
        op.report({"ERROR"}, "That material no longer exists: refresh the list.")
    return mat


class VHT_OT_usage_select(bpy.types.Operator):
    bl_idname = "vht.usage_select"
    bl_label = "Select Users"
    bl_description = ("Object mode: select the models that use the chosen material. Edit mode: select the faces of the active model that use it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import usage
        v = get_vehicle(self, context)
        mat = usage_material(self, context) if v is not None else None
        if mat is None:
            return {"CANCELLED"}
        self.report({"INFO"}, usage.select_users(context, v, mat))
        return {"FINISHED"}


class VHT_OT_usage_replace(bpy.types.Operator):
    bl_idname = "vht.usage_replace"
    bl_label = "Replace Everywhere"
    bl_description = ("Every slot that holds the chosen material, on every exported model and LOD mesh, takes the material picked under "
                      "'Replace with'. Polygon assignments do not change. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import usage
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Go to Object mode first.")
            return {"CANCELLED"}
        v = get_vehicle(self, context)
        old = usage_material(self, context) if v is not None else None
        if old is None:
            return {"CANCELLED"}
        new = state(context).usage_target
        if new is None or new is old:
            self.report({"ERROR"}, "Pick a different material under 'Replace with'.")
            return {"CANCELLED"}
        slots, models = usage.replace_everywhere(v, old, new)
        fill_usage(state(context), analysis.load(v.frag))
        self.report({"INFO"}, f"{slots} slot(s) on {models} model(s) now use {new.name}")
        return {"FINISHED"}


class VHT_OT_lods_generate(bpy.types.Operator):
    bl_idname = "vht.lods_generate"
    bl_label = "Generate LODs"
    bl_description = ("Fill the LOD slots of the parts below the chosen start level (L0 _hi or L1): attribute-aware reduction that keeps material borders, UVs and "
                      "shading, with extra detail kept on wheels, glass, lights and mirrors. Existing slots are left alone unless Replace existing is on; the start "
                      "meshes are never changed and no objects are made. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import lodgen
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Go to Object mode first.")
            return {"CANCELLED"}
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        st = state(context)
        models = v.models if st.lod_scope == "ALL" else [o for o in context.selected_objects if o in v.models]
        if not models:
            self.report({"ERROR"}, "Select some models of the vehicle, or choose Every part.")
            return {"CANCELLED"}
        ratios = {"high": st.lod_high, "medium": st.lod_medium, "low": st.lod_low, "very_low": st.lod_very_low}
        rep = lodgen.generate(models, st.lod_start, ratios, st.lod_make_hi, st.lod_overwrite, st.lod_method, st.lod_chain,
                              st.lod_protect, st.lod_shading, set(v.frag.data.bones.keys()))
        lines = []
        tri = rep["triangles"]
        lines.append("Triangles: " + ", ".join(f"L{i} {tri[s]}" for i, (s, _) in enumerate(lodgen.LEVELS) if tri[s]))
        if rep["methods"]:
            lines.append("Meshes made by: " + ", ".join(f"{k} {n}" for k, n in sorted(rep["methods"].items())))
        for name, why in rep["skipped"][:6]:
            lines.append(f"Skipped {name}: {why}")
        if len(rep["skipped"]) > 6:
            lines.append(f"... and {len(rep['skipped']) - 6} more skipped")
        st.report = chr(10).join(lines)
        n = sum(len(sl) for _, sl, _ in rep["done"])
        self.report({"INFO"}, f"{n} LOD mesh(es) on {len(rep['done'])} of {len(models)} models"
                    + ("" if rep["done"] else " (nothing to do: every slot has a mesh, or the start mesh is missing)"))
        return {"FINISHED"}


class VHT_OT_fill_textures(bpy.types.Operator):
    bl_idname = "vht.fill_textures"
    bl_label = "Fill Empty Textures"
    bl_description = ("Give every empty sampler of the vehicle's materials the texture name vanilla vehicles use for that shader and sampler "
                      "Samplers that hold a texture are untouched. blank and normal_flat_small are generated and "
                      "embedded in the yft. Ctrl+Z undoes it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        usage, _ = analysis.material_usage(v)
        lines = []
        for mat in usage:
            done = textures.apply_defaults(mat)
            if done:
                lines.append(f"{mat.name}: " + ", ".join(f"{s} -> {t}" for s, t in done))
        state(context).report = "\n".join(lines) or "Every sampler that has a default already holds a texture."
        self.report({"INFO"}, f"Filled {sum(l.count('->') for l in lines)} sampler(s) on {len(lines)} material(s)")
        return {"FINISHED"}


class VHT_OT_paint_livery_texture(bpy.types.Operator):
    bl_idname = "vht.paint_livery_texture"
    bl_label = "Set Livery Texture"
    bl_description = "Load an image into the livery slot (DiffuseSampler3) of the active livery material"
    bl_options = {"REGISTER", "UNDO"}
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.dds;*.png;*.tga;*.jpg;*.jpeg", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.active_object
        mat = obj.active_material if obj is not None and obj.type == "MESH" else None
        node = mat.node_tree.nodes.get("DiffuseSampler3") if mat is not None and mat.node_tree is not None else None
        if node is None:
            self.report({"ERROR"}, "The active material has no DiffuseSampler3: make it a livery material first.")
            return {"CANCELLED"}
        node.image = bpy.data.images.load(bpy.path.abspath(self.filepath), check_existing=True)
        self.report({"INFO"}, f"Livery texture set to {node.sollumz_texture_name}")
        return {"FINISHED"}


class VHT_OT_estimate_size(bpy.types.Operator):
    bl_idname = "vht.estimate_size"
    bl_label = "Estimate Export Size"
    bl_description = ("Run Sollumz's exporter into a temp folder and estimate the GPU-side size (vertex/index buffers and "
                      "embedded textures). Writes nothing outside the temp folder")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        try:
            m = sizing.estimate(context, v.frag)
        except Exception as e:  # exporter failures are reported, not raised through the UI
            self.report({"ERROR"}, f"Export for the estimate failed: {e}")
            return {"CANCELLED"}
        state(context).size_report = sizing.describe(m)
        self.report({"WARNING" if m["total"] >= sizing.LIMIT else "INFO"}, state(context).size_report.splitlines()[0])
        return {"FINISHED"}


class VHT_OT_export_compact(bpy.types.Operator):
    bl_idname = "vht.export_compact"
    bl_label = "Export Compact"
    bl_description = ("Export the vehicle with Sollumz's exporter and your Sollumz export settings, but merge vertices that differ only by float noise in their "
                      "normals. Same triangles, same look, fewer vertices and a smaller file")

    directory: bpy.props.StringProperty(name="Output directory", subtype="DIR_PATH", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        if not self.directory:
            self.report({"ERROR"}, "Choose an output folder.")
            return {"CANCELLED"}
        try:
            files, stock, compact = compactexport.export(context, v.frag, bpy.path.abspath(self.directory))
        except Exception as e:  # exporter failures are reported, not raised through the UI
            self.report({"ERROR"}, f"Export failed: {e}")
            return {"CANCELLED"}
        state(context).size_report = compactexport.describe(files, stock, compact)
        self.report({"INFO"}, state(context).size_report.splitlines()[0])
        return {"FINISHED"}


class VHT_OT_build_parts(bpy.types.Operator):
    bl_idname = "vht.build_parts"
    bl_label = "Build Part Collections"
    bl_description = ("Mirror the bone tree as nested collections in the Outliner, with each bound object in its part's "
                      "collection. Only collection membership changes: parents, constraints, transforms and export are untouched")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        created, moved = fixes.build_part_collections(v)
        self.report({"INFO"}, f"{created} collections created, {moved} objects moved")
        return {"FINISHED"}


class VHT_OT_remove_parts(bpy.types.Operator):
    bl_idname = "vht.remove_parts"
    bl_label = "Remove Part Collections"
    bl_description = "Put objects back in the collections they came from and delete the part collections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        frag = sz.find_fragment(context.active_object)
        if frag is None:
            self.report({"ERROR"}, "Select an object inside a Sollumz Fragment (or the fragment itself).")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{fixes.remove_part_collections(frag)} objects restored")
        return {"FINISHED"}


# --- material order --------------------------------------------------------

class VHT_OT_mat_load(bpy.types.Operator):
    bl_idname = "vht.mat_load"
    bl_label = "Load Export Order"
    bl_description = "Fill the list with the order Sollumz will export right now (base LODs, then _hi-only materials)"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        base, hi = analysis.export_order(v)
        frag = v.frag
        frag.vht_material_order.clear()
        for m in base + [m for m in hi if m not in base]:
            frag.vht_material_order.add().material = m
        frag.vht_material_order_index = 0
        return {"FINISHED"}


class VHT_OT_mat_autosort(bpy.types.Operator):
    bl_idname = "vht.mat_autosort"
    bl_label = "Sort Like Vanilla"
    bl_description = ("Put the shaders in the order vanilla vehicles have them (paint first, inner glass, shutters, lights, badges and mesh, plate, detail, dashboard, "
                      "outer glass, interior, cutout, tyres last; shaders it does not know stay in the middle, in their current order) and show it in the change preview. "
                      "Apply Changes writes it")

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        base, hi = analysis.export_order(v)
        current = base + [m for m in hi if m not in base]
        ordered = shaderorder.sorted_items([(m, m.shader_properties.name) for m in current])
        frag = v.frag
        frag.vht_material_order.clear()
        for m, _ in ordered:
            frag.vht_material_order.add().material = m
        frag.vht_material_order_index = 0
        st = state(context)
        st.fragment = frag.name
        fill_plan(st, v, [{"op": "set_material_order", "names": [m.name for m, _ in ordered]}])
        self.report({"INFO"}, "Sorted; check the preview, then Apply Changes" if st.plan else "Already in vanilla order")
        return {"FINISHED"}


class VHT_OT_mat_move(bpy.types.Operator):
    bl_idname = "vht.mat_move"
    bl_label = "Move Material"
    bl_options = {"REGISTER", "UNDO"}
    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", ""), ("TOP", "Top", ""), ("BOTTOM", "Bottom", "")])

    def execute(self, context):
        frag = sz.find_fragment(context.active_object)
        if frag is None or not frag.vht_material_order:
            return {"CANCELLED"}
        coll, i = frag.vht_material_order, frag.vht_material_order_index
        j = {"UP": i - 1, "DOWN": i + 1, "TOP": 0, "BOTTOM": len(coll) - 1}[self.direction]
        j = max(0, min(len(coll) - 1, j))
        coll.move(i, j)
        frag.vht_material_order_index = j
        return {"FINISHED"}


class VHT_OT_mat_preview(bpy.types.Operator):
    bl_idname = "vht.mat_preview"
    bl_label = "Preview Order"
    bl_description = "Put the listed order into the change preview. Apply Changes writes it to Sollumz shader indices"

    def execute(self, context):
        v = get_vehicle(self, context)
        if v is None:
            return {"CANCELLED"}
        names = [it.material.name for it in v.frag.vht_material_order if it.material]
        st = state(context)
        st.fragment = v.frag.name
        fill_plan(st, v, [{"op": "set_material_order", "names": names}])
        if not st.plan:
            self.report({"INFO"}, "Export order already matches the list")
        return {"FINISHED"}


classes = (VHT_OT_inspect, VHT_OT_validate, VHT_OT_suggest, VHT_OT_apply, VHT_OT_clear, VHT_OT_select,
           VHT_OT_fix_finding, VHT_OT_rename_part, VHT_OT_arrange, VHT_OT_couple_objects, VHT_OT_couple_bones, VHT_OT_build_parts, VHT_OT_remove_parts, VHT_OT_estimate_size, VHT_OT_export_compact, VHT_OT_move_bone,
           VHT_OT_tree_toggle, VHT_OT_tree_expand, VHT_OT_tree_visible, VHT_OT_tree_show, VHT_OT_tree_lod, VHT_OT_tree_col,
           VHT_OT_tree_move, VHT_OT_tree_grab, VHT_OT_tree_drop, VHT_OT_tree_axes, VHT_OT_tree_attach, VHT_OT_tree_adopt,
           VHT_OT_paint_refresh, VHT_OT_paint_assign, VHT_OT_paint_add, VHT_OT_shader_add, VHT_OT_paint_livery, VHT_OT_paint_livery_texture, VHT_OT_fill_textures, VHT_OT_lods_generate, VHT_OT_mat_transfer, VHT_OT_usage_refresh, VHT_OT_usage_select, VHT_OT_usage_replace,
           VHT_OT_mat_load, VHT_OT_mat_autosort, VHT_OT_mat_move, VHT_OT_mat_preview)
