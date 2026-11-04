from __future__ import annotations

import numpy as np


def pack_array(values) -> bytes:
    array = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    return array.tobytes()


def unpack_array(blob) -> np.ndarray:
    if not blob:
        return np.array([], dtype=np.float64)
    return np.frombuffer(blob, dtype="<f8").copy()
