from pathlib import Path

from synthetic.readiness import (
    check_repo,
    detect_license,
    find_package_dir,
    find_tests_dir,
    render_table,
    third_party_imports,
)


def make_repo(root: Path, tests: dict[str, str], pyproject: str = "", pkg: str = "mylib") -> Path:
    (root / pkg).mkdir(parents=True)
    (root / pkg / "__init__.py").write_text("")
    (root / "tests").mkdir()
    for name, text in tests.items():
        (root / "tests" / name).write_text(text)
    if pyproject:
        (root / "pyproject.toml").write_text(pyproject)
    return root


def test_third_party_imports_skips_stdlib_own_package_and_local_test_modules(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "helpers.py": "x = 1\n",
            "test_a.py": "import os\nimport json\nimport mylib\nfrom mylib.x import y\n"
            "import helpers\nimport dirty_equals\nfrom . import sibling\nimport pytest\n",
        },
    )
    got = third_party_imports(repo / "tests", {"mylib"})
    assert got == {"dirty_equals", "pytest"}


def test_syntax_errors_in_a_test_file_do_not_stop_the_scan(tmp_path):
    repo = make_repo(tmp_path, {"test_a.py": "def (:\n", "test_b.py": "import attr_extra\n"})
    assert third_party_imports(repo / "tests", {"mylib"}) == {"attr_extra"}


def test_a_repo_with_only_stdlib_and_pytest_imports_is_admitted(tmp_path):
    repo = make_repo(tmp_path, {"test_a.py": "import pytest\nimport mylib\n"})
    row = check_repo("mylib", repo, "mylib", "tests")
    assert row["admit"] is True and row["reasons"] == []


def test_an_undeclared_third_party_test_import_rejects(tmp_path):
    repo = make_repo(tmp_path, {"test_a.py": "import dirty_equals\n"})
    row = check_repo("mylib", repo, "mylib", "tests")
    assert row["admit"] is False
    assert any("dirty_equals" in r for r in row["reasons"])


def test_a_declared_runtime_dependency_is_not_a_reason_to_reject(tmp_path):
    repo = make_repo(
        tmp_path,
        {"test_a.py": "import markupsafe\n"},
        pyproject='[project]\nname = "mylib"\ndependencies = ["MarkupSafe>=2"]\n',
    )
    assert check_repo("mylib", repo, "mylib", "tests")["admit"] is True


def test_network_fixtures_and_missing_plugins_reject(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "test_a.py": "def test_x(httpbin):\n    pass\n",
            "test_b.py": "import pytest\n@pytest.mark.asyncio\nasync def test_y():\n    pass\n",
            "test_c.py": "def test_z(mocker):\n    pass\n",
        },
    )
    row = check_repo("mylib", repo, "mylib", "tests")
    text = " ".join(row["reasons"])
    assert row["admit"] is False
    assert "httpbin" in text and "asyncio" in text and "mocker" in text


def test_requires_python_above_the_sandbox_rejects(tmp_path):
    repo = make_repo(
        tmp_path,
        {"test_a.py": "x = 1\n"},
        pyproject='[project]\nname = "mylib"\nrequires-python = ">=3.14"\n',
    )
    row = check_repo("mylib", repo, "mylib", "tests")
    assert row["admit"] is False and any("3.14" in r for r in row["reasons"])


def test_detect_license_reads_common_licence_text():
    assert detect_license("Permission is hereby granted, free of charge, to any person") == "MIT"
    assert detect_license("Apache License\nVersion 2.0, January 2004") == "Apache-2.0"
    assert (
        detect_license(
            "Redistribution and use in source and binary forms, with or without\n"
            "3. Neither the name of the copyright holder nor the names"
        )
        == "BSD-3-Clause"
    )
    assert (
        detect_license(
            "Redistribution and use in source and binary forms, with or without\n"
            "modification, are permitted"
        )
        == "BSD-2-Clause"
    )
    assert detect_license("some custom terms") == "UNKNOWN"


def test_find_package_and_tests_dirs(tmp_path):
    (tmp_path / "src" / "mylib").mkdir(parents=True)
    (tmp_path / "src" / "mylib" / "__init__.py").write_text("")
    (tmp_path / "test").mkdir()
    assert find_package_dir(tmp_path, "mylib") == "src/mylib"
    assert find_tests_dir(tmp_path) == "test"


def test_render_table_lists_each_repo_and_its_verdict():
    rows = [
        {"name": "a", "admit": True, "reasons": [], "third_party": []},
        {"name": "b", "admit": False, "reasons": ["needs dirty_equals"], "third_party": ["x"]},
    ]
    out = render_table(rows)
    assert "| a | admit |" in out and "| b | reject | needs dirty_equals" in out


def test_repo_root_names_and_the_tests_package_itself_count_as_local(tmp_path):
    repo = make_repo(
        tmp_path, {"test_a.py": "from tests import helpers\nimport scripts\nimport docs_src\n"}
    )
    (repo / "scripts").mkdir()
    (repo / "docs_src").mkdir()
    assert check_repo("mylib", repo, "mylib", "tests")["admit"] is True


def test_optional_imports_and_uncollected_files_are_not_counted(tmp_path):
    repo = make_repo(
        tmp_path,
        {
            "test_a.py": "try:\n    import cytoolz\nexcept ImportError:\n    cytoolz = None\n",
            "fuzz_b.py": "import atheris\n",
        },
    )
    assert third_party_imports(repo / "tests", {"mylib"}) == set()
