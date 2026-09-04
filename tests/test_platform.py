import multiprocessing
import os
from pathlib import Path

import pytest

from lexaegis.storage import Store
from lexaegis.util import assert_local_filesystem, exclusive_lock


def _try_lock(path: str, queue) -> None:
    try:
        with exclusive_lock(Path(path), error=RuntimeError("locked")):
            queue.put("acquired")
    except RuntimeError:
        queue.put("locked")


def test_unicode_data_path_round_trip(tmp_path):
    root = tmp_path / "案件数据-林澄-ß"
    store = Store(root / "数据库.sqlite")
    with store.transaction() as repo:
        repo.put("settings", {"id": "settings", "label": "劳动争议・模拟"})
    with store.transaction() as repo:
        assert repo.get("settings")["label"] == "劳动争议・模拟"


def test_exclusive_lock_blocks_another_process(tmp_path):
    lock_path = tmp_path / "进程锁" / "worker.lock"
    context = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    queue = context.Queue()
    with exclusive_lock(lock_path, error=RuntimeError("locked")):
        process = context.Process(target=_try_lock, args=(str(lock_path), queue))
        process.start()
        process.join(10)
        assert process.exitcode == 0
        assert queue.get(timeout=2) == "locked"
    with exclusive_lock(lock_path, error=RuntimeError("locked")):
        pass


def test_platform_constraint_excludes_windows_uvloop():
    constraints = Path(__file__).parents[1] / "constraints"
    windows = (constraints / "windows.txt").read_text(encoding="utf-8")
    windows_requirements = [
        line for line in windows.lower().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("uvloop") for line in windows_requirements)
    for name in ("macos.txt", "linux.txt"):
        assert "uvloop==" in (constraints / name).read_text(encoding="utf-8")


def test_network_share_sqlite_path_is_rejected():
    with pytest.raises(ValueError, match="网络文件系统"):
        assert_local_filesystem(Path("//example.invalid/shared/case.sqlite"))
