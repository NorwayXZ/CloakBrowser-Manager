import os
import time
from pathlib import Path

from backend.log_rotation import rotate_log, start_rotation


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_small_or_missing_log_is_left_alone(tmp_path: Path):
    log = tmp_path / "manager.log"
    assert rotate_log(log, max_bytes=100) is False
    _write(log, "x" * 100)
    assert rotate_log(log, max_bytes=100) is False
    assert log.read_text() == "x" * 100
    assert not (tmp_path / "manager.log.1").exists()


def test_big_log_moves_to_dot_one_and_restarts_empty(tmp_path: Path):
    log = tmp_path / "manager.log"
    _write(log, "a" * 101)
    assert rotate_log(log, max_bytes=100) is True
    assert log.read_text() == ""
    assert (tmp_path / "manager.log.1").read_text() == "a" * 101


def test_older_copies_shift_up_and_only_keep_are_kept(tmp_path: Path):
    log = tmp_path / "manager.log"
    for generation in "abcd":
        _write(log, generation * 101)
        rotate_log(log, max_bytes=100, keep=3)
    assert (tmp_path / "manager.log.1").read_text() == "d" * 101
    assert (tmp_path / "manager.log.2").read_text() == "c" * 101
    assert (tmp_path / "manager.log.3").read_text() == "b" * 101
    assert not (tmp_path / "manager.log.4").exists()


def test_a_writer_that_stays_open_in_append_mode_keeps_writing_at_the_new_end(tmp_path: Path):
    log = tmp_path / "manager.log"
    with open(log, "a", buffering=1, encoding="utf-8") as writer:
        writer.write("old line\n" * 20)
        assert rotate_log(log, max_bytes=50) is True
        writer.write("after rotation\n")
    assert log.read_text() == "after rotation\n"
    assert (tmp_path / "manager.log.1").read_text().count("old line") == 20


def test_rotation_failure_is_swallowed(tmp_path: Path):
    log = tmp_path / "manager.log"
    _write(log, "a" * 101)
    # A directory where the copy should go makes the copy fail.
    (tmp_path / "manager.log.1").mkdir()
    (tmp_path / "manager.log.1" / "keep").write_text("x")
    assert rotate_log(log, max_bytes=100, keep=1) is False
    assert log.read_text() == "a" * 101


def test_watcher_rotates_while_the_app_runs(tmp_path: Path):
    log = tmp_path / "manager.log"
    thread = start_rotation(log, max_bytes=100, keep=2, interval=0.05)
    try:
        _write(log, "z" * 500)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and os.path.getsize(log) > 0:
            time.sleep(0.05)
        assert log.read_text() == ""
        assert (tmp_path / "manager.log.1").exists()
    finally:
        thread.stop.set()  # type: ignore[attr-defined]
