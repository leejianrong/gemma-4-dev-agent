"""EDA 3: the embedding space, what the code graph is made of, and the duplicate vectors.

Sources: emb_nn.csv (kNN agreement), emb_sample.csv.gz (16 random nodes per graph with raw vectors),
emb_dups.csv (identical-vector groups). Two figures: the space itself, and the duplicates plus the
composition of the graphs.

Node classes come from the top-level name of the dotted node id: the repo's own package is
"library", `tests` is "tests", everything else (docs tutorials, scripts, examples) is "other".
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME_SPACE = "eda_03_embedding_space"
NAME_DUPS = "eda_03b_embedding_duplicates"
THRESHOLDS = [0.9999, 0.999, 0.99, 0.95]
VEC_COLS = [f"v{i}" for i in range(256)]
PACKAGE = {
    "fastapi/fastapi": "fastapi",
    "Textualize/rich": "rich",
    "psf/requests": "requests",
    "encode/httpx": "httpx",
}
CLASSES = ["library", "tests", "other"]
CLASS_LABELS = {
    "library": "library code",
    "tests": "tests",
    "other": "docs tutorials, scripts, examples",
}
CLASS_COLORS = {
    "library": style.PALETTE["blue"],
    "tests": style.PALETTE["vermillion"],
    "other": style.PALETTE["sky"],
}


def node_class(repo: str, node_id: str) -> str:
    top = node_id.split(".")[0]
    if top == PACKAGE.get(repo, ""):
        return "library"
    return "tests" if top == "tests" else "other"


def classify(sample: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [node_class(r, n) for r, n in zip(sample["repo"], sample["node_id"], strict=True)],
        index=sample.index,
    )


def composition(sample: pd.DataFrame, cls: pd.Series) -> pd.DataFrame:
    """Share (0-100) of sampled nodes per repo in each class."""
    rows = {}
    for repo in [r for r in style.REPO_ORDER if r in set(sample["repo"])]:
        m = (sample["repo"] == repo).to_numpy()
        rows[repo] = [100 * float((cls[m] == c).mean()) for c in CLASSES]
    return pd.DataFrame(rows, index=CLASSES).T


def knn_numbers(nn: pd.DataFrame) -> dict:
    def block(df):
        b = {
            "queries": len(df),
            "hits_1hop": float(df["hits_1hop"].mean()),
            "chance_1hop": float(df["expected_1hop"].mean()),
            "hits_same_parent": float(df["hits_same_parent"].mean()),
            "chance_same_parent": float(df["expected_same_parent"].mean()),
        }
        b["ratio_1hop"] = b["hits_1hop"] / b["chance_1hop"] if b["chance_1hop"] else float("nan")
        b["ratio_same_parent"] = (
            b["hits_same_parent"] / b["chance_same_parent"]
            if b["chance_same_parent"]
            else float("nan")
        )
        return b

    out = {"all": block(nn), "edited": block(nn[nn["is_edited"] == 1])}
    out["top1_cos_share_at_least"] = {
        str(t): float((nn["top1_cos"] >= t).mean()) for t in THRESHOLDS
    }
    return out


def pair_cosines(
    v: np.ndarray, n_pairs: int = 200_000, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Cosine of random distinct pairs, raw and after subtracting the mean vector."""
    rng = np.random.default_rng(seed)
    i, j = rng.integers(0, len(v), n_pairs), rng.integers(0, len(v), n_pairs)
    keep = i != j

    def cos(m):
        u = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        return (u[i] * u[j]).sum(1)[keep]

    return cos(v), cos(v - v.mean(0))


def pca(v: np.ndarray):
    c = v - v.mean(0)
    u, s, _ = np.linalg.svd(c, full_matrices=False)
    ev = s**2 / (s**2).sum()
    return u[:, :2] * s[:2], ev


def space_numbers(nn, v, raw, centred, ev, cls) -> dict:
    return {
        "knn": knn_numbers(nn),
        "sample_vectors": len(v),
        "random_pair_cosine_raw_mean": float(raw.mean()),
        "random_pair_cosine_raw_median": float(np.median(raw)),
        "random_pair_cosine_centred_mean": float(centred.mean()),
        "pca_var_pc1": float(ev[0]),
        "pca_var_pc2": float(ev[1]),
        "pcs_for_90pct_variance": int(np.searchsorted(np.cumsum(ev), 0.9) + 1),
        "vector_dim": int(v.shape[1]),
        "sample_share_by_class": {c: float((cls == c).mean()) for c in CLASSES},
    }


def draw_space(nn, v, raw, centred, xy, ev, cls):
    fig, ax = plt.subplots(2, 2, figsize=(style.FIG_WIDTH, 5.8))
    kn = knn_numbers(nn)

    a = ax[0, 0]  # agreement with the call graph vs chance
    labels = ["1-hop caller\nor callee", "same parent\n(class or module)"]
    sets = (
        (-0.26, [kn["all"]["chance_1hop"], kn["all"]["chance_same_parent"]], "chance", "grey"),
        (0.0, [kn["all"]["hits_1hop"], kn["all"]["hits_same_parent"]], "all nodes", "blue"),
        (
            0.26,
            [kn["edited"]["hits_1hop"], kn["edited"]["hits_same_parent"]],
            "edited nodes",
            "orange",
        ),
    )
    x = np.arange(2)
    for off, vals, name, col in sets:
        bars = a.bar(x + off, vals, 0.26, label=name, color=style.PALETTE[col])
        a.bar_label(bars, labels=[f"{q:.2f}" for q in vals], fontsize=7, padding=1)
    a.set_xticks(x, labels)
    a.set(title="Top-10 neighbours that are related", ylabel="of 10 neighbours (log)", yscale="log")
    a.set_ylim(top=a.get_ylim()[1] * 2.2)
    a.legend(fontsize=7, loc="upper right", ncol=3)

    b = ax[0, 1]  # how tight the nearest neighbour is
    shares = [100 * kn["top1_cos_share_at_least"][str(t)] for t in THRESHOLDS]
    bars = b.bar([f"≥ {t}" for t in THRESHOLDS], shares, color=style.PALETTE["blue"])
    b.bar_label(bars, labels=[f"{s:.0f}%" for s in shares], padding=2, fontsize=8)
    b.set(title="Cosine to the nearest neighbour", xlabel="top-1 cosine", ylabel="% of queries")
    b.set_ylim(0, 112)

    c = ax[1, 0]  # everything looks alike
    bins = np.linspace(-0.6, 1.0, 60)
    c.hist(
        raw,
        bins=bins,
        color=style.PALETTE["vermillion"],
        alpha=0.75,
        label=f"raw (mean {raw.mean():.2f})",
    )
    c.hist(
        centred,
        bins=bins,
        color=style.PALETTE["blue"],
        alpha=0.75,
        label=f"mean-centred (mean {centred.mean():.2f})",
    )
    c.set(title="Cosine between random node pairs", xlabel="cosine", ylabel="pairs")
    c.legend(fontsize=7, loc="upper left")

    d = ax[1, 1]  # PCA of the sample, by what kind of code the node is
    for k in CLASSES:
        m = (cls == k).to_numpy()
        if m.any():
            d.scatter(
                xy[m, 0],
                xy[m, 1],
                s=7,
                alpha=0.55,
                linewidths=0,
                color=CLASS_COLORS[k],
                label=f"{CLASS_LABELS[k]} ({int(m.sum())})",
            )
    d.set(
        title="First two principal components",
        xlabel=f"PC1 ({100 * ev[0]:.0f}% of variance)",
        ylabel=f"PC2 ({100 * ev[1]:.0f}%)",
    )
    d.legend(fontsize=7, markerscale=2, loc="upper left")
    n90 = int(np.searchsorted(np.cumsum(ev), 0.9) + 1)
    d.text(
        0.03,
        0.68,
        f"{n90} components carry 90%\nof the variance (of {v.shape[1]})",
        transform=d.transAxes,
        fontsize=8,
        color=style.PALETTE["grey"],
        ha="left",
    )
    return fig


def dup_numbers(dups: pd.DataFrame) -> dict:
    n = int(dups["n_nodes"].sum())
    dn = int(dups["nodes_in_duplicate_groups"].sum())
    g = int(dups["duplicate_groups"].sum())
    return {
        "graphs": len(dups),
        "nodes": n,
        "nodes_in_duplicate_groups": dn,
        "share_nodes_in_duplicate_groups": dn / n if n else 0.0,
        "duplicate_groups": g,
        "share_groups_identical_text": float(dups["groups_identical_text"].sum() / g) if g else 0.0,
        "groups_unrelated": int(dups["groups_unrelated"].sum()),
        "groups_siblings": int(dups["groups_siblings"].sum()),
        "groups_parent_child": int(dups["groups_parent_child"].sum()),
        "largest_group": int(dups["largest_group"].max()),
        "unique_vectors": int(dups["unique_vectors"].sum()),
    }


def draw_dups(dups: pd.DataFrame, comp: pd.DataFrame):
    fig, ax = plt.subplots(1, 3, figsize=(style.FIG_WIDTH + 2.4, 3.4))
    nums = dup_numbers(dups)
    dups = dups.assign(share=100 * dups["nodes_in_duplicate_groups"] / dups["n_nodes"])

    a = ax[0]  # share of nodes per graph, by repo
    repos = [r for r in style.REPO_ORDER if r in set(dups["repo"])]
    for i, r in enumerate(repos):
        s = dups.loc[dups["repo"] == r, "share"]
        jitter = np.random.default_rng(i).uniform(-0.18, 0.18, len(s))
        a.scatter(
            np.full(len(s), i) + jitter,
            s,
            s=10,
            alpha=0.6,
            color=style.REPO_COLORS[r],
            linewidths=0,
        )
        a.hlines(s.median(), i - 0.3, i + 0.3, color=style.PALETTE["black"], lw=1.5)
    a.set_xticks(range(len(repos)), [style.short(r) for r in repos])
    a.set(title="Nodes sharing a vector", ylabel="% of a graph's nodes", ylim=(0, None))

    b = ax[1]  # what the groups are
    g = nums["duplicate_groups"]
    ident = nums["share_groups_identical_text"] * 100
    rows = [
        ("identical text", ident),
        ("different text", 100 - ident),
        ("unrelated nodes", 100 * nums["groups_unrelated"] / g),
        ("siblings", 100 * nums["groups_siblings"] / g),
        ("parent and child", 100 * nums["groups_parent_child"] / g),
    ]
    cols = [
        style.PALETTE["blue"],
        style.PALETTE["vermillion"],
        style.PALETTE["blue"],
        style.PALETTE["sky"],
        style.PALETTE["sky"],
    ]
    bars = b.barh([r for r, _ in rows], [v for _, v in rows], color=cols)
    b.bar_label(bars, labels=[f"{v:.1f}%" for _, v in rows], padding=2, fontsize=8)
    b.invert_yaxis()
    b.set(title=f"What the {g:,} groups are", xlabel="% of groups", xlim=(0, 118))

    c = ax[2]  # what the graph is made of
    left = np.zeros(len(comp))
    for k in CLASSES:
        c.barh(
            [style.short(r) for r in comp.index],
            comp[k],
            left=left,
            color=CLASS_COLORS[k],
            label=CLASS_LABELS[k],
        )
        left += comp[k].to_numpy()
    c.invert_yaxis()
    c.set(title="What the code graph is made of", xlabel="% of sampled nodes", xlim=(0, 100))
    c.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=1)
    return fig


def build() -> list[Path]:
    nn = data.load("emb_nn.csv")
    sample = data.load("emb_sample.csv.gz")
    dups = data.load("emb_dups.csv")
    v = sample[VEC_COLS].to_numpy(dtype=np.float32)
    cls = classify(sample)
    comp = composition(sample, cls)
    raw, centred = pair_cosines(v)
    xy, ev = pca(v)
    n1 = space_numbers(nn, v, raw, centred, ev, cls)
    kn = n1["knn"]
    hits, chance = kn["all"]["hits_1hop"], kn["all"]["chance_1hop"]
    cap1 = (
        "Embeddings follow the call graph: a node's top-10 neighbours include "
        f"{hits:.2f} callers or callees against {chance:.2f} by chance. But random node pairs "
        f"already have cosine {n1['random_pair_cosine_raw_mean']:.2f}, and "
        f"{n1['pcs_for_90pct_variance']} of {n1['vector_dim']} dimensions carry 90% of the "
        "variance. Test functions form their own region."
    )
    n2 = dup_numbers(dups)
    n2["composition_pct_by_repo"] = {
        style.short(r): {c: round(float(comp.loc[r, c]), 1) for c in CLASSES} for r in comp.index
    }
    share_dup = 100 * n2["share_nodes_in_duplicate_groups"]
    share_text = 100 * n2["share_groups_identical_text"]
    cap2 = (
        f"{share_dup:.0f}% of nodes share an identical vector with another node; "
        f"{share_text:.1f}% of those groups have identical source text, so the vector is a "
        "function of the text. Library code is a minority of the graph in fastapi and requests."
    )
    return [
        style.save(
            draw_space(nn, v, raw, centred, xy, ev, cls),
            NAME_SPACE,
            ["emb_nn.csv", "emb_sample.csv.gz"],
            n1,
            cap1,
        ),
        style.save(
            draw_dups(dups, comp), NAME_DUPS, ["emb_dups.csv", "emb_sample.csv.gz"], n2, cap2
        ),
    ]
