"""The add-on's own header icons (icons/*.png, 32x32), loaded as previews. Every user falls back to a built-in icon if one is missing."""
import os

import bpy
import bpy.utils.previews

_collection = None


def register():
    global _collection
    _collection = bpy.utils.previews.new()
    folder = os.path.join(os.path.dirname(__file__), "icons")
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            if f.endswith(".png"):
                _collection.load(f[:-4], os.path.join(folder, f), "IMAGE")


def unregister():
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
        _collection = None


def value(name):
    return _collection[name].icon_id if _collection is not None and name in _collection else 0
