"""Multi-worker logging: append mode, single-process size rotation, deploy truncation."""

import importlib
import logging
from logging.handlers import RotatingFileHandler

import pytest

import rock.logger as rock_logger
from rock import env_vars


@pytest.fixture(autouse=True)
def _clear_handler_cache():
    rock_logger.init_file_handler.cache_clear()
    yield
    rock_logger.init_file_handler.cache_clear()


def test_rock_logging_append_defaults_false(monkeypatch):
    monkeypatch.delenv("ROCK_LOGGING_APPEND", raising=False)
    import rock.env_vars as ev

    importlib.reload(ev)
    assert ev.ROCK_LOGGING_APPEND is False


def test_file_handler_defaults_to_truncate_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_APPEND", False, raising=False)
    p = tmp_path / "trunc_default.log"
    p.write_text("stale lines from a previous run\n")
    handler = rock_logger.init_file_handler("trunc_default.log")
    assert handler is not None
    assert p.read_text() == ""
    handler.close()


def test_file_handler_append_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_APPEND", True, raising=False)
    handler = rock_logger.init_file_handler("append_mode.log")
    assert handler is not None
    assert handler.mode == "a"


def test_reset_log_file_truncates_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_FILE_NAME", "deploy.log", raising=False)
    p = tmp_path / "deploy.log"
    p.write_text("stale lines from previous deploy\n")
    rock_logger.reset_log_file()
    assert p.read_text() == ""


def test_reset_log_file_noop_without_path(monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", None, raising=False)
    # must not raise when file logging is disabled (stdout mode)
    rock_logger.reset_log_file()


def _emit_lines(handler, count: int) -> None:
    probe = logging.getLogger("rotation_probe")
    probe.handlers = [handler]
    probe.setLevel(logging.INFO)
    probe.propagate = False
    for _ in range(count):
        probe.info("x" * 100)
    handler.flush()


def test_rotation_defaults(monkeypatch):
    monkeypatch.delenv("ROCK_LOGGING_MAX_BYTES", raising=False)
    monkeypatch.delenv("ROCK_LOGGING_BACKUP_COUNT", raising=False)
    import rock.env_vars as ev

    importlib.reload(ev)
    assert ev.ROCK_LOGGING_MAX_BYTES == 1024 * 1024 * 1024
    assert ev.ROCK_LOGGING_BACKUP_COUNT == 5


def test_single_process_handler_rotates_by_size(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_APPEND", False, raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_MAX_BYTES", 512, raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_BACKUP_COUNT", 2, raising=False)

    handler = rock_logger.init_file_handler("rotating.log")
    assert isinstance(handler, RotatingFileHandler)
    _emit_lines(handler, 40)
    handler.close()

    assert (tmp_path / "rotating.log.1").exists()
    assert (tmp_path / "rotating.log.2").exists()
    assert not (tmp_path / "rotating.log.3").exists()
    assert (tmp_path / "rotating.log").stat().st_size <= 512


def test_append_handler_does_not_rotate(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_APPEND", True, raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_MAX_BYTES", 512, raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_BACKUP_COUNT", 2, raising=False)

    handler = rock_logger.init_file_handler("append_shared.log")
    assert not isinstance(handler, RotatingFileHandler)
    _emit_lines(handler, 40)
    handler.close()

    assert not (tmp_path / "append_shared.log.1").exists()
    assert (tmp_path / "append_shared.log").stat().st_size > 512


def test_zero_max_bytes_disables_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_PATH", str(tmp_path), raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_APPEND", False, raising=False)
    monkeypatch.setattr(env_vars, "ROCK_LOGGING_MAX_BYTES", 0, raising=False)

    handler = rock_logger.init_file_handler("unbounded.log")
    _emit_lines(handler, 40)
    handler.close()

    assert not (tmp_path / "unbounded.log.1").exists()
    assert (tmp_path / "unbounded.log").stat().st_size > 0
