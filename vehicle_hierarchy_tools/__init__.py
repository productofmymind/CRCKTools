"""CRCKTools: vehicle tools for Sollumz.

Part tree, part coupling, validation and material ordering for GTA V vehicle fragments,
built on top of Sollumz (never modifies Sollumz itself).
"""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)

from . import icons, operators, paint, rulecheck, ui, vehicleshaders

class VHT_MaterialItem(bpy.types.PropertyGroup):
    material: PointerProperty(type=bpy.types.Material)


class VHT_TreeRow(bpy.types.PropertyGroup):
    kind: StringProperty()      # root | node | col
    depth: IntProperty()
    key: StringProperty()       # collapse key
    label: StringProperty()
    bone: StringProperty()
    index: IntProperty()
    objects: StringProperty()   # "|"-joined names of the node's own geometry and collisions
    lods: StringProperty()      # digits of the LOD slots present (the compound's slots)
    n_geo: IntProperty()
    n_col: IntProperty()
    has_children: BoolProperty()


class VHT_PaintRow(bpy.types.PropertyGroup):
    name: StringProperty()      # material name
    shader: StringProperty()
    layer: StringProperty()     # Sollumz paint layer name
    polys: IntProperty()
    parts: StringProperty()


class VHT_UsageRow(bpy.types.PropertyGroup):
    name: StringProperty()      # material name
    shader: StringProperty()
    polys: IntProperty()
    objects: IntProperty()
    lods: StringProperty()


class VHT_OrderRow(bpy.types.PropertyGroup):
    section: StringProperty()
    text: StringProperty()


class VHT_Finding(bpy.types.PropertyGroup):
    severity: StringProperty()
    code: StringProperty()
    message: StringProperty()
    target: StringProperty()
    kind: StringProperty()
    fix: StringProperty()


class VHT_PlanItem(bpy.types.PropertyGroup):
    text: StringProperty()
    kind: StringProperty()
    fix: StringProperty()
    enabled: BoolProperty(default=True)
    destructive: BoolProperty()


def _lod_defaults(st):
    """Switching the start level resets the ratios to what vanilla vehicles use for it."""
    from . import lodgen
    r = lodgen.VANILLA[st.lod_start]
    st.lod_high = r.get("high", 0.0)
    st.lod_medium, st.lod_low, st.lod_very_low = r["medium"], r["low"], r["very_low"]


class VHT_State(bpy.types.PropertyGroup):
    """Session results (WindowManager: not saved in the .blend, not affected by undo)."""
    fragment: StringProperty()
    tree: CollectionProperty(type=VHT_TreeRow)
    tree_filter: StringProperty(name="Filter")
    tree_open: StringProperty(description="Collapse keys of the open nodes, newline-separated")
    tree_grab: StringProperty(description="The part or [COL] row picked up with Grab: node:<bone> or col:<object>")
    tree_index: IntProperty(update=lambda self, context: operators.on_tree_index(context))
    paint: CollectionProperty(type=VHT_PaintRow)
    paint_index: IntProperty(update=lambda self, context: operators.on_paint_index(context))
    paint_shader: EnumProperty(name="Shader", items=paint.shader_items(),
                               default="vehicle_paint4.sps", description="Shader of the new paint material")
    vehicle_shader: EnumProperty(name="Shader", items=vehicleshaders.items, description="Vehicle shader of the new material")
    paint_layer: EnumProperty(name="Layer", items=[(n, paint.LAYER_LABELS[n], "") for n in paint.LAYERS], default="PRIMARY",
                              description="Which paint colour the new material uses")
    axes_rotation: BoolProperty(name="Rotation", default=True, description="Reset to World / Reset to Parent / Copy change the orientation")
    axes_position: BoolProperty(name="Position", default=False, description="Reset to World / Reset to Parent / Copy also move the origin (world origin, the parent's origin, or the copied part's origin)")
    order: CollectionProperty(type=VHT_OrderRow)
    findings: CollectionProperty(type=VHT_Finding)
    findings_index: IntProperty()
    plan: CollectionProperty(type=VHT_PlanItem)
    report: StringProperty()
    arrange_notes: StringProperty()
    seen_bone: StringProperty()
    lod_scope: EnumProperty(name="Parts", items=[("ALL", "Every part", "All the vehicle's models"), ("SELECTED", "Selected models", "Only the selected models")],
                            default="ALL")
    lod_start: EnumProperty(name="Start from", items=[("high", "L1 (high)", "Reduce from the existing L1 mesh; the levels below it are filled, L0 is not touched"),
                                                      ("very_high", "L0 (_hi)", "Reduce from the very-high (_hi) mesh; L1 and everything below are filled")],
                            default="high", update=lambda self, ctx: _lod_defaults(self))
    lod_method: EnumProperty(name="Method", items=[("AUTO", "Auto (recommended)", "meshoptimizer above about 40% of the triangles, Blender's Decimate below, "
                                                                                 "Blender's for parts with many vertex groups"),
                                                   ("MESHOPT", "meshoptimizer", "Attribute-aware, material borders protected; needs lib/meshoptimizer.dll"),
                                                   ("BLENDER", "Blender Decimate", "Collapse decimation")], default="AUTO")
    lod_make_hi: BoolProperty(name="Also copy L1 to L0 (_hi) if empty", default=False,
                              description="When starting from L1: copy the high mesh into an empty very-high slot, which becomes the _hi file")
    lod_high: FloatProperty(name="L1 high", default=0.30, min=0.0, max=1.0, description="Share of the start mesh's triangles kept. 0 leaves the slot empty")
    lod_medium: FloatProperty(name="L2 medium", default=0.50, min=0.0, max=1.0, description="Share of the start mesh's triangles kept. 0 leaves the slot empty")
    lod_low: FloatProperty(name="L3 low", default=0.27, min=0.0, max=1.0, description="Share of the start mesh's triangles kept. 0 leaves the slot empty")
    lod_very_low: FloatProperty(name="L4 very low", default=0.09, min=0.0, max=1.0, description="Share of the start mesh's triangles kept. 0 leaves the slot empty")
    lod_chain: BoolProperty(name="Each level from the previous one", default=False,
                            description="Reduce every level from the next higher level instead of from the start mesh. Measured no better, so off by default")
    lod_protect: FloatProperty(name="Protect wheels, glass, lights, mirrors", default=1.5, min=1.0, max=3.0,
                               description="Parts that must keep their look keep this many times more triangles. 1 turns it off")
    lod_shading: BoolProperty(name="Keep original shading", default=True,
                              description="Transfer the start mesh's normals onto each level (hard edges stay hard)")
    lod_overwrite: BoolProperty(name="Replace existing", default=False, description="Rebuild slots that already have a mesh. Off: they are left alone")
    usage: CollectionProperty(type=VHT_UsageRow)
    usage_index: IntProperty()
    usage_report: StringProperty()
    usage_target: PointerProperty(type=bpy.types.Material, name="Replace with", description="The material that takes the place of the selected one",
                                  poll=lambda self, m: m.sollum_type == "sollumz_material_shader")
    rename_scope: EnumProperty(name="Rename", items=[("ACTIVE", "This part", "The part the tools act on"),
                                                      ("SELECTED", "Selected bones", "The bones selected in Pose mode"),
                                                      ("ALL", "Whole vehicle", "Every part whose name contains the Find text")],
                               default="ACTIVE", description="Which parts to rename")
    rename_find: StringProperty(name="Find", description="Text to replace in the part names. Empty: the part gets the Replace text as its whole new name")
    rename_replace: StringProperty(name="Replace with", description="The new text, or the whole new name when Find is empty")
    size_report: StringProperty()
    profile: EnumProperty(name="Profile", items=[(p, p if p == "AUTO" else p.title(), "") for p in rulecheck.PROFILES],
                          default="AUTO", description="Vehicle type for the required-bone checks. AUTO guesses it from the bones")
    show_error: BoolProperty(default=True)
    show_warning: BoolProperty(default=True)
    show_info: BoolProperty(default=False)
    show_review: BoolProperty(default=True)
    couple_bone: StringProperty(name="Part", description="Bone that the selected objects are coupled to")


classes = (VHT_MaterialItem, VHT_TreeRow, VHT_PaintRow, VHT_UsageRow, VHT_OrderRow, VHT_Finding, VHT_PlanItem, VHT_State) + operators.classes + ui.classes


def menu_export(self, context):
    self.layout.operator("vht.export_compact", text="CRCK Export")


def register():
    icons.register()
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.vht_material_order = CollectionProperty(type=VHT_MaterialItem)
    bpy.types.Object.vht_material_order_index = IntProperty()
    bpy.types.WindowManager.vht = PointerProperty(type=VHT_State)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    del bpy.types.WindowManager.vht
    del bpy.types.Object.vht_material_order_index
    del bpy.types.Object.vht_material_order
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    icons.unregister()
