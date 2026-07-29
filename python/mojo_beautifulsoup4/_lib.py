from __future__ import annotations

import atexit
import ctypes
import os
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get(
    "MOJO_BEAUTIFULSOUP4_LIB",
    os.path.join(ROOT, "dist", "libmojo-beautifulsoup4.so"),
)
I = ctypes.c_int64


class BuildError(RuntimeError):
    pass


_lib: ctypes.CDLL | None = None
_parallel_device: int | None = None
_parallel_attempted = False
PREFILTER_PARALLEL_THRESHOLD = 131_072


def build(force: bool = False) -> str:
    source = os.path.join(ROOT, "src", "capi.mojo")
    stale = not os.path.exists(LIB) or os.path.getmtime(LIB) < os.path.getmtime(source)
    if force or stale:
        proc = subprocess.run(
            ["bash", os.path.join(ROOT, "build", "build.sh")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode or not os.path.exists(LIB):
            raise BuildError((proc.stderr or proc.stdout).strip())
    return LIB


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(build())
        _lib.mbs_tokenize.argtypes = [I] * 6
        _lib.mbs_tokenize.restype = I
        _lib.mbs_prefilter.argtypes = [I] * 17
        _lib.mbs_prefilter.restype = I
    return _lib


def addr(value: np.ndarray) -> int:
    address = int(value.ctypes.data)
    if not address:
        raise ValueError("cannot pass a null array pointer to Mojo")
    return address


def _int64_vector(value: np.ndarray, name: str, length: int | None = None) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise TypeError(f"{name} must be a NumPy array")
    if value.dtype != np.dtype(np.int64):
        raise TypeError(f"{name} must have dtype int64")
    if value.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not value.flags.c_contiguous or not value.flags.aligned:
        raise ValueError(f"{name} must be contiguous and aligned")
    if length is not None and len(value) != length:
        raise ValueError(f"{name} must contain {length} entries")
    return value


def _parallel_available() -> bool:
    global _parallel_attempted, _parallel_device
    if _parallel_attempted:
        return _parallel_device is not None
    _parallel_attempted = True
    try:
        runtime = lib()
        create = runtime.KGEN_CompilerRT_AsyncRT_GetOrCreateCPUDevice
        create.argtypes = []
        create.restype = ctypes.c_void_p
        device = create()
        if not device:
            return False
        _parallel_device = int(device)
        release = runtime.KGEN_CompilerRT_AsyncRT_ReleaseCPUDevice
        release.argtypes = [ctypes.c_void_p]
        release.restype = None
        atexit.register(release, ctypes.c_void_p(_parallel_device))
    except (AttributeError, OSError):
        return False
    return True


def tokenize(source: bytes):
    if not isinstance(source, bytes):
        raise TypeError("source must be bytes")
    data = np.frombuffer(source or b"\0", dtype=np.uint8)
    # Every emitted token consumes at least one source byte. Allocating one slot
    # per byte makes the output capacity an invariant, rather than checking only
    # after Mojo could already have written past a smaller heuristic allocation.
    capacity = max(1, len(source))
    fields = [np.empty(capacity, dtype=np.int64) for _ in range(4)]
    count = int(
        lib().mbs_tokenize(
            addr(data),
            len(source),
            *(addr(field) for field in fields),
        )
    )
    if count < 0 or count > capacity:
        raise RuntimeError(f"Mojo tokenizer returned invalid token count {count}")
    return tuple(field[:count] for field in fields)


def prefilter(
    blob: bytes,
    name_starts: np.ndarray,
    name_ends: np.ndarray,
    id_starts: np.ndarray,
    id_ends: np.ndarray,
    class_starts: np.ndarray,
    class_ends: np.ndarray,
    *,
    tag: str | None,
    element_id: str | None,
    classes: tuple[str, ...],
) -> np.ndarray:
    arrays = (
        name_starts,
        name_ends,
        id_starts,
        id_ends,
        class_starts,
        class_ends,
    )
    node_count = len(_int64_vector(name_starts, "name_starts"))
    names = (
        "name_ends",
        "id_starts",
        "id_ends",
        "class_starts",
        "class_ends",
    )
    for value, name in zip(arrays[1:], names):
        _int64_vector(value, name, node_count)
    blob_length = len(blob)
    for starts, ends, label in (
        (name_starts, name_ends, "name"),
        (id_starts, id_ends, "id"),
        (class_starts, class_ends, "class"),
    ):
        if np.any(starts < 0) or np.any(ends < starts) or np.any(ends > blob_length):
            raise ValueError(f"{label} offsets must satisfy 0 <= start <= end <= blob length")

    query = bytearray()
    tag_start = len(query)
    query.extend((tag or "").encode())
    tag_end = len(query)
    id_start = len(query)
    query.extend((element_id or "").encode())
    id_end = len(query)
    offsets = []
    for cls in classes:
        offsets.append(len(query))
        query.extend(cls.encode())
    offsets.append(len(query))
    query_array = np.frombuffer(query or b"\0", dtype=np.uint8)
    blob_array = np.frombuffer(blob or b"\0", dtype=np.uint8)
    offset_array = np.asarray(offsets or [0], dtype=np.int64)
    result = np.empty(node_count, dtype=np.uint8)
    matched = int(lib().mbs_prefilter(
        addr(blob_array),
        addr(name_starts),
        addr(name_ends),
        addr(id_starts),
        addr(id_ends),
        addr(class_starts),
        addr(class_ends),
        node_count,
        addr(query_array),
        tag_start,
        tag_end,
        id_start,
        id_end,
        addr(offset_array),
        len(classes),
        addr(result),
        int(
            node_count >= PREFILTER_PARALLEL_THRESHOLD
            and _parallel_available()
        ),
    ))
    if matched < 0 or matched > node_count:
        raise RuntimeError(f"Mojo prefilter returned invalid match count {matched}")
    return result
