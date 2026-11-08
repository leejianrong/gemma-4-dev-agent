"""The dashboard app: one tab per page in `dash.pages.PAGES`."""

from __future__ import annotations

import indah

from dashboards import data as rundata
from dashboards.pages import PAGES


def build_session() -> indah.Session:
    data = rundata.load()
    pages = [build(data) for _, build in PAGES]
    tabs = indah.Tabs(children=pages, labels=[title for title, _ in PAGES])
    return indah.Session(indah.Column(children=[tabs]))


def create() -> object:
    return indah.create_app(session_factory=build_session)
