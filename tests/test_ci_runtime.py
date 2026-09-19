import pytest

from lexaegis.runtime_identity import runtime_identity, _load_manifest
from scripts.prepare_ci_runtime import prepare


def test_ci_manifest_remains_pending_and_cannot_overwrite_release(tmp_path):
    target = tmp_path / "release-build-manifest.json"
    prepare(target)
    assert runtime_identity("api", manifest_path=target).status == "pending"
    assert _load_manifest(None, target)[1] == "pending"
    with pytest.raises(FileExistsError):
        prepare(target)
