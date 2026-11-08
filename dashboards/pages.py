"""Dashboard pages. Each page is `(title, build)`; `build(data) -> indah component`.

A dashboard card adds its page here, so the shell never changes shape.
"""

from __future__ import annotations

from collections.abc import Callable

import indah

from dashboards.data import RunData

RUN_COLUMNS = ["run_id", "variant", "seed", "subset", "n_tasks", "n_resolved", "resolution_rate"]


def overview(data: RunData):
    rates = [float(r["resolution_rate"]) for r in data.runs]
    best = max(rates) if rates else 0.0
    banner = (
        "Showing synthetic fixture data. Run `make pull-runs KERNEL=<slug>` to load real runs."
        if data.is_fixture
        else f"Loaded {len(data.runs)} runs from {', '.join(str(p) for p in data.sources)}."
    )
    table = [{c: r.get(c, "") for c in RUN_COLUMNS} for r in data.runs]
    return indah.Column(
        children=[
            indah.Text(f"# Runs overview\n\n{banner}", markdown=True),
            indah.Grid(
                columns=3,
                children=[
                    indah.Stat(len(data.runs), label="runs"),
                    indah.Stat(len({t["instance_id"] for t in data.tasks}), label="distinct tasks"),
                    indah.Stat(f"{100 * best:.1f}%", label="best resolution rate"),
                ],
            ),
            indah.DataFrame(table, label="Runs"),
        ]
    )


PAGES: list[tuple[str, Callable[[RunData], object]]] = [("Overview", overview)]
