import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.package_delivery import image_ids, package, sha256
from .test_formal_release_flow import _manifest


ROOT = Path(__file__).resolve().parents[1]


def _inputs(tmp_path):
    images = tmp_path / "images.tar"
    configs = [b'{"architecture":"amd64","test_fixture":"runtime"}',
               b'{"architecture":"amd64","test_fixture":"route"}']
    with tarfile.open(images, "w") as archive:
        files = {f"config-{i}.json": config for i, config in enumerate(configs)}
        files["manifest.json"] = json.dumps([{"Config": name, "Layers": []} for name in files]).encode()
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    import hashlib
    runtime, route = ["sha256:" + hashlib.sha256(config).hexdigest() for config in configs]
    wheel = tmp_path / "lexaegis-test.whl"
    wheel.write_bytes(b"test artifact only")
    manifest = _manifest().model_copy(update={
        "status": "pending", "wheel_hash": sha256(wheel),
        "container_image_digests": {role: runtime for role in ("api", "worker", "gateway")},
        "lockfile_hashes": {name: sha256(ROOT / name) for name in ("requirements.lock", "frontend/pnpm-lock.yaml")},
    })
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json())
    inventory = tmp_path / "dependencies.json"
    inventory.write_text(json.dumps({"runtime_image_id": runtime, "components": [
        {"name": "test-dependency", "version": "1", "license": "test fixture"}]}))
    return dict(root=ROOT, profile="demo", images=images, runtime_image=runtime, route_image=route,
                manifest_path=manifest_path, wheel=wheel, dependencies=inventory,
                output=tmp_path / "delivery.zip")


def test_bundle_binds_images_wheel_inventory_and_provenance(tmp_path):
    args = _inputs(tmp_path)
    index = package(**args)
    assert index["production_acceptance"] == "not_attested_by_packaging"
    with zipfile.ZipFile(args["output"]) as archive:
        names = set(archive.namelist())
        assert {"images.tar", "release-build-manifest.json", "dependencies.json", "delivery.json",
                "scripts/windows/lexaegis.ps1", "docs/DUAL_TRACK_ACCEPTANCE.md"} <= names
        assert not any(name.endswith(".sqlite") or name == ".env" for name in names)
        assert json.loads(archive.read("delivery.json"))["files"]["images.tar"] == sha256(args["images"])
    with pytest.raises(ValueError, match="overwrite"):
        package(**args)


@pytest.mark.parametrize("mutation,match", [
    ("production", "verified"), ("image", "image IDs"),
    ("wheel", "Wheel"), ("inventory", "exact delivered image"),
])
def test_bundle_refuses_mismatched_release_inputs(tmp_path, mutation, match):
    args = _inputs(tmp_path)
    if mutation == "production":
        args["profile"] = "production"
    elif mutation == "image":
        args["runtime_image"] = "sha256:" + "f" * 64
    elif mutation == "wheel":
        args["wheel"].write_bytes(b"changed wheel")
    else:
        inventory = json.loads(args["dependencies"].read_text())
        inventory["runtime_image_id"] = "sha256:" + "f" * 64
        args["dependencies"].write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match=match):
        package(**args)
    assert not args["output"].exists()


def test_image_archive_cannot_reference_outside_path(tmp_path):
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, "w") as archive:
        data = json.dumps([{"Config": "../../outside.json"}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="Unsafe"):
        image_ids(archive_path)
