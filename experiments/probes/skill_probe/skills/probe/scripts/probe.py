"""Print what a skill script can see: cwd, workspace, libraries, graph files, speed."""

import glob
import importlib.util
import json
import os
import re
import sys
import time

t0 = time.time()
out = {"cwd": os.getcwd(), "python": sys.version.split()[0], "cpus": os.cpu_count()}
out["workspace_top"] = (
    sorted(os.listdir("/workspace"))[:30] if os.path.isdir("/workspace") else None
)
py = [p for p in glob.glob("/workspace/**/*.py", recursive=True) if "/tests/" not in p]
out["py_files_non_test"] = len(py)
words = 0
for p in py:
    try:
        words += len(re.findall(r"\w+", open(p, encoding="utf-8", errors="replace").read()))
    except OSError:
        pass
out["tokens_in_non_test_py"] = words
out["index_seconds"] = round(time.time() - t0, 3)
out["libs"] = {
    m: importlib.util.find_spec(m) is not None
    for m in ("numpy", "rank_bm25", "sklearn", "networkx", "scipy")
}
out["graph_like_files"] = [p for p in glob.glob("/**/*.npz", recursive=True)[:5]] + glob.glob(
    "/**/graphs/*.json", recursive=True
)[:5]
out["env_has_task_vars"] = sorted(k for k in os.environ if "TASK" in k or "REPO" in k)[:10]
try:
    open("/tmp/probe_write_test", "w").write("x")
    out["tmp_writable"] = True
except OSError:
    out["tmp_writable"] = False
out["total_seconds"] = round(time.time() - t0, 3)
print(json.dumps(out))
