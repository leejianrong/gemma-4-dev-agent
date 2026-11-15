import importlib.util
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location("gpu_queue", Path("scripts/gpu_queue.py"))
gq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gq)

ROWS = [
    {"model": "e4b", "minutes_per_task": "3.0"},
    {"model": "e4b", "minutes_per_task": "2.0"},
    {"model": "e4b", "minutes_per_task": "4.0"},
    {"model": "e2b", "minutes_per_task": "1.0"},
]
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def task(i, status, label):
    return {"id": i, "status": status, "label": label, "command": "x"}


def test_vram_and_need():
    assert gq.vram_mib("2991 MiB, 16384 MiB") == (2991, 16384)
    assert gq.need_mib(0.88, 16384, 512) == 14929  # 14417 for the server (0.88 of the card) + 512


def test_estimate_uses_the_models_median_then_all_runs():
    assert gq.estimate_s(ROWS, "e4b", 36) == 3.0 * 60 * 36
    assert gq.estimate_s(ROWS, "other", 10) == 2.5 * 60 * 10  # median of 1, 2, 3, 4
    assert gq.estimate_s([], "e4b", 10) is None


def test_pueue_timestamps_with_nanoseconds_parse():
    t = gq.parse_time("2026-11-15T12:11:48.805421928+08:00")
    assert (t.hour, t.minute, t.second, t.utcoffset().total_seconds()) == (12, 11, 48, 8 * 3600)


def test_schedule_chains_queued_jobs_after_the_running_one():
    started = "2026-11-15T11:30:00.123456789+00:00"
    tasks = {
        "0": task(0, {"Done": {"result": "Success"}}, "old|e4b|36"),
        "1": task(
            1, {"Running": {"start": started}}, "r1|e4b|36"
        ),  # est 108 min, started 30 min ago
        "2": task(2, {"Queued": {"enqueued_at": started}}, "r2|e2b|36"),  # est 36 min
        "3": task(3, "Queued", "r3|e4b|36"),  # status can be a bare string
    }
    jobs = gq.schedule(tasks, ROWS, NOW)
    assert [j["label"] for j in jobs] == ["r1", "r2", "r3"]  # finished jobs are left out
    assert jobs[0]["end"] == datetime(2026, 11, 15, 13, 18, 0, 123456, tzinfo=UTC)
    assert jobs[1]["start"] == jobs[0]["end"]
    assert (jobs[1]["end"] - jobs[1]["start"]).total_seconds() == 36 * 60
    assert jobs[2]["start"] == jobs[1]["end"]


def test_a_running_job_past_its_estimate_ends_now():
    tasks = {"1": task(1, {"Running": {"start": "2026-11-15T01:00:00+00:00"}}, "r1|e2b|36")}
    assert gq.schedule(tasks, ROWS, NOW)[0]["end"] == NOW


def test_unknown_estimate_does_not_break_the_queue():
    tasks = {"1": task(1, "Queued", "adhoc job")}
    job = gq.schedule(tasks, [], NOW)[0]
    assert job["est_s"] is None and job["end"] is None
