# CRCKTools tutorial

A step-by-step guide to the main tools. You need Blender 4.2+, Sollumz 2.9.x and a GTA V vehicle imported with Sollumz.

Contents: [1. Install](#1-install) · [2. Check the vehicle](#2-check-the-vehicle) · [3. Fix problems](#3-fix-problems) · [4. The part tree](#4-the-part-tree) · [5. Generate LODs](#5-generate-lods) · [6. Materials](#6-materials) · [7. Export Compact](#7-export-compact) · [8. Tips](#8-tips-and-troubleshooting)

## 1. Install

1. Download `CRCKTools-0.15.0.zip` from the [Releases](../../../releases) page.
2. In Blender: Edit > Preferences > Get Extensions > the arrow menu at the top right > **Install from Disk**. Pick the zip and enable it.
3. Make sure **Sollumz** is enabled too.
4. Restart Blender.

**Find the tools:** select the vehicle's Fragment (or any object inside it), press **N** in the 3D viewport and open the **CRCKTools** tab. Everything is in that one tab.

## 2. Check the vehicle

Press **Check Vehicle**. The line under the button counts errors and warnings, and the **Problems** list fills in.

Click a problem. The box underneath tells you:

- **What is wrong**, using your own bone and object names.
- **Why it matters.**
- **How to fix it** by hand.
- **Quick fix**, if the row has a wrench icon.

| Level | Meaning |
|---|---|
| Error | The export fails or the vehicle is broken in game |
| Warning | Probably wrong, worth fixing before export |
| Info | Worth knowing, often fine |

## 3. Fix problems

1. Click a problem that has a wrench.
2. Press **Preview This Fix**. The change appears in the preview box at the top of the tab. Nothing has changed yet.
3. Untick anything you do not want, then press **Apply Changes**.
4. Ctrl+Z undoes it.

**Preview All Quick Fixes** previews every quick fix at once. **Select** selects the bone or object a problem is about.

**Example: a wheel with no collision.** The game needs a physics group and a collision on every wheel bone. The quick fix copies another wheel's collision onto the bone, moves it into place and turns on Use Physics. If no wheel has a collision, it builds a disc from the wheel model instead.

## 4. The part tree

Open **Vehicle > Hierarchy** and press **Refresh Hierarchy**. You get one tree: the fragment at the top, then every part nested in bone order.

- A part with geometry shows the LOD slots it has (`L01` means L0 and L1).
- A part with a collision has a `[COL]` row.
- Click a row to select the part and everything under it.
- **L0-L4** show one LOD slot on every part. **COL** shows or hides collisions.
- The eye icons, Isolate, Show and Hide only change what you see in the viewport, not the export.

### Move a part

Blender can't drag list rows, so it takes two clicks:

1. Click the part and press **Grab Selected Row**.
2. Click the part you want to drop it on.
3. Choose **Into** (becomes its child), **Before** or **After** (becomes its sibling).

**Unlink from Parent** makes a part a top-level bone of its own. Ctrl+Z undoes each move. A part keeps its position, its geometry and its collision when it moves.

### Other part tools

- **Auto Arrange** (top of the tab) previews the moves that put parts where vanilla vehicles have them: bones under their usual parents, models and collisions on the bone they are named after. Review the preview, then Apply Changes.
- **Rename Part** (Parts and Bone Order) renames the bone, its models, collisions, mesh data and vertex groups together.
- **Local Axes** changes a bone's axes without moving anything you can see. **Align Spin Axis to Geometry** fixes a rotor that wobbles.
- **Bone order:** Up and Down move a bone among its siblings. The bone index follows.

## 5. Generate LODs

Open **Vehicle > Generate LODs**.

1. **Parts:** every part, or only the selected models.
2. **Start from:** L1 (high) or L0 (`_hi`). The panel shows how many parts have a mesh in each level, and warns when some have no mesh to start from.
3. The sliders are the share of triangles each level keeps. They switch to sensible defaults when you change the start level. Set one to 0 to leave that level empty.
4. Press **Generate LODs**.

What to know:

- It **never changes the start mesh** or anything above it.
- A level that already has a mesh is left alone, unless you tick **Replace existing**.
- Material order, UV maps, colour attributes, bone weights and shading are kept.
- Wheels, glass, lights and mirrors keep extra triangles. Change this with *Protect wheels, glass, lights, mirrors* in the Quality box.
- **Method:** Auto uses meshoptimizer where it is better and Blender's Decimate elsewhere.
- LOD switch distances are **not** set for you.
- Not tested in game yet. Check the result in game.

## 6. Materials

### Material order

Open **Materials > Material Order**. Press **Sort Like Vanilla**, check the preview, then **Apply Changes**. It orders the shaders the way vanilla vehicles do (paint first, tyres last). This is a pattern seen in 11 vehicles, not a proven game rule. You can also load the current order, move materials by hand, press **Preview Order** and apply.

### Paint layers

A colour variant is a material with another paint layer (Primary, Secondary, Pearlescent, Wheel and so on).

1. Select the faces (Edit mode) or the model (Object mode).
2. Make the body paint material the active slot.
3. Press a layer, for example **Secondary**, under *Paint the selection as*.

The variant is created once and reused. **Add Paint Material** makes a new one from a shader and layer. **Livery** turns the active paint material into a livery material.

### Other material tools

- **Default Textures** gives new materials the texture names vanilla vehicles use. **Fill Empty Textures** does the same for existing ones.
- **Usage and Textures** shows which materials the vehicle uses, by how many models and polygons. Select Users selects them, Replace Everywhere swaps one material for another on every LOD.

## 7. Export Compact

**File > Export > RAGE Asset, compact (.yft ...)**, or **CRCKTools > Export Info > Export Compact**. Pick an output folder.

It runs Sollumz's own exporter with your Sollumz export settings, with one change: vertices that differ only by tiny float noise in their normals are merged. The triangles stay the same. On one test vehicle the file came out 9% smaller than with Sollumz alone.

Select the vehicle's Fragment first. **Estimate Export Size** (same panel) shows a rough size from a trial export and warns at 256 MiB.

## 8. Tips and troubleshooting

- **The tab isn't there:** Sollumz must be enabled and a vehicle must be selected. Restart Blender after installing or updating.
- **A tool says "incompatible":** your Sollumz version differs from the one this was tested with (2.9.x).
- **Read the preview** before pressing Apply Changes. Ctrl+Z undoes it.
- **Bug or idea:** open an issue on GitHub with a screenshot of the Problems panel.
- **In game:** bone order, physics groups and shader order are tested and work. The other tools have not been tested in game yet, so check their results there.
