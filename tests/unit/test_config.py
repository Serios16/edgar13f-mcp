import os

import pytest

from edgar13f import config


def test_env_cache_dir_used(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR13F_CACHE_DIR", str(tmp_path / "c"))
    assert config.cache_dir() == tmp_path / "c"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_unwritable_env_falls_back(tmp_path, monkeypatch):
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    monkeypatch.setenv("EDGAR13F_CACHE_DIR", str(ro / "c"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert config.cache_dir() == tmp_path / "xdg" / "edgar13f"


def test_default_then_temp_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("EDGAR13F_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert config.cache_dir() == tmp_path / "xdg" / "edgar13f"
    real = config._usable
    monkeypatch.setattr(config, "_usable", lambda p: "xdg" not in str(p) and real(p))
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    got = config.cache_dir()
    assert str(got).startswith(str(tmp_path / "tmp"))


def test_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "  a b@c.d ")
    assert config.user_agent() == "a b@c.d"
    monkeypatch.setenv("SEC_USER_AGENT", "")
    assert config.user_agent() is None


def test_write_json_from_many_threads_to_one_path(tmp_path):
    import threading

    from edgar13f.config import write_json

    errors = []

    def work(i):
        try:
            for _ in range(50):
                write_json(tmp_path / "x" / "same.json", {"i": i})
        except OSError as exc:  # a shared temporary name makes one thread's rename fail
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and sorted(p.name for p in (tmp_path / "x").iterdir()) == ["same.json"]


def test_sweep_stale_temp_removes_only_dead_process_temp_files(tmp_path):
    import subprocess
    import sys

    from edgar13f.config import sweep_stale_temp

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    names = {f"a.tmp{dead.pid}-7": False, f"b.tmp{os.getpid()}-7": True, "c.tmp": True,
             "d.tmpabc-1": True, "e.json": True, f"sub/f.tmp{dead.pid}-1": False}
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    (tmp_path / f"g.tmp{dead.pid}-1").mkdir()  # a directory is never removed
    sweep_stale_temp(tmp_path)
    assert {n: (tmp_path / n).exists() for n in names} == names
    assert (tmp_path / f"g.tmp{dead.pid}-1").is_dir()
