"""Shared matplotlib style, palette and figure saving, so every figure looks like one set.

Colours are the Okabe-Ito colour-blind-safe palette. Each repo keeps one colour in every figure.
`save` writes the PNG plus a sidecar JSON naming the source tables and the numbers quoted in the
caption, which is the seed of the figure-to-data registry the paper checks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "sky": "#56B4E9",
    "pink": "#CC79A7",
    "yellow": "#F0E442",
    "grey": "#6B7280",
    "black": "#111111",
}
REPO_COLORS = {
    "fastapi/fastapi": PALETTE["blue"],
    "Textualize/rich": PALETTE["orange"],
    "psf/requests": PALETTE["green"],
    "encode/httpx": PALETTE["vermillion"],
}
REPO_ORDER = list(REPO_COLORS)
FIG_WIDTH = 7.2  # inches: one column of a paper page, or half a slide
_CYCLE = ("blue", "orange", "green", "vermillion", "sky", "pink")


def short(repo: str) -> str:
    return repo.split("/")[-1]


def apply() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 100,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "figure.constrained_layout.use": True,
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#E5E7EB",
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "legend.frameon": False,
            "axes.prop_cycle": plt.cycler(color=[PALETTE[k] for k in _CYCLE]),
        }
    )


def fig_dir() -> Path:
    return Path(os.environ.get("FIG_DIR", "figures/eda"))


def save(fig, name: str, data: list[str], numbers: dict | None = None, caption: str = "") -> Path:
    """Write <fig_dir>/<name>.png and <name>.json (sources, quoted numbers, caption)."""
    out = fig_dir()
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{name}.png"
    fig.savefig(png)
    plt.close(fig)
    meta = {"figure": png.name, "data": sorted(data), "numbers": numbers or {}, "caption": caption}
    text = json.dumps(meta, indent=2, sort_keys=True) + "\n"
    (out / f"{name}.json").write_text(text, encoding="utf-8")
    return png


apply()
