"""The sidebar: one tab, CRCKTools. Top: status, Check Vehicle, the preview of any change, then Problems; below, collapsible panels for
the hierarchy, local axes, parts, materials (paint, livery, textures, order) and export info."""
import textwrap

import bpy

from . import explain, icons, paint, sollumz_bridge as sz, vehicleshaders

ICONS = {"ERROR": "CANCEL", "WARNING": "ERROR", "INFO": "INFO", "REVIEW": "VIEWZOOM"}
CATEGORY = "CRCKTools"


def chars(offset=0):
    """Characters that fit the sidebar's current width (about 6 px each at UI scale 1), less `offset` for what sits beside the text."""
    region = bpy.context.region
    px = (region.width if region is not None else 300) - 44 - offset
    return max(22, int(px / (6.2 * bpy.context.preferences.system.ui_scale)))


def wrap(layout, text, width=None, icon=None, offset=0):
    col = layout.column(align=True)
    for para in text.split(chr(10)):
        for i, line in enumerate(textwrap.wrap(para, width or chars(offset)) or [""]):
            col.label(text=line, icon=icon if (icon and i == 0) else "NONE")
    return col


def count(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def has_vehicle(context):
    return sz.status()[0] and sz.find_fragment(context.active_object) is not None


def head(layout, icon, custom=None):
    """Panel header icon: a custom one of the add-on's own if it loaded, else a built-in one."""
    value = icons.value(custom) if custom else 0
    if value:
        layout.label(text="", icon_value=value)
    else:
        layout.label(text="", icon=icon)


class Sub(bpy.types.Panel):
    """A section of the tab (or a sub-section when it names a parent): collapsible, with an icon in its header, only while a Sollumz
    vehicle is selected."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    icon = "NONE"
    icon_name = None

    @classmethod
    def poll(cls, context):
        return has_vehicle(context)

    def draw_header(self, context):
        head(self.layout, self.icon, self.icon_name)


# --- lists ------------------------------------------------------------------

class VHT_UL_findings(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        title = explain.get(item.code)[0]
        row.label(text=f"{item.target}: {title}" if item.target else title, icon=ICONS[item.severity])
        if item.fix:
            row.label(text="", icon="TOOL_SETTINGS")
        if item.target and item.kind:
            op = row.operator("vht.select", text="", icon="RESTRICT_SELECT_OFF", emboss=False)
            op.target, op.kind = item.target, item.kind

    def filter_items(self, context, data, propname):
        st = context.window_manager.vht
        items = getattr(data, propname)
        show = {"ERROR": st.show_error, "WARNING": st.show_warning, "INFO": st.show_info, "REVIEW": st.show_review}
        return [self.bitflag_filter_item if show[i.severity] else 0 for i in items], []


class VHT_UL_materials(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        m = item.material
        row = layout.row(align=True)
        if m is None:
            row.label(text="(missing material)", icon="ERROR")
            return
        sp = m.shader_properties
        row.label(text=f"{index:2}  {m.name}")
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.label(text=f"{sp.name}  [{sp.renderbucket[:1]}]  idx {sp.index}")


class VHT_UL_paint(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="MATERIAL")
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.label(text=f"{paint.LAYER_LABELS.get(item.layer, item.layer).split(' (')[0]}   {item.polys}")


class VHT_UL_usage(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="MATERIAL")
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.label(text=f"{item.objects} models  {item.polys}  L{item.lods}")


class VHT_UL_hierarchy(bpy.types.UIList):
    """The structure view: root > parts (bone order) > child parts, with a [COL] row under each part that has a
    collision. A part with geometry is a "compound" (shows the LOD slots it has); a part without is a plain node."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        for _ in range(item.depth):
            row.label(text="", icon="BLANK1")
        tri = "DISCLOSURE_TRI_DOWN" if self._open(context, item) else "DISCLOSURE_TRI_RIGHT"
        if item.kind == "root":
            row.operator("vht.tree_toggle", text="", icon=tri, emboss=False).key = item.key
            row.label(text=item.label, icon="OUTLINER_OB_ARMATURE")
            return
        if item.kind == "col":
            row.label(text="", icon="BLANK1")
            grabbed = context.window_manager.vht.tree_grab == "col:" + item.objects
            row.label(text=item.label, icon="PIVOT_CURSOR" if grabbed else "MESH_CUBE")
        else:
            if item.has_children:
                row.operator("vht.tree_toggle", text="", icon=tri, emboss=False).key = item.key
            else:
                row.label(text="", icon="BLANK1")
            grabbed = context.window_manager.vht.tree_grab == "node:" + item.bone
            row.label(text=item.label, icon="PIVOT_CURSOR" if grabbed else ("MESH_DATA" if item.n_geo else "EMPTY_AXIS"))
            if item.lods:
                sub = row.row()
                sub.alignment = "RIGHT"
                sub.label(text="L" + item.lods)
        objs = [bpy.data.objects.get(n) for n in item.objects.split("|") if n]
        hidden = bool(objs) and all(o is not None and o.hide_get() for o in objs)
        op = row.operator("vht.tree_visible", text="", icon="HIDE_ON" if hidden else "HIDE_OFF", emboss=False)
        op.key, op.bone = item.key, item.bone

    @staticmethod
    def _open(context, item):
        return item.key in context.window_manager.vht.tree_open.split("\n")

    def filter_items(self, context, data, propname):
        from . import analysis
        items = getattr(data, propname)
        word = self.filter_name.strip().lower().strip("*")
        if word:  # a search shows every matching row (bone or object name), whatever is collapsed
            def hit(r):
                return word in r.label.lower() or word in r.bone.lower() or any(word in n.lower() for n in r.objects.split("|") if n)
            return [self.bitflag_filter_item if hit(r) else 0 for r in items], []
        shown = analysis.collapse_visible(items, set(context.window_manager.vht.tree_open.split(chr(10))))
        return [self.bitflag_filter_item if s else 0 for s in shown], []


# --- main panel: status, check, preview ----------------------------------------

class VHT_PT_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "CRCKTools"

    def draw_header(self, context):
        head(self.layout, "AUTO", "vehicle")

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        ok, msg = sz.status()
        if not ok or "untested" in msg:
            layout.label(text=msg, icon="ERROR")
        if not ok:
            return
        frag = sz.find_fragment(context.active_object)
        if frag is None:
            wrap(layout, "Select a Sollumz vehicle (the fragment, or any part inside it) to start.", icon="INFO")
            return
        layout.label(text=frag.name, icon="AUTO")
        layout.prop(st, "profile", text="Type")

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("vht.validate", icon="CHECKMARK")
        n = {s: sum(1 for f in st.findings if f.severity == s) for s in ("ERROR", "WARNING", "INFO", "REVIEW")}
        if st.findings and st.fragment == frag.name:
            bad = n["ERROR"] + n["WARNING"]
            if bad:
                layout.label(text=f"{count(n['ERROR'], 'error')}, {count(n['WARNING'], 'warning')}", icon="ERROR")
            else:
                layout.label(text="No errors or warnings", icon="CHECKMARK")
        row = layout.row(align=True)
        row.operator("vht.suggest", text="Preview All Quick Fixes", icon="TOOL_SETTINGS")
        row.operator("vht.clear", text="", icon="X")
        layout.operator("vht.arrange", icon="MOD_ARRAY")

        if st.plan:
            box = layout.box()
            box.label(text=f"{count(len(st.plan), 'change')} ready", icon="HIDE_OFF")
            box.label(text="Nothing is applied until you press Apply")
            for p in st.plan:
                r = box.row(align=True)
                r.prop(p, "enabled", text="")
                wrap(r, p.text, offset=34)
            row = box.row()
            row.scale_y = 1.3
            row.operator("vht.apply", icon="CHECKMARK")
        if st.arrange_notes:
            box = layout.box()
            box.label(text="No known place for these (needs you)", icon="QUESTION")
            wrap(box, st.arrange_notes)
        if st.report:
            box = layout.box()
            box.label(text="Last result (Ctrl+Z undoes it)", icon="INFO")
            wrap(box, st.report)


class VHT_PT_problems(Sub):
    bl_label = "Problems"
    icon = "ERROR"

    @classmethod
    def poll(cls, context):
        return has_vehicle(context) and bool(context.window_manager.vht.findings)

    def draw_header(self, context):
        st = context.window_manager.vht
        head(self.layout, self.icon)
        self.layout.label(text=str(sum(1 for f in st.findings if f.severity in ("ERROR", "WARNING"))))

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        row = layout.row(align=True)
        for sev, prop in (("ERROR", "show_error"), ("WARNING", "show_warning"), ("INFO", "show_info"), ("REVIEW", "show_review")):
            n = sum(1 for f in st.findings if f.severity == sev)
            row.prop(st, prop, text=str(n), icon=ICONS[sev], toggle=True)
        layout.template_list("VHT_UL_findings", "", st, "findings", st, "findings_index", rows=5)
        quick = sum(1 for f in st.findings if f.fix)
        if quick:
            layout.label(text=f"{quick} with a quick fix (wrench)", icon="TOOL_SETTINGS")
        if not 0 <= st.findings_index < len(st.findings):
            layout.label(text="Click a problem to see how to fix it", icon="INFO")
            return
        f = st.findings[st.findings_index]
        title, why, how, quick_text = explain.get(f.code)
        box = layout.box()
        box.label(text=title, icon=ICONS[f.severity])
        row = box.row(align=True)
        row.label(text=f"On: {f.target}" if f.target else "")
        if f.target and f.kind:
            op = row.operator("vht.select", text="Select", icon="RESTRICT_SELECT_OFF")
            op.target, op.kind = f.target, f.kind
        sub = box.column(align=True)
        sub.label(text="What is wrong", icon="ERROR")
        wrap(sub, f.message)
        if why and why not in f.message:
            sub.separator()
            wrap(sub, why)
        sub = box.column(align=True)
        sub.separator()
        sub.label(text="How to fix it", icon="TOOL_SETTINGS")
        wrap(sub, how or "No general steps for this one; the message above says what it is.")
        fix = box.column(align=True)
        fix.separator()
        if f.fix:
            fix.label(text="Quick fix", icon="CHECKMARK")
            wrap(fix, quick_text or "Available.")
            fix.operator("vht.fix_finding", icon="HIDE_OFF")
        else:
            fix.label(text="No quick fix: do the steps by hand", icon="INFO")
        sub = box.column(align=True)
        sub.separator()
        wrap(sub, explain.SEVERITY[f.severity])


# --- hierarchy ---------------------------------------------------------------

class VHT_PT_vehicle_group(Sub):
    bl_label = "Vehicle"
    icon_name = "part"
    icon = "OUTLINER_OB_ARMATURE"

    def draw(self, context):
        wrap(self.layout, "The parts of the vehicle: the tree, local axes, renaming and bone order.")


class VHT_PT_hierarchy(Sub):
    bl_label = "Hierarchy"
    bl_parent_id = "VHT_PT_vehicle_group"
    icon = "OUTLINER"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        frag = sz.find_fragment(context.active_object)
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("vht.inspect", text="Refresh Hierarchy", icon="FILE_REFRESH")
        if not st.tree or st.fragment != frag.name:
            wrap(layout, "Press Refresh to read this vehicle. Nesting sets bone parents, order sets bone indices, and "
                         "geometry and collision belong to the part they sit in.")
            return
        # LOD slot buttons : which slot of every part is displayed
        models = [o for o in frag.children_recursive if sz.sollum_type(o) == sz.DRAWABLE_MODEL]
        current = models[0].sz_lods.active_lod_level if models else ""
        row = layout.row(align=True)
        row.label(text="Show:")
        for i, lvl in enumerate(("sollumz_veryhigh", "sollumz_high", "sollumz_medium", "sollumz_low", "sollumz_verylow")):
            row.operator("vht.tree_lod", text=f"L{i}", depress=(current == lvl)).level = i
        row.operator("vht.tree_col", text="COL", depress=bool(context.scene.sollumz_show_collisions))
        layout.template_list("VHT_UL_hierarchy", "", st, "tree", st, "tree_index", rows=12)
        row = layout.row(align=True)
        row.operator("vht.tree_expand", text="Expand", icon="DISCLOSURE_TRI_DOWN").mode = "ALL"
        row.operator("vht.tree_expand", text="Collapse", icon="DISCLOSURE_TRI_RIGHT").mode = "NONE"
        row = layout.row(align=True)
        row.operator("vht.tree_show", text="Isolate", icon="ZOOM_SELECTED").mode = "ISOLATE"
        row.operator("vht.tree_show", text="Show", icon="HIDE_OFF").mode = "SHOW"
        row.operator("vht.tree_show", text="Hide", icon="HIDE_ON").mode = "HIDE"

        box = layout.box()
        box.label(text="Move a part", icon="PIVOT_CURSOR")
        if st.tree_grab:
            row = box.row(align=True)
            row.label(text="Holding: " + st.tree_grab.split(":", 1)[1], icon="PIVOT_CURSOR")
            row.operator("vht.tree_grab", text="", icon="X").cancel = True
            wrap(box, "Click the part to drop it on, then choose:")
            row = box.row(align=True)
            for mode, label in (("INTO", "Into"), ("BEFORE", "Before"), ("AFTER", "After")):
                row.operator("vht.tree_drop", text=label).mode = mode
        else:
            box.operator("vht.tree_grab", text="Grab the Selected Row", icon="PIVOT_CURSOR")
            wrap(box, "Then click the target part and Drop it Into, Before or After it.")
        box.operator("vht.tree_drop", text="Unlink from Parent", icon="UNLINKED").mode = "UNLINK"
        row = box.row(align=True)
        row.operator("vht.tree_move", text="Move Up", icon="TRIA_UP").direction = "UP"
        row.operator("vht.tree_move", text="Move Down", icon="TRIA_DOWN").direction = "DOWN"
        col = layout.column(align=True)
        col.operator("vht.tree_attach", text="Put Selected Objects on This Part", icon="CONSTRAINT_BONE")
        col.operator("vht.tree_adopt", text="Put Selected Bones Under This Part", icon="LINKED")


class VHT_PT_lods(Sub):
    bl_label = "Generate LODs"
    bl_parent_id = "VHT_PT_vehicle_group"
    bl_options = {"DEFAULT_CLOSED"}
    icon = "MOD_DECIM"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        wrap(layout, "Fills the LOD slots below the start level, from L0 (_hi) or from the existing L1. Material borders, UVs and shading are kept; "
                     "wheels, glass, lights and mirrors keep extra detail. The start meshes are never changed.")
        layout.prop(st, "lod_scope", text="")
        layout.prop(st, "lod_start")
        frag = sz.find_fragment(context.active_object)
        if frag is not None:
            from . import analysis, lodgen
            models = analysis.load(frag).models
            have = lodgen.slot_counts(models)
            box = layout.box()
            box.label(text=f"Parts with a mesh in each level (of {len(models)}):")
            row = box.row(align=True)
            for i, (s, _) in enumerate(lodgen.LEVELS):
                row.label(text=f"L{i} {have[s]}")
            missing = len(models) - have[st.lod_start]
            if missing:
                box.label(text=f"{missing} part(s) have no L{lodgen.SLOT_INDEX[st.lod_start]} mesh and will be skipped", icon="ERROR")
        col = layout.column(align=True)
        col.label(text="Triangles kept (of the start mesh, 0 = skip)")
        if st.lod_start == "very_high":
            col.prop(st, "lod_high", slider=True)
        col.prop(st, "lod_medium", slider=True)
        col.prop(st, "lod_low", slider=True)
        col.prop(st, "lod_very_low", slider=True)
        if st.lod_start == "high":
            layout.prop(st, "lod_make_hi")
        layout.prop(st, "lod_overwrite")
        box = layout.box()
        box.label(text="Quality", icon="PREFERENCES")
        box.prop(st, "lod_method")
        box.prop(st, "lod_protect", slider=True)
        box.prop(st, "lod_shading")
        box.prop(st, "lod_chain")
        from . import meshopt
        if not meshopt.available():
            box.label(text="meshoptimizer is not available: Blender Decimate is used", icon="ERROR")
        row = layout.row()
        row.scale_y = 1.3
        row.operator("vht.lods_generate", icon="MOD_DECIM")


class VHT_PT_axes(Sub):
    bl_label = "Local Axes"
    bl_parent_id = "VHT_PT_vehicle_group"
    bl_options = {"DEFAULT_CLOSED"}
    icon = "ORIENTATION_LOCAL"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        frag = sz.find_fragment(context.active_object)
        wrap(layout, "The axes of the active part decide what a rotor spins on or a door swings around. These keep "
                     "geometry, children and collisions where they are.")
        row = st.tree[st.tree_index] if 0 <= st.tree_index < len(st.tree) else None
        picked = sz.selected_bones(frag) if context.mode == "POSE" else []
        if len(picked) > 1:
            layout.label(text=f"Acts on: {len(picked)} selected bones, each on its own", icon="BONE_DATA")
        else:
            from . import analysis, operators
            target = row.bone if row is not None and row.kind == "node" else None
            if operators.bone_token(frag) != st.seen_bone:  # picked elsewhere since the last row click: the tools follow it
                target = operators.selected_part(analysis.load(frag)) or target
            layout.label(text=f"Acts on: {target}" if target else "Acts on: select a part", icon="BONE_DATA")
        layout.prop(frag.data, "show_axes", text="Show axes in viewport")
        row = layout.row(align=True)
        row.prop(st, "axes_rotation", toggle=True)
        row.prop(st, "axes_position", toggle=True)
        col = layout.column(align=True)
        col.operator("vht.tree_axes", text="Center to Object", icon="PIVOT_BOUNDBOX").mode = "CENTER"
        col.operator("vht.tree_axes", text="Reset to Parent", icon="PARTICLE_PATH").mode = "PARENT"
        col.operator("vht.tree_axes", text="Reset to World", icon="WORLD").mode = "WORLD"
        col.operator("vht.tree_axes", text="Align Spin Axis to Geometry", icon="ORIENTATION_NORMAL").mode = "ALIGN"
        col.operator("vht.tree_axes", text="Origin to 3D Cursor", icon="CURSOR").mode = "CURSOR"
        col.operator("vht.tree_axes", text="Copy From Grabbed", icon="COPYDOWN").mode = "COPY"


class VHT_PT_couple(Sub):
    bl_label = "Parts and Bone Order"
    bl_parent_id = "VHT_PT_vehicle_group"
    bl_options = {"DEFAULT_CLOSED"}
    icon = "BONE_DATA"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        frag = sz.find_fragment(context.active_object)
        wrap(layout, "A part is a bone plus the objects bound to it. These only fill the change preview.")
        box = layout.box()
        box.label(text="Put several objects on one part", icon="MESH_DATA")
        box.prop_search(st, "couple_bone", frag.data, "bones", text="Part")
        box.operator("vht.couple_objects", icon="CONSTRAINT_BONE")
        box = layout.box()
        box.label(text="Put several parts under one part", icon="BONE_DATA")
        box.operator("vht.couple_bones", icon="LINKED")
        box = layout.box()
        box.label(text="Rename part", icon="TEXT")
        box.prop(st, "rename_scope", text="")
        if st.rename_scope == "ACTIVE":
            box.prop(st, "rename_replace", text="Name")
            box.prop(st, "rename_find", text="Find")
        else:
            box.prop(st, "rename_find", text="Find")
            box.prop(st, "rename_replace", text="Replace with")
        box.operator("vht.rename_part", icon="HIDE_OFF")
        box.label(text="Renames the bone and the objects named after it")
        box = layout.box()
        box.label(text="Bone order (export index)", icon="SORTALPHA")
        row = box.row(align=True)
        row.operator("vht.move_bone", text="Up", icon="TRIA_UP").direction = "UP"
        row.operator("vht.move_bone", text="Down", icon="TRIA_DOWN").direction = "DOWN"
        box = layout.box()
        box.label(text="Outliner view of the parts", icon="OUTLINER_COLLECTION")
        row = box.row(align=True)
        row.operator("vht.build_parts", icon="OUTLINER_COLLECTION")
        row.operator("vht.remove_parts", text="", icon="X")


# --- materials ---------------------------------------------------------------

class VHT_PT_materials_group(Sub):
    bl_label = "Materials"
    bl_options = {"DEFAULT_CLOSED"}
    icon = "MATERIAL"

    def draw(self, context):
        wrap(self.layout, "Paint colours, liveries, default textures and shader order.")


class MatSub(Sub):
    bl_parent_id = "VHT_PT_materials_group"


class VHT_PT_mat_paint(MatSub):
    bl_label = "Paint Layers"
    icon = "BRUSH_DATA"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        wrap(layout, "Select faces (Edit mode) or models (Object mode), make a paint material the active slot, then press a layer. "
                     "A colour variant is a copy of the material with another layer.")
        layout.operator("vht.paint_refresh", icon="FILE_REFRESH")
        if st.paint:
            layout.template_list("VHT_UL_paint", "", st, "paint", st, "paint_index", rows=5)
        obj = context.active_object
        mat = obj.active_material if obj is not None and obj.type == "MESH" else None
        if mat is not None and paint.is_paint_material(mat):
            box = layout.box()
            box.label(text=mat.name, icon="MATERIAL")
            box.prop(mat, "sz_paint_layer", text="Layer")
        col = layout.column(align=True)
        col.label(text="Paint the selection as:")
        for i in range(0, 6, 2):
            row = col.row(align=True)
            for name in paint.LAYERS[i:i + 2]:
                row.operator("vht.paint_assign", text=paint.LAYER_LABELS[name]).layer = name
        row = col.row(align=True)
        row.operator("vht.paint_assign", text="Custom").layer = "CUSTOM"
        row.operator("vht.paint_assign", text="Default").layer = "DEFAULT"


class VHT_PT_mat_shader(MatSub):
    bl_label = "Vehicle Shaders"
    icon = "SHADING_RENDERED"

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        wrap(layout, "Every vehicle shader Sollumz has. A new material starts with the shared textures vanilla vehicles use for it, "
                     "so you only add the textures that belong to your vehicle.")
        layout.prop(st, "vehicle_shader", text="")
        if st.vehicle_shader:
            try:
                rows = vehicleshaders.preview(st.vehicle_shader)
            except Exception:
                rows = []
            box = layout.box()
            for sampler, tex in rows:
                r = box.row()
                r.label(text=sampler.replace("Sampler", ""))
                r.label(text=tex or "your own texture")
            if st.vehicle_shader.startswith("vehicle_paint"):
                layout.prop(st, "paint_layer")
        layout.operator("vht.shader_add", icon="ADD")


class VHT_PT_mat_add(MatSub):
    bl_label = "Add Paint Material"
    icon = "ADD"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        wrap(layout, "A new paint material from a shader and a layer, put on the selection. Textures start with the names "
                     "vanilla vehicles use.")
        layout.prop(st, "paint_shader")
        note = paint.SHADER_NOTES.get(st.paint_shader)
        if note:
            wrap(layout, note[1])
        layout.prop(st, "paint_layer")
        layout.operator("vht.paint_add", icon="ADD")


class VHT_PT_mat_livery(MatSub):
    bl_label = "Livery"
    icon = "IMAGE_DATA"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wrap(layout, "A livery is the vehicle_paint3_lvr shader: the paint material plus a livery image on the second UV map. "
                     "Make the active paint material a livery, then load the image.")
        layout.operator("vht.paint_livery", icon="MATERIAL")
        obj = context.active_object
        mat = obj.active_material if obj is not None and obj.type == "MESH" else None
        node = mat.node_tree.nodes.get("DiffuseSampler3") if mat is not None and mat.node_tree is not None else None
        if node is not None:
            layout.label(text=f"Livery texture: {node.sollumz_texture_name or '(blank)'}", icon="IMAGE_DATA")
            layout.operator("vht.paint_livery_texture", icon="FILE_FOLDER")


class VHT_PT_mat_textures(MatSub):
    bl_label = "Default Textures"
    icon = "TEXTURE"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wrap(layout, "An empty sampler exports no texture name. This fills the ones vanilla vehicles give a generic texture "
                     "(spec, dirt, normal, glass, tyres, plates). A sampler for the vehicle's own texture stays empty.")
        layout.operator("vht.fill_textures", icon="TEXTURE")


class VHT_PT_mat_usage(MatSub):
    bl_label = "Usage and Textures"
    icon = "NODE_MATERIAL"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        wrap(layout, "Which materials the vehicle uses, by how many models and polygons (displayed LOD). Click one, then select its users "
                     "or replace it everywhere.")
        layout.operator("vht.usage_refresh", icon="FILE_REFRESH")
        if st.usage:
            layout.template_list("VHT_UL_usage", "", st, "usage", st, "usage_index", rows=6)
            layout.operator("vht.usage_select", icon="RESTRICT_SELECT_OFF")
            box = layout.box()
            box.prop(st, "usage_target")
            box.operator("vht.usage_replace", icon="FILE_REFRESH")
        if st.usage_report:
            box = layout.box()
            box.label(text="Textures", icon="TEXTURE")
            wrap(box, st.usage_report)
        elif st.usage:
            layout.label(text="No texture problems found", icon="CHECKMARK")


class VHT_PT_mat_transfer(MatSub):
    bl_label = "Transfer Materials"
    icon = "COPYDOWN"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wrap(layout, "Select the models that should receive materials, then the model that has them last (the active one). They share the "
                     "very same materials, so the shader group gets no duplicates. Object mode.")
        col = layout.column(align=True)
        col.operator("vht.mat_transfer", text="Copy All Slots", icon="MATERIAL").mode = "ALL"
        col.operator("vht.mat_transfer", text="Copy Active Material Only", icon="MATERIAL_DATA").mode = "ACTIVE"


class VHT_PT_materials(MatSub):
    bl_label = "Material Order"
    icon = "SORTALPHA"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        frag = sz.find_fragment(context.active_object)
        wrap(layout, "The order Sollumz writes the shaders in (its shader index), the shader group order. [A] = alpha bucket.")
        layout.operator("vht.mat_load", icon="IMPORT")
        layout.operator("vht.mat_autosort", icon="SORTALPHA")
        row = layout.row()
        row.template_list("VHT_UL_materials", "", frag, "vht_material_order", frag, "vht_material_order_index", rows=6)
        col = row.column(align=True)
        for d, icon in (("TOP", "TRIA_UP_BAR"), ("UP", "TRIA_UP"), ("DOWN", "TRIA_DOWN"), ("BOTTOM", "TRIA_DOWN_BAR")):
            col.operator("vht.mat_move", text="", icon=icon).direction = d
        layout.operator("vht.mat_preview", icon="HIDE_OFF")


# --- export info -------------------------------------------------------------

class VHT_PT_order(Sub):
    bl_label = "Export Info"
    bl_options = {"DEFAULT_CLOSED"}
    icon = "EXPORT"

    @classmethod
    def poll(cls, context):
        return has_vehicle(context)

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.vht
        layout.operator("vht.export_compact", icon="EXPORT")
        layout.operator("vht.estimate_size", icon="FILE_TICK")
        if st.size_report:
            wrap(layout.box(), st.size_report)
        section, col, shown = None, None, 0
        for r in st.order:
            if r.section != section:
                section, shown = r.section, 0
                box = layout.box()
                box.label(text=section)
                col = box.column(align=True)
            shown += 1
            if shown == 101:
                col.label(text="...")
            elif shown <= 100:
                col.label(text=r.text)


classes = (VHT_UL_findings, VHT_UL_materials, VHT_UL_paint, VHT_UL_usage, VHT_UL_hierarchy,
           VHT_PT_main, VHT_PT_problems, VHT_PT_vehicle_group, VHT_PT_hierarchy, VHT_PT_axes, VHT_PT_couple, VHT_PT_lods,
           VHT_PT_materials_group, VHT_PT_mat_paint, VHT_PT_mat_shader, VHT_PT_mat_add, VHT_PT_mat_livery, VHT_PT_mat_textures, VHT_PT_mat_usage, VHT_PT_mat_transfer, VHT_PT_materials,
           VHT_PT_order)
