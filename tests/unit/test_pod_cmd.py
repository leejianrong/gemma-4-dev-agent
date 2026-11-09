from pod.pod_cmd import command, env_value


def test_env_value_reads_by_name_and_strips_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\nKAGGLE_API_TOKEN='tok en'\n")
    assert env_value(f, "KAGGLE_API_TOKEN") == "tok en"


def test_command_embeds_scripts_and_quotes_the_token(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("print('hi')\n")
    cmd = command(a, "x'y")
    assert "export KAGGLE_API_TOKEN='x'\"'\"'y'" in cmd
    assert "bash job.sh" in cmd
    assert "print('hi')" not in cmd  # the files travel compressed
    assert cmd.index("export KAGGLE_API_TOKEN") < cmd.index("bash job.sh")


def test_heredoc_round_trips_through_base64_gunzip(tmp_path):
    import subprocess

    from pod.pod_cmd import heredoc

    text = "line one\nline 'two'\n" * 50
    out = tmp_path / "f.txt"
    subprocess.run(["bash", "-c", heredoc(str(out), text, "EOF_T")], check=True)
    assert out.read_text() == text.rstrip() + "\n"


def test_extra_env_pairs_are_exported_before_the_job(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    cmd = command(a, "t", ["WANT_SNAPSHOTS=1", "MAX_MIB=30000"])
    assert "export WANT_SNAPSHOTS=1\n" in cmd and "export MAX_MIB=30000\n" in cmd
    assert cmd.index("export MAX_MIB") < cmd.index("bash job.sh")
