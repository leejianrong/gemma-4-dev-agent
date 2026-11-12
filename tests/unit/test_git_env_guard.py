import os
import subprocess


def test_git_in_a_temp_folder_is_its_own_repository(tmp_path):
    # The autouse fixture in tests/conftest.py drops the GIT_* variables a git hook exports.
    assert not [n for n in os.environ if n.startswith("GIT_")]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    top = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert top == str(tmp_path.resolve())
