import zipfile

import pytest

from pod.layout_probe import npy_header
from synthetic.embed import embed_text, write_npz


def dot(x, y):
    return sum(p * q for p, q in zip(x, y, strict=True))


def test_vector_is_256_long_unit_length_and_deterministic():
    v = embed_text("def parse_header(line):\n    return line.split(':')")
    assert len(v) == 256
    assert abs(dot(v, v) - 1.0) < 1e-6
    assert v == embed_text("def parse_header(line):\n    return line.split(':')")


def test_related_text_is_closer_than_unrelated_text():
    a = embed_text("def parse_header(line): return line.split(':')")
    b = embed_text("def parse_headers(lines): return [x.split(':') for x in lines]")
    c = embed_text("class Renderer: def draw_table(self, rows): pass")
    assert dot(a, b) > dot(a, c)


def test_empty_text_gives_a_zero_vector_not_a_crash():
    assert embed_text("") == [0.0] * 256


def test_npz_holds_one_float32_256_array_per_node_keyed_by_id(tmp_path):
    p = tmp_path / "e.npz"
    write_npz(p, {"pkg.mod.f": embed_text("def f(): pass"), "pkg.mod.C.m": embed_text("x")})
    with zipfile.ZipFile(p) as z:
        assert sorted(z.namelist()) == ["pkg.mod.C.m.npy", "pkg.mod.f.npy"]
        h = npy_header(z.read("pkg.mod.f.npy")[:512])
    assert h["descr"] == "<f4" and tuple(h["shape"]) == (256,)


def test_npz_is_readable_by_numpy(tmp_path):
    np = pytest.importorskip("numpy")
    p = tmp_path / "e.npz"
    v = embed_text("def f(): pass")
    write_npz(p, {"a.b": v})
    z = np.load(p)
    assert z["a.b"].dtype == np.float32 and z["a.b"].shape == (256,)
    assert abs(float(z["a.b"][0]) - v[0]) < 1e-6
