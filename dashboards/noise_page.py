"""The noise planner page: inputs on the left, what the noise allows on the right."""

from __future__ import annotations

import indah

from dashboards import noise
from dashboards.data import RunData, table


def page(_data: RunData):
    names = list(noise.DENOMINATORS)
    denom = indah.Signal(names[0])
    base = indah.Signal(17.0)
    gain = indah.Signal(5.0)
    w = indah.Signal(noise.DEFAULT_W)
    reps = indah.Signal(3.0)

    def n() -> int:
        return noise.DENOMINATORS[denom.value]

    def p() -> float:
        return base.value / 100.0

    def needed() -> str:
        r = noise.replicates_needed(gain.value, n(), max(w.value, 1e-6))
        return "-" if r is None else str(r)

    def rows() -> dict:
        out = []
        for label, nn in noise.DENOMINATORS.items():
            out.append(
                {
                    "tasks": label,
                    "one task is worth (points)": round(noise.quantum(nn), 2),
                    "95% band on one score (points, +/-)": round(noise.binomial_band(p(), nn), 1),
                    "gain detectable with 1 replicate": round(
                        noise.detectable_gain(nn, w.value, 1), 1
                    ),
                    f"gain detectable with {int(reps.value)} replicates": round(
                        noise.detectable_gain(nn, w.value, int(reps.value)), 1
                    ),
                }
            )
        return table(out, list(out[0]))

    return indah.Column(
        children=[
            indah.Text(
                "# Noise and replicate planner\n\n"
                "Replicates shrink run-to-run noise on the **same tasks**. They cannot shrink the "
                "task-sampling band of a single score, which is set by how many tasks there are. "
                "`w` is an assumption until we have replicate runs; see `dashboards/noise.py`.",
                markdown=True,
            ),
            indah.Row(
                children=[
                    indah.Select(denom, options=names, label="Task set"),
                    indah.Number(base, min=0, max=100, step=1, label="Baseline score (%)"),
                    indah.Number(gain, min=0.5, max=50, step=0.5, label="Target gain (points)"),
                ]
            ),
            indah.Row(
                children=[
                    indah.Number(
                        w, min=0.005, max=0.25, step=0.005, label="Within-task variance w"
                    ),
                    indah.Number(reps, min=1, max=50, step=1, label="Replicates per variant"),
                ]
            ),
            indah.Grid(
                columns=3,
                children=[
                    indah.Stat(
                        lambda: f"{noise.quantum(n()):.2f} points", label="one task is worth"
                    ),
                    indah.Stat(needed, label="replicates per variant for the target gain"),
                    indah.Stat(
                        lambda: f"+/-{noise.binomial_band(p(), n()):.1f} points",
                        label="95% band on one score",
                    ),
                ],
            ),
            indah.Chart(
                lambda: noise.needed_curve(n(), max(w.value, 1e-6)),
                series=["replicates per variant"],
                title="Replicates needed to detect a gain (same tasks, 80% power)",
                x_label="gain (points)",
            ),
            indah.DataFrame(rows, label="What each task set can resolve"),
        ]
    )
