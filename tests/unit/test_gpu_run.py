from pod import gpu_run


def test_fetch_skips_what_is_already_downloaded(tmp_path, monkeypatch):
    (tmp_path / "wheelhouse").mkdir()
    (tmp_path / "wheelhouse" / "a-1-py3-none-any.whl").write_text("")
    model = tmp_path / "models" / gpu_run.MODEL / "2"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_text("")
    monkeypatch.setattr(gpu_run, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert gpu_run.fetch(tmp_path) == (tmp_path / "wheelhouse", tmp_path / "models")


def test_main_points_the_kernel_at_the_pod_folders(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gpu_run, "fetch", lambda w: (w / "wheelhouse", w / "models"))
    monkeypatch.setattr(gpu_run, "run", lambda cmd, env=None: calls.append((cmd, env)))
    monkeypatch.setenv("GPU_WORK", str(tmp_path / "w"))
    assert gpu_run.main(["gpu_run.py", str(tmp_path / "data"), str(tmp_path / "out")]) == 0
    test_env, setup, kernel = calls
    assert test_env[0][1].endswith("test_env.sh")
    assert setup[0][0] == "bash" and setup[1] == {"WHEELHOUSE": str(tmp_path / "w" / "wheelhouse")}
    assert kernel[0][1].endswith("kernel.py")
    assert kernel[1]["DATA_DIR"] == str(tmp_path / "data")
    assert kernel[1]["ER_MODEL_ROOT_DIR"] == str(tmp_path / "w" / "models")


def test_control_ids_gate_the_run_and_check_only_stops_before_the_download(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gpu_run, "run", lambda cmd, env=None: calls.append(cmd))
    monkeypatch.setattr(gpu_run, "fetch", lambda w: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setenv("GPU_WORK", str(tmp_path / "w"))
    monkeypatch.setenv("CONTROL_IDS", "a_1,b_2")
    monkeypatch.setenv("ENV_CHECK_ONLY", "1")
    assert gpu_run.main(["gpu_run.py", str(tmp_path / "data"), str(tmp_path / "out")]) == 0
    assert calls[1][1].endswith("env_check.py") and calls[1][3] == "a_1,b_2"
