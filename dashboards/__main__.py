"""`python -m dashboards [--port N]`: serve on the first free port and print the URL."""

from __future__ import annotations

import argparse

import indah

from dashboards.app import create


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dashboards")
    ap.add_argument("--port", type=int, default=None, help="default: first free port from 8000")
    args = ap.parse_args(argv)
    indah.launch(create(), port=args.port, block=True, open_inline=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
