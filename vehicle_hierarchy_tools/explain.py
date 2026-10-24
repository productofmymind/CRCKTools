"""Plain-language text for every finding code: what it is, why it matters, how to fix it by hand, and what the quick fix does.

The finding's own message carries the specifics (bone and object names, counts). This adds the general part, so the Problems panel can say
"what is wrong" and "how to fix it" without the reader knowing the code.
"""

SEVERITY = {
    "ERROR": "Error: the export fails or the vehicle is broken in game.",
    "WARNING": "Warning: probably wrong, and worth fixing before export.",
    "INFO": "Info: worth knowing; often fine.",
    "REVIEW": "Review: check it yourself.",
}

# code: (short title, why it matters, how to fix it by hand, what the quick fix does or None)
CATALOG = {
    # --- structure
    "FRAG_NOT_ARMATURE": ("The vehicle is not an armature", "Sollumz only exports a fragment whose object is an armature.",
                          "Re-import the vehicle, or create it with Sollumz's Create Fragment. The fragment object must be an Armature.", None),
    "NO_DRAWABLE": ("No Drawable under the vehicle", "Sollumz refuses to export a fragment that has none.",
                    "Create a Drawable (Sollumz tools) under the fragment and put the models under it.", None),
    "NO_BONES": ("The skeleton has no bones", "There is nothing to bind parts to.",
                 "Add bones in Edit mode, starting with a root bone called chassis.", None),
    "MULTIPLE_ROOTS": ("More than one root bone", "A vehicle skeleton has exactly one root, chassis.",
                       "Put the extra roots under the chassis: in the Hierarchy panel grab the part and Drop it Into the chassis.", None),
    "EXTRA_DRAWABLE": ("A second Drawable", "Sollumz exports only the first one; the rest is lost.",
                       "Move its models under the first Drawable and delete the extra one.", None),
    "EXTRA_COMPOSITE": ("A second Bound Composite", "Sollumz exports only the first one; the rest is lost.",
                        "Move its collisions under the first composite and delete the extra one.", None),
    "NESTED_MODEL": ("Model is inside another object", "Sollumz only exports models that sit directly under the Drawable, so this mesh is dropped.",
                     "Drag it in the Outliner onto the Drawable. Express hierarchy with bones, not parenting.",
                     "Moves it under the Drawable without moving it in space."),
    "MODEL_UNBOUND": ("Model is not on any bone", "It exports on the root bone, so it never moves with its part.",
                      "Bind it to a bone: pick the bone under Parts > Several objects under one part, then preview.",
                      "Binds it to the bone it is named after."),
    "BOUND_ELSEWHERE": ("Named after one bone, bound to another",
                        "Vanilla vehicles keep a model or collision on the bone it is named after. This may be deliberate.",
                        "If it is a mistake, re-bind it to the bone in its name; otherwise rename the object.",
                        "Re-binds it to the bone in its name (listed but unticked)."),
    "STRAY_VGROUPS": ("Vertex groups that match no bone", "They are ignored on export, so those weights do nothing.",
                      "Rename each group to its bone, or delete the ones you do not need (Object Data > Vertex Groups).", None),
    # --- collisions and physics
    "BOUND_OUTSIDE_COMPOSITE": ("Collision is not under the Bound Composite", "Sollumz exports only the composite's children, so it is lost.",
                                "Drag it onto the composite in the Outliner.", "Moves it under the composite, keeping its position."),
    "BOUND_UNBOUND": ("Collision is not on any bone", "It never becomes a physics part of the vehicle.",
                      "Bind it to a bone like a model: Parts > Several objects under one part.", "Binds it to the bone it is named after."),
    "BOUND_BONE_NO_PHYSICS": ("Collision on a bone with Use Physics off", "Sollumz skips such a collision, so it is not exported.",
                              "Turn on Use Physics for the bone (Bone properties > Sollumz), or unbind the collision.",
                              "Turns Use Physics on for the bone."),
    "PHYSICS_MESH_NO_PHYSICS": ("Wheel or breakable part will be missing from the file", "Its bone has Use Physics off, so Sollumz writes no physics group and drops the mesh.",
                                "Turn on Use Physics for the bone (Bone properties > Sollumz).", "Turns Use Physics on for the bone."),
    "WHEEL_NO_COLLISION": ("Wheel bone has no collision", "The game makes a wheel from a physics group with a collision; a wheel bone without one gets no wheel, so that "
                           "corner of the vehicle shows none. Vanilla vehicles keep the wheel mesh on wheel_lf only; every other wheel has just Use Physics and a disc collision.",
                           "Duplicate the collision of another wheel, rename it after this bone (wheel_lr.col), move it to the wheel, bind it to the bone "
                           "(Parts and Bone Order) and turn Use Physics on for the bone.",
                           "Copies the collision of another wheel bone here (or, if none has one, builds a disc from the wheel model), binds it and turns Use Physics on."),
    "PHYSICS_NO_COLLISION": ("Use Physics is on but the bone has no collision", "Sollumz drops the physics group for this bone.",
                             "Bind a collision to the bone, or turn Use Physics off.", None),
    "COLLISION_MASS_ZERO": ("Collision has no mass", "A fragment whose physics parts weigh nothing has no usable mass; the vehicle can freeze or ignore gravity.",
                            "Sollumz Tools > Fragment > Set Mass, or set Mass on the collision (Fragment Child).", None),
    # --- bone names and tags
    "BONE_NAME_SUFFIX": ("Bone name ends in .001", "The tag is hashed from the full name, so the game does not recognise the part.",
                         "Rename the bone without the suffix (rename or delete the other bone of that name first).", "Renames the bone without the suffix."),
    "TAG_MISMATCH": ("Bone tag differs from its name", "The tag no longer matches the name hash, and the game finds parts by tag.",
                     "Turn off Use Manual Tag on the bone so the tag follows its name.", "Turns the manual tag off."),
    "HV001_ROOT_NAME": ("Root bone is not called chassis", "Vehicles use chassis as the root.", "Rename the root bone to chassis.", None),
    "HV002_DUPLICATE_NAME": ("Two bones differ only by letter case", "Tags are hashed from the upper-cased name, so they collide.",
                             "Rename one of the bones.", None),
    "HV003_UNKNOWN_BONE": ("Bone name the game does not know", "The engine finds parts by name, so an unknown name does nothing unless a script uses it.",
                           "Rename it to the part it should be. For a custom part you can ignore this.", "Renames it to the one close match."),
    "HV004_ROOT_TAG": ("Root bone tag is not 0", "The root bone uses tag 0.", "Turn off the manual tag on the root bone, or set it to 0.",
                       "Makes the tag follow the name."),
    "HV005_DUPLICATE_TAG": ("Two bones share a tag", "The game resolves parts by tag, so one of them is lost.",
                            "Rename one bone, or give it another manual tag.", None),
    # --- profile
    "HV010_MISSING_REQUIRED": ("A bone this vehicle type needs is missing", "The chosen profile requires it.",
                               "Add the bone in Edit mode under its usual parent, or pick another profile.", None),
    "HV010_MISSING_RECOMMENDED": ("A bone vehicles of this type usually have", "Nothing breaks without it.",
                                  "Add it if the vehicle has that part; otherwise ignore this.", None),
    "HV011_FORBIDDEN_PRESENT": ("A bone this vehicle type should not have", "The chosen profile does not use it.",
                                "Remove the bone, or pick another profile.", None),
    # --- parents
    "HV020_PARENT": ("Bone is under an unusual parent", "Vanilla vehicles put this bone somewhere else (their counts are in the message).",
                     "Move it in the Hierarchy panel: Grab it, click the usual parent, Drop Into.", "Moves the bone under its usual parent."),
    "HV021_WINDOW_NOT_IN_DOOR": ("Window is not inside its door", "The glass stays put when the door opens.",
                                 "Move the window bone under its door bone (Hierarchy: Grab, Drop Into).", "Moves the window bone under its door."),
    "HV022_BIKE_WHEEL_PARENT": ("Bike wheel is not under its fork or swingarm", "The wheel will not follow the suspension.",
                                "Move the wheel bone under the fork or swingarm.", "Moves the wheel bone under it."),
    "HV032_NO_JOINT": ("Opening part has no hinge or slide limit",
                       "A door, bonnet or boot needs a Limit Rotation or Limit Location constraint to export as a joint; without one it never opens.",
                       "In Pose mode add a Limit Rotation (hinge) or Limit Location (slide) bone constraint to the part.", None),
    "HV061_PARENT_ORDER": ("A bone comes before its parent", "The skeleton must list parents first.",
                           "Re-parent the bone, or use Move Up/Down in the Hierarchy panel.", None),
    # --- glass
    "HV040_GLASS_NO_COLLISION": ("Glass cannot shatter", "Window glass needs Use Physics and a collision to break.",
                                 "Give the window bone a collision and turn on Use Physics. If there is no window model yet, model the pane first.",
                                 "Turns Use Physics on, or builds a glass collision from the window model."),
    "HV040_GLASS_NO_SHADER": ("Window does not use a glass shader", "Nothing on it uses vehicle_vehglass, so it will not draw like glass.",
                              "Give the window a vehicle_vehglass material (Sollumz material panel).",
                              "Gives it vehicle_vehglass copies of its materials (listed but unticked: it changes the look)."),
    "HV062_GLASS_ORDER": ("Inner glass is drawn after outer glass", "Transparent materials draw in shader order, so the inner pane can hide behind the outer one.",
                          "Materials > Material Order: move vehicle_vehglass_inner above vehicle_vehglass.", "Writes that order."),
    "HV063_SHADER_ORDER": ("Shader order differs from vanilla", "There is no sorting rule for shaders, but "
                           "every vanilla vehicle that has both shaders puts them in the same order (for example shutters before lights before the outer glass). "
                           "Whether the game needs it is not established.",
                           "Materials > Material Order > Sort Like Vanilla, then Preview Order and Apply.",
                           "Sorts the shaders by where vanilla vehicles usually put them (ties keep their order) and writes that order."),
    # --- other bone rules
    "HV060_NODE_COUNT": ("Many bones", "Some guides cite a 128-bone limit; it is unconfirmed.",
                         "Usually nothing to do.", None),
    "HV080_SIREN_GAP": ("Siren numbers skip a value", "Sirens are numbered siren1, siren2 ... without gaps in vanilla.",
                        "Renumber the sirens or add the missing one.", None),
    "HV080_SIREN_GLASS_ORPHAN": ("siren_glass without its siren", "Each siren_glassN belongs with a sirenN.",
                                 "Add the matching siren bone or remove the glass bone.", None),
    "HV090_ROTOR_AXIS": ("Rotor spin axis is not square to its blades", "The rotor spins on its local Z, so the blades wobble instead of spinning flat.",
                         "Hierarchy > Local Axes > Align Spin Axis to Geometry.", "Aligns the axis to the blade disc; nothing moves."),
    # --- export limits
    "CLOTH_MATERIALS": ("Cloth mesh has more than one material", "A mesh with a cloth shader must have exactly that one material, or it is not treated as cloth.",
                        "Give the mesh a single cloth material and move any other polygons to a separate model.", None),
    "CLOTH_VERTS": ("Cloth mesh has too many vertices", "A cloth control mesh cannot exceed 255 vertices.",
                    "Reduce the cloth mesh (Decimate or dissolve edges) to 255 vertices or fewer.", None),
    "FEW_LODS": ("The vehicle has fewer than 4 LODs", "Vehicles normally carry four LOD meshes; with fewer, the lower detail levels are missing.",
                 "Generate LODs fills the missing slots from the highest one.", None),
    # --- materials
    "MAT_INDEX_TIES": ("Materials share a shader index", "Ties are broken by object name, so renaming or adding meshes silently reorders the shaders.",
                       "Materials > Material Order > Preview Order.", "Writes the current order into the shader indices."),
    "HI_ORDER_DIFFERS": ("The _hi materials are in a different order", "Both are normally exported from one material list, so their order agrees.",
                         "Materials > Material Order > Preview Order.", "Writes the current order into the shader indices."),
    "HI_ONLY_MATERIAL": ("Material used only by the _hi model", "Fine unless it was meant for the base models too.", "Usually nothing to do.", None),
    "HI_MATERIAL_SET_DIFFERS": ("_hi and base use different materials", "Both are normally exported from one material list.", "Usually nothing to do.", None),
    "LOW_LOD_ONLY": ("Material used only by low LODs", "The high LOD does not use it.", "Usually nothing to do.", None),
    "NON_SOLLUMZ_SLOT": ("Slot holds a material that is not a Sollumz shader", "Its polygons export without a shader.",
                         "Replace it with a Sollumz shader material (Sollumz material panel).", None),
    "DUPLICATE_MATERIALS": ("Materials that are the same", "Each one becomes its own entry in the shader group.",
                            "Point every slot at one of them.", "Merges them into the first; polygon indices do not change."),
    "EMPTY_TEXTURE_SAMPLER": ("Sampler has no texture", "The export names no texture for it.",
                              "Assign a texture in the Sollumz shader panel, or Materials > Default Textures.",
                              "Fills the samplers vanilla vehicles give a generic texture."),
    "MISSING_UV_MAP": ("Mesh lacks a UV map its shader uses", "The shader samples a map that does not exist, so the part renders wrong.",
                       "Object Data > UV Maps: add the map with the name in the message.", None),
    "MISSING_COLOR_ATTR": ("Mesh lacks a colour attribute its shader uses", "The shader reads vertex colours that do not exist.",
                           "Object Data > Color Attributes: add the attribute with the name in the message.", None),
    "MODEL_ORDER_BY_NAME": ("Models share a sort key", "Sollumz exports them in object-name order, so renaming one reorders the export.",
                            "Usually nothing to do. Rename objects if the export order matters.", None),
}


def get(code):
    """(title, why, how, quick) for a code; a code with no entry reads as its own name."""
    return CATALOG.get(code) or (code.replace("_", " ").capitalize(), "", "", None)
