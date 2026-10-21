"""ctypes wrapper for the parts of meshoptimizer (zeux/meshoptimizer, MIT) the LOD generator uses. The library is `lib/meshoptimizer.dll`
(Windows x64, built from the upstream sources with `zig c++`); everything here returns None / raises Unavailable when it cannot be loaded, so
the rest of the add-on works without it.

Data is numpy: positions (n, 3) float32, attributes (n, k) float32, indices (m,) uint32.
"""
import ctypes
import os

import numpy as np

LIB = os.path.join(os.path.dirname(__file__), "lib", "meshoptimizer.dll")

# meshopt_SimplifyOptions
LOCK_BORDER, SPARSE, ERROR_ABSOLUTE, PRUNE, REGULARIZE, PERMISSIVE = 1, 2, 4, 8, 16, 32
# meshopt_SimplifyVertex_*
V_LOCK, V_PROTECT, V_PRIORITY = 1, 2, 4

_lib = None


class Unavailable(RuntimeError):
    pass


def lib():
    global _lib
    if _lib is None:
        try:
            _lib = ctypes.CDLL(LIB)
        except OSError as e:
            raise Unavailable(f"meshoptimizer is not available: {e}")
        _lib.meshopt_generateVertexRemap.restype = ctypes.c_size_t
        _lib.meshopt_simplifyWithAttributes.restype = ctypes.c_size_t
        _lib.meshopt_simplifyWithUpdate.restype = ctypes.c_size_t
        _lib.meshopt_simplifyScale.restype = ctypes.c_float
    return _lib


def available():
    try:
        lib()
        return True
    except Unavailable:
        return False


def _p(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def weld(vertices):
    """Merge identical rows of `vertices` (n, k) float32. Returns (remap (n,) uint32 giving each row's unique id, unique_rows (u, k))."""
    v = np.ascontiguousarray(vertices, dtype=np.float32)
    n = len(v)
    remap = np.empty(n, dtype=np.uint32)
    u = lib().meshopt_generateVertexRemap(_p(remap), None, ctypes.c_size_t(n), _p(v), ctypes.c_size_t(n), ctypes.c_size_t(v.strides[0]))
    first = np.empty(u, dtype=np.int64)
    first[remap[::-1]] = np.arange(n - 1, -1, -1)  # first occurrence of each unique id
    return remap, v[first]


def weld_index(vertices):
    """Like weld(), but returns (remap, first): remap gives each row's unique id, first the index of the first row that has each unique id."""
    v = np.ascontiguousarray(vertices, dtype=np.float32)
    n = len(v)
    remap = np.empty(n, dtype=np.uint32)
    u = lib().meshopt_generateVertexRemap(_p(remap), None, ctypes.c_size_t(n), _p(v), ctypes.c_size_t(n), ctypes.c_size_t(v.strides[0]))
    first = np.empty(u, dtype=np.int64)
    first[remap[::-1]] = np.arange(n - 1, -1, -1)
    return remap, first


def scale(positions):
    p = np.ascontiguousarray(positions, dtype=np.float32)
    return lib().meshopt_simplifyScale(_p(p), ctypes.c_size_t(len(p)), ctypes.c_size_t(p.strides[0]))


def simplify(indices, positions, attributes=None, weights=None, locks=None, target_count=0, target_error=1.0, options=0):
    """meshopt_simplifyWithAttributes. Returns (new_indices uint32, error). target_count is an index count (3 x triangles); target_error is
    relative to the mesh extent (1e-2 is about 1%) unless ERROR_ABSOLUTE is set."""
    idx = np.ascontiguousarray(indices, dtype=np.uint32)
    pos = np.ascontiguousarray(positions, dtype=np.float32)
    out = np.empty(len(idx), dtype=np.uint32)
    err = ctypes.c_float(0.0)
    if attributes is not None and weights is not None and len(weights):
        att = np.ascontiguousarray(attributes, dtype=np.float32)
        w = np.ascontiguousarray(weights, dtype=np.float32)
        att_p, att_s, w_p, k = _p(att), att.strides[0], _p(w), len(w)
    else:
        att_p, att_s, w_p, k = None, 0, None, 0
    lock = np.ascontiguousarray(locks, dtype=np.uint8) if locks is not None else None
    n = lib().meshopt_simplifyWithAttributes(
        _p(out), _p(idx), ctypes.c_size_t(len(idx)), _p(pos), ctypes.c_size_t(len(pos)), ctypes.c_size_t(pos.strides[0]),
        att_p, ctypes.c_size_t(att_s), w_p, ctypes.c_size_t(k), _p(lock) if lock is not None else None,
        ctypes.c_size_t(target_count), ctypes.c_float(target_error), ctypes.c_uint(options), ctypes.byref(err))
    return out[:n].copy(), err.value


def simplify_update(indices, positions, attributes=None, weights=None, locks=None, target_count=0, target_error=1.0, options=0):
    """meshopt_simplifyWithUpdate: like simplify(), but also moves the surviving vertices (and updates their attributes) for a better fit. The caller's
    arrays are not modified. Returns (new_indices, positions, attributes, error); vertices no longer used are still in the arrays."""
    idx = np.ascontiguousarray(indices, dtype=np.uint32).copy()
    pos = np.ascontiguousarray(positions, dtype=np.float32).copy()
    err = ctypes.c_float(0.0)
    if attributes is not None and weights is not None and len(weights):
        att = np.ascontiguousarray(attributes, dtype=np.float32).copy()
        w = np.ascontiguousarray(weights, dtype=np.float32)
        att_p, att_s, w_p, k = _p(att), att.strides[0], _p(w), len(w)
    else:
        att, att_p, att_s, w_p, k = None, None, 0, None, 0
    lock = np.ascontiguousarray(locks, dtype=np.uint8) if locks is not None else None
    n = lib().meshopt_simplifyWithUpdate(
        _p(idx), ctypes.c_size_t(len(idx)), _p(pos), ctypes.c_size_t(len(pos)), ctypes.c_size_t(pos.strides[0]),
        att_p, ctypes.c_size_t(att_s), w_p, ctypes.c_size_t(k), _p(lock) if lock is not None else None,
        ctypes.c_size_t(target_count), ctypes.c_float(target_error), ctypes.c_uint(options), ctypes.byref(err))
    return idx[:n].copy(), pos, att, err.value
