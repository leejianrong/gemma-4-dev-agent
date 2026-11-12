import os

import pytest


@pytest.fixture(autouse=True)
def no_inherited_git_env(monkeypatch):
    """A git hook sets GIT_DIR; tests that run git in a temp folder must not act on this repo."""
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        monkeypatch.delenv(name)
