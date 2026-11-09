"""Our own node embedding in the competition's shape: a float32 vector of length 256 per node.

The competition's embedding model is unknown, so this is a deterministic signed feature hash of
identifier sub-words and character 3-grams, L2-normalised. Identical text gives an identical
vector, and texts that share identifiers are close. Stdlib only: the `.npz` is written by hand
(a zip of `.npy` files), so numpy is not needed to build a bundle.
"""

from __future__ import annotations

import functools
import hashlib
import math
import re
import struct
import zipfile
from pathlib import Path

DIM = 256
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _features(text: str) -> list[str]:
    feats: list[str] = []
    for word in WORD.findall(text):
        parts = [p.lower() for p in CAMEL.findall(word)] or [word.lower()]
        feats += [f"w:{p}" for p in parts]
        low = word.lower()
        feats += [f"g:{low[i : i + 3]}" for i in range(max(len(low) - 2, 0))]
    return feats


def embed_text(text: str) -> list[float]:
    return list(_embed(text))


@functools.lru_cache(maxsize=200_000)
def _embed(text: str) -> tuple[float, ...]:
    vec = [0.0] * DIM
    for feat in _features(text):
        h = hashlib.blake2b(feat.encode(), digest_size=4).digest()
        n = int.from_bytes(h, "little")
        vec[n % DIM] += 1.0 if (n >> 31) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return tuple(x / norm for x in vec) if norm else tuple(vec)


def _npy(values: list[float]) -> bytes:
    """A version-1.0 .npy file holding one little-endian float32 vector."""
    header = f"{{'descr': '<f4', 'fortran_order': False, 'shape': ({len(values)},), }}"
    pad = (64 - (10 + len(header) + 1) % 64) % 64
    header = header + " " * pad + "\n"
    return (
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header.encode("latin1")
        + (struct.pack(f"<{len(values)}f", *values))
    )


def write_npz(path: Path, arrays: dict[str, list[float]]) -> None:
    """One array per key, in key order, so the same input gives the same bytes."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for key in sorted(arrays):
            info = zipfile.ZipInfo(f"{key}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            z.writestr(info, _npy(arrays[key]))
