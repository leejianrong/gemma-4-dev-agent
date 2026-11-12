"""Write mutation records as a competition-shaped bundle (stage 1: localization only).

    out/tasks.jsonl                       one task per line, the 8 string fields of A36
    out/graphs/<repo>_<base_commit>.json  call graph of the buggy tree
    out/embeddings/<repo>_<base_commit>.npz
    out/gold_nodes.csv                    instance_id -> gold node (for scoring only)

`base_commit` is a synthetic id (a hash of the source commit and the mutation id): each task has
its own buggy tree, and its graph holds the mutated text. `patch` is the gold reverse patch.
`test_patch` is empty in stage 1 (no tests yet). The problem statement names the symptom only.
Usage: python -m synthetic.export SRC_DIR OUT_DIR --repo NAME --n 50 --seed 0 [--leak 0.0]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from synthetic import mutate
from synthetic.embed import embed_text, write_npz
from synthetic.graph import build_graph, read_tree

CREATED_AT = "2026-01-01T00:00:00Z"
SYMPTOMS = {
    "cmp_swap": [
        "A comparison in the library behaves the wrong way round: inputs that sit on a boundary, "
        "or on the wrong side of it, are treated the opposite way from the documentation.",
        "Values at the edge of an allowed range are accepted when they should be rejected, or "
        "rejected when they should be accepted.",
    ],
    "bool_swap": [
        "A condition that should need several things to be true at once is satisfied too easily, "
        "so some inputs are accepted or rejected by mistake.",
        "A check that should pass if either of two cases holds now insists on both, so valid "
        "inputs are turned away.",
    ],
    "const_off_by_one": [
        "Some results are off by one: a count, index or limit is one too high or one too low, "
        "and the first or last item is missing or repeated.",
        "A boundary value is wrong by one, so slices or ranges cover one item too many or too few.",
    ],
    "drop_guard": [
        "A check that should stop certain inputs early no longer applies, so those inputs go on "
        "to be processed and give wrong results or an unexpected error.",
        "Unusual inputs are no longer handled up front and reach code that cannot cope with them.",
    ],
    "swap_args": [
        "Two values are mixed up: a call receives its arguments in the wrong order, so the "
        "result is wrong whenever the two values differ.",
        "Results are swapped or reversed in some calls; the same inputs in the other order give "
        "the expected answer.",
    ],
    "wrong_return": [
        "A function hands back the wrong value in some cases, for example one of its inputs "
        "instead of the computed result, or nothing at all.",
        "The result of one call is not what the caller expects; it looks like a different value "
        "is returned from the function.",
    ],
}


def pick(variants: list[str], key: str) -> str:
    """One of `variants`, chosen by a hash of `key` (the same key always gives the same one)."""
    return variants[int(_fraction(key) * len(variants))]


def _fraction(key: str) -> float:
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=4).digest(), "little") / 2**32


def names_the_node(record: dict, leak: float) -> bool:
    """Whether this task's issue text is one of the `leak` share that names the gold node."""
    return bool(leak) and _fraction("l:" + record["id"]) < leak


def problem_statement(record: dict, leak: float = 0.0) -> str:
    """A symptom-only issue text. With `leak` > 0 that share of tasks also names the node."""
    text = pick(SYMPTOMS[record["operator"]], "v:" + record["id"])
    if names_the_node(record, leak):
        text += f" It seems to be related to `{record['gold_node'].rpartition('.')[2]}`."
    return text


def write_graph(out: Path, name: str, base: str, task_files: dict[str, str], include_async=False):
    """Write one task's graph JSON and embeddings; return (nodes, edges)."""
    graph = build_graph(task_files, f"{name}@{base[:12]}", include_async=include_async)
    (out / "graphs" / f"{name}_{base}.json").write_text(
        json.dumps(graph, separators=(",", ":")), encoding="utf-8"
    )
    write_npz(
        out / "embeddings" / f"{name}_{base}.npz",
        {n["id"]: embed_text(n["text"]) for n in graph["nodes"]},
    )
    return len(graph["nodes"]), len(graph["edges"])


def export_bundle(
    records: list[dict],
    src_root: Path,
    out_dir: Path,
    repo: str,
    commit: str,
    leak: float = 0.0,
    include_async: bool = False,
) -> dict:
    files = read_tree(src_root)
    out = Path(out_dir)
    (out / "graphs").mkdir(parents=True, exist_ok=True)
    (out / "embeddings").mkdir(parents=True, exist_ok=True)
    rows, gold = [], []
    n_nodes = n_edges = 0
    for i, rec in enumerate(records):
        base = hashlib.sha1(f"{commit}:{rec['id']}".encode()).hexdigest()
        iid = f"{repo}_{i:05d}"
        task_files = dict(files)
        task_files[rec["file"]] = rec["mutated_text"]
        nodes, edges = write_graph(out, repo, base, task_files, include_async)
        n_nodes += nodes
        n_edges += edges
        rows.append(
            {
                "instance_id": iid,
                "repo": f"synthetic/{repo}",
                "base_commit": base,
                "patch": rec["gold_patch"],
                "test_patch": "",
                "problem_statement": problem_statement(rec, leak),
                "hints_text": "",
                "created_at": CREATED_AT,
            }
        )
        gold.append(
            {
                "instance_id": iid,
                "gold_node": rec["gold_node"],
                "gold_kind": rec["gold_kind"],
                "fell_back": int(rec["fell_back"]),
                "operator": rec["operator"],
                "file": rec["file"],
            }
        )
    (out / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with open(out / "gold_nodes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, ["instance_id", "gold_node", "gold_kind", "fell_back", "operator", "file"]
        )
        w.writeheader()
        w.writerows(gold)
    return {
        "tasks": len(rows),
        "mean_nodes": round(n_nodes / max(len(rows), 1), 1),
        "mean_edges": round(n_edges / max(len(rows), 1), 1),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", default=mutate.PLACEHOLDER)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--leak", type=float, default=0.0)
    args = ap.parse_args(argv[1:])
    recs = mutate.generate(
        Path(args.src), n=args.n, seed=args.seed, repo=args.repo, commit=args.commit
    )
    print(
        json.dumps(
            export_bundle(recs, Path(args.src), Path(args.out), args.repo, args.commit, args.leak)
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
