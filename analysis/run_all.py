"""Regenerate every EDA figure: `make eda`. Each figure module exposes `build() -> list[Path]`."""

from __future__ import annotations

import importlib
import sys

FIGURE_MODULES: list[str] = ["eda_inventory"]  # appended by each figure card, in reading order


def main() -> int:
    if not FIGURE_MODULES:
        print("no figure modules registered yet")
        return 0
    failed = 0
    for name in FIGURE_MODULES:
        try:
            for png in importlib.import_module(f"analysis.{name}").build():
                print(f"wrote {png}")
        except FileNotFoundError as e:
            print(f"ERROR {name}: {e}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
