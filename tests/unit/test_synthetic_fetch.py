import json
import subprocess

import pytest

from synthetic.fetch import FetchError, fetch, load_manifest

ENTRY = {
    "name": "toolz",
    "url": "https://github.com/pytoolz/toolz.git",
    "tag": "1.2.0",
    "sha": "451af60dec590a6010e2babdbf391ea8f815122f",
}


class Runner:
    """Stands in for subprocess.run: records calls and answers rev-parse with `head`."""

    def __init__(self, head):
        self.head = head
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.head + "\n" if "rev-parse" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def test_fetch_clones_the_pinned_tag_shallow_and_verifies_the_sha(tmp_path):
    run = Runner(ENTRY["sha"])
    dest = fetch(ENTRY, tmp_path, runner=run)
    assert dest == tmp_path / "toolz"
    clone = run.calls[0]
    assert clone[:2] == ["git", "clone"] and "--depth" in clone and "1" in clone
    assert "--branch" in clone and "1.2.0" in clone and ENTRY["url"] in clone
    assert any("rev-parse" in c for c in run.calls)


def test_fetch_refuses_and_removes_a_checkout_whose_head_differs(tmp_path):
    run = Runner("0" * 40)

    def clone_makes_dir(cmd, **kw):
        if cmd[1] == "clone":
            (tmp_path / "toolz").mkdir()
        return run(cmd, **kw)

    with pytest.raises(FetchError, match="HEAD"):
        fetch(ENTRY, tmp_path, runner=clone_makes_dir)
    assert not (tmp_path / "toolz").exists()


def test_fetch_reuses_a_checkout_that_is_already_at_the_pinned_sha(tmp_path):
    (tmp_path / "toolz").mkdir()
    run = Runner(ENTRY["sha"])
    assert fetch(ENTRY, tmp_path, runner=run) == tmp_path / "toolz"
    assert all(c[1] != "clone" for c in run.calls)


def test_fetch_never_runs_anything_but_git(tmp_path):
    run = Runner(ENTRY["sha"])
    fetch(ENTRY, tmp_path, runner=run)
    assert {c[0] for c in run.calls} == {"git"}


def test_load_manifest_requires_a_full_sha(tmp_path):
    good = [{**ENTRY}]
    bad = [{**ENTRY, "sha": "abc123"}]
    p = tmp_path / "m.json"
    p.write_text(json.dumps(good))
    assert load_manifest(p)[0]["name"] == "toolz"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="sha"):
        load_manifest(p)
