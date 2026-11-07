"""Loaders for the tables from the Kaggle `gemma-4-eda-extract` kernel (see pod/eda_extract.py)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def eda_dir() -> Path:
    return Path(os.environ.get("EDA_DIR", "data/eda"))


def path(name: str) -> Path:
    p = eda_dir() / name
    if not p.is_file():
        raise FileNotFoundError(
            f"{p} not found. Run `make pull-eda` to download the kernel's output "
            "(small CSVs; the kernel is built with `make kernel-eda`)."
        )
    return p


def load(name: str) -> pd.DataFrame:
    """Read one table; .csv.gz is handled by pandas from the extension."""
    return pd.read_csv(path(name))
