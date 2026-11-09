"""Print what a skill script can see: cwd, workspace, libraries, graph files, speed.

Each fact is printed as soon as it is known, so a timeout still leaves output. Nothing walks `/`.
"""

import importlib.util
import json
import os
import re
import sys
import time

t0 = time.time()


def show(key, value):
    print(json.dumps({key: value, "t": round(time.time() - t0, 3)}), flush=True)


show("cwd", os.getcwd())
show("python", sys.version.split()[0])
show("cpus", os.cpu_count())
show("root_top", sorted(os.listdir("/"))[:40])
show(
    "workspace_top", sorted(os.listdir("/workspace"))[:30] if os.path.isdir("/workspace") else None
)
show(
    "candidate_dirs",
    {d: os.path.isdir(d) for d in ("/data", "/kaggle", "/kaggle/input", "/mnt", "/workspace/data")},
)
py, words = 0, 0
for root, dirs, files in os.walk("/workspace"):
    dirs[:] = [d for d in dirs if d not in ("tests", "docs", "docs_src", ".git", "__pycache__")]
    for name in files:
        if name.endswith(".py"):
            py += 1
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                    words += len(re.findall(r"\w+", fh.read()))
            except OSError:
                pass
show("non_test_py_files_and_tokens", [py, words])
show(
    "libs",
    {
        m: importlib.util.find_spec(m) is not None
        for m in ("numpy", "rank_bm25", "sklearn", "networkx", "scipy")
    },
)
show("task_env_var_names", sorted(k for k in os.environ if "TASK" in k or "REPO" in k)[:10])
try:
    with open("/tmp/probe_write_test", "w") as fh:
        fh.write("x")
    show("tmp_writable", True)
except OSError:
    show("tmp_writable", False)
