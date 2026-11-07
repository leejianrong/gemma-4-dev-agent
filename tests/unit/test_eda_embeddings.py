import json

import pytest

pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from analysis import eda_embeddings as ee  # noqa: E402


def write_tables(tmp_path):
    rng = np.random.default_rng(0)
    nn = pd.DataFrame(
        {
            "repo": ["fastapi/fastapi"] * 6 + ["Textualize/rich"] * 4,
            "kind": ["function_like"] * 10,
            "is_edited": [1, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            "hits_1hop": [2, 0, 1, 0, 0, 1, 3, 0, 0, 1],
            "expected_1hop": [0.1] * 10,
            "hits_same_parent": [4, 2, 1, 3, 0, 2, 5, 1, 2, 0],
            "expected_same_parent": [0.3] * 10,
            "top1_cos": [1.0, 0.9999, 0.995, 0.97, 1.0, 0.99, 0.9, 1.0, 1.0, 0.999],
        }
    )
    nn.to_csv(tmp_path / "emb_nn.csv", index=False)
    base = rng.normal(size=(1, 256)) * 3  # a big shared offset, as in the real data
    vecs = base + rng.normal(size=(80, 256)) * 0.5
    meta = pd.DataFrame(
        {
            "stem": "s",
            "repo": ["fastapi/fastapi"] * 50 + ["Textualize/rich"] * 30,
            "node_id": (
                [f"fastapi.m.f{i}" for i in range(10)]
                + [f"tests.test_a.f{i}" for i in range(30)]
                + [f"docs_tutorial.t{i}.Item" for i in range(10)]
                + [f"rich.m.f{i}" for i in range(15)]
                + [f"tests.test_b.f{i}" for i in range(15)]
            ),
            "kind": "function_like",
            "module2": "p.m",
        }
    )
    sample = pd.concat([meta, pd.DataFrame(vecs, columns=ee.VEC_COLS)], axis=1)
    sample.to_csv(tmp_path / "emb_sample.csv.gz", index=False)
    dups = pd.DataFrame(
        {
            "stem": ["a", "b"],
            "repo": ["fastapi/fastapi", "Textualize/rich"],
            "n_nodes": [100, 50],
            "unique_vectors": [80, 45],
            "nodes_in_duplicate_groups": [30, 8],
            "duplicate_groups": [10, 3],
            "largest_group": [8, 3],
            "groups_identical_text": [10, 3],
            "groups_parent_child": [0, 0],
            "groups_siblings": [1, 0],
            "groups_unrelated": [9, 3],
        }
    )
    dups.to_csv(tmp_path / "emb_dups.csv", index=False)
    ex = pd.DataFrame(
        {
            "stem": ["a", "b"],
            "repo": ["fastapi/fastapi", "Textualize/rich"],
            "group_size": [8, 3],
            "relation": ["unrelated", "siblings"],
            "identical_text": [1, 1],
            "node_ids": ["t.a.Item;t.b.Item;t.c.Item", "r.x.f;r.x.g"],
        }
    )
    ex.to_csv(tmp_path / "emb_dup_examples.csv", index=False)


def test_pair_cosines_show_a_shared_offset_that_centering_removes():
    rng = np.random.default_rng(1)
    v = rng.normal(size=(200, 64)) * 0.3 + 5.0
    raw, centred = ee.pair_cosines(v, n_pairs=5000)
    assert raw.mean() > 0.9 and abs(centred.mean()) < 0.1


def test_node_class_uses_the_top_level_name_and_the_repos_own_package():
    assert ee.node_class("fastapi/fastapi", "fastapi.routing.APIRouter") == "library"
    assert ee.node_class("fastapi/fastapi", "tests.test_x.test_y") == "tests"
    assert ee.node_class("fastapi/fastapi", "sql_databases.app.main.read") == "other"
    assert ee.node_class("psf/requests", "requests.sessions.Session") == "library"
    assert (
        ee.node_class("psf/requests", "fastapi.x") == "other"
    )  # another repo's package is not ours


def test_composition_sums_to_100_per_repo(tmp_path):
    write_tables(tmp_path)
    sample = pd.read_csv(tmp_path / "emb_sample.csv.gz")
    comp = ee.composition(sample, ee.classify(sample))
    assert (comp.sum(axis=1).round(6) == 100).all()
    assert comp.loc["fastapi/fastapi", "tests"] == pytest.approx(60.0)
    assert comp.loc["Textualize/rich", "library"] == pytest.approx(50.0)


def test_pca_returns_normalised_variances():
    v = np.random.default_rng(2).normal(size=(100, 20))
    xy, ev = ee.pca(v)
    assert xy.shape == (100, 2) and ev.sum() == pytest.approx(1.0) and ev[0] >= ev[1]


def test_knn_numbers_compare_with_chance_and_edited_subset(tmp_path):
    write_tables(tmp_path)
    kn = ee.knn_numbers(pd.read_csv(tmp_path / "emb_nn.csv"))
    assert kn["all"]["queries"] == 10 and kn["edited"]["queries"] == 2
    assert kn["all"]["ratio_1hop"] == pytest.approx(0.8 / 0.1)
    assert kn["top1_cos_share_at_least"]["0.9999"] == pytest.approx(0.5)


def test_build_writes_both_figures_with_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "figs"))
    write_tables(tmp_path)
    pngs = ee.build()
    assert [p.name for p in pngs] == [
        "eda_03_embedding_space.png",
        "eda_03b_embedding_duplicates.png",
    ]
    assert all(p.stat().st_size > 5000 for p in pngs)
    space = json.loads((tmp_path / "figs" / "eda_03_embedding_space.json").read_text())
    dups = json.loads((tmp_path / "figs" / "eda_03b_embedding_duplicates.json").read_text())
    assert space["numbers"]["random_pair_cosine_raw_mean"] > 0.9
    assert space["numbers"]["random_pair_cosine_centred_mean"] < 0.2
    assert (
        dups["numbers"]["nodes_in_duplicate_groups"] == 38 and dups["numbers"]["largest_group"] == 8
    )
    assert dups["numbers"]["composition_pct_by_repo"]["fastapi"]["tests"] == 60.0
    assert space["numbers"]["sample_share_by_class"]["tests"] == pytest.approx(45 / 80)
    assert dups["numbers"]["share_groups_identical_text"] == 1.0
