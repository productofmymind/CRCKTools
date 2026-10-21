# CRCKTools

**CRCKTools** is a Blender add-on for GTA V vehicle modding. It sits **on top of [Sollumz](https://github.com/Sollumz/Sollumz)** and adds what a vehicle workflow is missing: a tree view of the vehicle's parts, one-click checks with fixes, whole-vehicle LOD generation, paint and material tools, and a smaller-file export. It replaces nothing Sollumz does.

**Version 0.15.0** · Blender 4.2+ (tested on 5.2.2) · Sollumz 2.9.x tested · GPL-3.0-or-later

## What it does, in short

| You want to... | CRCKTools gives you |
|---|---|
| See how a vehicle is built | A tree of parts: bones, the models bound to them, collisions and LOD slots, in one view |
| Find out what is wrong | **Check Vehicle**: each problem explained in plain words, with a fix you can preview and apply |
| Make LODs | **Generate LODs** for the whole vehicle at once, starting from L0 (`_hi`) or L1 |
| Paint and materials | Paint layers and liveries, default textures, material usage, material order |
| Ship a smaller file | **Export Compact**: Sollumz's own exporter with a vertex merge that makes files smaller |
| Fix a wobbling rotor, rename a part, rearrange bones | Local-axes tools, Rename Part, Auto Arrange |

New here? Read the step-by-step [tutorial](docs/TUTORIAL.md).

## Install

1. Download `CRCKTools-0.15.0.zip` from the [Releases](../../releases) page. (Or zip the *contents* of the `vehicle_hierarchy_tools` folder yourself, with `blender_manifest.toml` at the top level of the zip.)
2. Blender > Edit > Preferences > Get Extensions > the arrow menu > **Install from Disk**, pick the zip, and enable it. **Sollumz must be enabled too.**
3. Select the vehicle's Fragment (or any object inside it). Everything is in one tab of the 3D Viewport sidebar (press **N**): **CRCKTools**.
4. Restart Blender after updating the add-on.

`lib/meshoptimizer.dll` (MIT, Windows x64) powers Generate LODs. Without it, or on another platform, Blender's Decimate is used instead.

## Why it exists

A GTA V vehicle has no object tree. Its hierarchy is a **bone tree** plus the **objects bound to each bone**. Sollumz shows flat objects and a separate armature. CRCKTools works on the real structure and shows it as a tree of nested parts, so you can see and change how the vehicle is put together.

## Features

### See and fix the structure

| Tool | What it does |
|---|---|
| **Hierarchy** | One tree: fragment root, parts nested in bone order, `[COL]` rows, the LOD slots each part has. Select, expand, hide/isolate, show L0-L4 or COL, Move Up/Down, attach objects or bones to a part. **Grab and drop** moves a part or collision into another part, before/after a sibling, or unlinks it. Search filters rows. |
| **Auto Arrange** | One preview of the moves that put parts where vanilla vehicles have them: bones under their usual parents, models and collisions on the bone they are named after, nested models back under the Drawable, collisions into the Bound Composite. Nothing moves in space. |
| **Local Axes** | Center to Object, Reset to Parent/World, Copy From Grabbed, Origin to 3D Cursor (rotation and position switches) and **Align Spin Axis to Geometry**, all without moving geometry, children or collisions. Fixes rotor wobble. |
| **Parts and Bone Order** | Bind several objects to one bone, or several bones under one (preview, then Apply, one undo step). Move bones up/down among siblings. **Rename Part** renames bone, models, collisions, mesh data and vertex groups together, with find/replace. Part collections mirror the bone tree in the Outliner. |
| **Problems** | **Check Vehicle** lists each problem in plain words: what is wrong (with your names), why it matters, how to fix it by hand, and a previewable **quick fix** where one exists. 51 kinds explained, including **wheel bones without a collision** (the quick fix copies another wheel's collision, or builds a disc from the wheel model). Rules are data (`data/vehicle_rules.json`), graded by confidence, and silent on the vanilla vehicles tested. |
| **Export Info** | The order Sollumz will actually write, and a size estimate from a trial export (warns at 256 MiB). **Export Compact** (also under File > Export) runs Sollumz's exporter with your settings but merges vertices that differ only by float noise in their normals: a test vehicle re-exported 9% smaller than with Sollumz alone, with identical triangles. |

### Materials

| Tool | What it does |
|---|---|
| **Paint layers and liveries** | A colour variant is a material with another paint layer (Primary, Secondary, Pearlescent, Wheel, ...), as vanilla does it. Add paint materials from any paint shader, make livery materials. |
| **Default textures** | New materials get the texture names vanilla uses per shader and sampler; *Fill Empty Textures* does it for existing ones. |
| **Material Usage** | Which materials the vehicle uses, by how many models, polygons and LODs; Select Users; Replace Everywhere; texture report. |
| **Material Order** | Reorder the shader group. Writes Sollumz's own shader index. **Sort Like Vanilla** orders it the way vanilla vehicles do (paint first, inner glass, shutters, lights ... outer glass, interior, tyres last); a Problems entry offers it as a quick fix. A tendency learned from 11 vehicles, not a proven game rule. |

### Generate LODs

Fills the LOD slots below a start level you choose, **L0 (`_hi`) or L1**, for every part or the selected models.

- Works in Sollumz's own LOD slots: no loose objects, start meshes never touched, existing slots left alone unless *Replace existing* is on. Models with no start mesh are skipped with a reason.
- Keeps material list, order and borders, every UV map and colour attribute, bone weights and the original shading (hard edges stay hard). Thin materials survive every level.
- Wheels, glass, lights and mirrors keep extra triangles (default 1.5x).
- Reduction is attribute-aware ([meshoptimizer](https://github.com/zeux/meshoptimizer), with Blender's Decimate for strong reductions and as fallback). Defaults are the triangle shares 11 vanilla vehicles use.
- Tested on 11 vanilla vehicles in both modes, with export and re-import. LOD switch distances are not changed.

## How it works with Sollumz

- **Sollumz stays the foundation.** Import, export, shaders, collisions, physics and the data model are Sollumz's. CRCKTools never edits its files or replaces its importer or exporter.
- **It edits only data Sollumz already reads:** Sollumz's own bone constraint, `Material.shader_properties.index`, material slots, bone parents and order, LOD slots.
- **Checks use Sollumz's own functions**, so what is reported matches what the exporter does.
- **One file touches Sollumz internals:** `vehicle_hierarchy_tools/sollumz_bridge.py`. If a Sollumz update moves something, that is the only file to fix. A missing function shows "incompatible" in the panel instead of failing; other Sollumz versions show an "untested" note.
- **Nothing is changed silently.** Consequential edits are previewed, applied in one operator, and are one undo step. Read-only checks are tested not to modify anything.

## What Sollumz does not do (so CRCKTools does)

Verified against Sollumz 2.9.0's source and by experiment: show a vehicle as nested parts (models are flat siblings, and parenting one under an object makes the exporter drop it); bind objects to a chosen bone in bulk; reorder sibling bones; warn about name-ordered rigid models, `.001` bone names, tag mismatches, duplicate materials, empty samplers or missing UV maps and colour attributes across a vehicle; estimate export size; generate LODs for a whole vehicle at once.
Import/export, shader conversion, collision creation, mass, light IDs, cloth and texture dictionaries stay Sollumz's.

## Limits

- Generated LODs are judged by surface distance, normals and UVs against the start mesh, not rendered or run in game. Set LOD distances yourself.
- The size estimate is not checked against the resource header.
- Not run on Blender 4.2 yet; performance on very large vehicles is untested.

## Credits

This project builds on the work of others, and would not exist without it:

- **[Sollumz](https://github.com/Sollumz/Sollumz)** by the Sollumz team (GPL-3.0): the import and export of every GTA V asset type, the shader and collision data model, and LOD slots that
  CRCKTools works through. It reads Sollumz's source for compatibility and never modifies it. Sollumz in turn relies on its own file libraries for reading and writing the native files.
- **[meshoptimizer](https://github.com/zeux/meshoptimizer)** by Arseny Kapoulkine (MIT): the mesh simplifier behind Generate LODs. The bundled `lib/meshoptimizer.dll` is built from
  meshoptimizer 1.3; its licence is in `vehicle_hierarchy_tools/lib/meshoptimizer-LICENSE.md`.
- **[Blender](https://www.blender.org)** (GPL): the platform, the Decimate modifier used as the fallback reducer, and the BVH used to measure and transfer surfaces.
- **[Zig](https://ziglang.org)** (MIT): its C++ compiler built the DLL for Windows.
- **Published research** on mesh simplification: M. Garland and P. Heckbert, *Surface simplification using quadric error metrics* (SIGGRAPH 1997) and *Simplifying surfaces with color
  and texture using quadric error metrics* (1998); H. Hoppe, *New quadric metric for simplifying meshes with appearance attributes* (1999); P. Cignoni et al., *A general method for
  preserving attribute values on simplified meshes* (1998).
- **The GTA V modding community's** vehicle hierarchy references (bone names, parents, vehicle types), which the rule data started from and which were then checked against real vehicles.
- **Rockstar Games' vanilla vehicle files** were read only to measure what a vehicle normally looks like (parents, binding, shader order, textures, LOD shares). None are included in this repository.

GTA V is a trademark of Take-Two Interactive. This project is not affiliated with Rockstar Games, Take-Two or the Sollumz team.

## Thanks to Sollumz

CRCKTools only exists because of [Sollumz](https://github.com/Sollumz/Sollumz). It does the importing, exporting and the whole data model this add-on stands on, and without it GTA V modding in Blender would still be a pain. Thanks to the Sollumz team and its code contributors, and to dexyfex and the [CodeWalker](https://github.com/dexyfex/CodeWalker) contributors, whose work the wider modding scene builds on.

## Made with AI

This add-on was developed with AI. Most of the code, the tests and the documentation were written with Claude (by Anthropic), while the maintainer directed the work, tested it, and checked it in game. Read the code before you trust it with your files, and report problems in the Issues tab.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). The bundled meshoptimizer library is MIT licensed (see its licence file above).
