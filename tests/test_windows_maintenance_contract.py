"""Static contract checks for Windows maintenance argument and image binding.

The PowerShell runtime is not available on every CI host; these assertions guard
critical script contracts without claiming to execute the launcher on Windows.
"""
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "windows" / "lexaegis.ps1"


def test_restore_arguments_are_constructed_explicitly_for_restore_and_rollback():
    script = SCRIPT.read_text(encoding="utf-8")
    restore_branch = re.search(r"\} elseif \(\$command\[0\] -eq 'restore'\) \{(.*?)\n    \} else", script, re.S)
    assert restore_branch, "restore branch must be present"
    body = restore_branch.group(1)
    assert "$command = @('restore', $containerArchive, '--target', '/data', '--gateway-target', '/gateway', '--profile', $Profile)" in body
    assert "Select-Object -Skip" not in body
    assert script.count("Invoke-Maintenance -Arguments @('restore', $Archive, '--target', $AppData, '--gateway-target', $GatewayData, '--profile', $Profile)") == 2
    assert "-Image $maintenanceImage" in script
    assert "-Image $oldImage" in script


def test_runtime_and_route_images_are_checked_against_manifest_and_delivery_index():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "docker image inspect --format '{{.Id}}' $Image" in script
    assert "foreach ($role in @('api','worker','gateway'))" in script
    assert "$result.digests.$role -ne $runtimeId" in script
    assert "Assert-ImageMatchesDelivery -Image $selectedImage -Key 'runtime_image_id'" in script
    assert "Assert-ImageMatchesDelivery -Image $routeImage -Key 'route_image_id'" in script
    assert "alpine:3.20" not in script
    assert "-RouteImage" in script and "-DeliveryIndex" in script


def test_maintenance_python_runs_only_in_pinned_offline_container():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function Invoke-PinnedPython" in script
    assert "--network','none'" in script
    assert "Get-Command python" not in script
    assert "Python 3.12 is required" not in script


def test_active_send_probe_keeps_sqlite_wal_directory_writable():
    script = SCRIPT.read_text(encoding="utf-8")
    active_send = re.search(r"function Test-ActiveSend \{(.*?)\n\}", script, re.S)
    assert active_send
    body = active_send.group(1)
    assert '"$($AppData):/data"' in body
    assert '"$($AppData):/data:ro"' not in body
    assert "immutable=1" not in body
    assert "select body from records where kind=" in body

    # Leave a committed WAL frame behind as if the prior service exited before
    # checkpointing, remove only its SHM helper, then confirm a normal read can
    # reopen it and rebuild coordination files on a writable mount.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.sqlite"
        writer = (
            "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute('PRAGMA journal_mode=WAL'); c.execute('CREATE TABLE probe(value)'); "
            "c.execute('INSERT INTO probe VALUES (7)'); c.commit(); os._exit(0)"
        )
        subprocess.run([sys.executable, "-c", writer, str(database)], check=True)
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        assert wal.exists() and wal.stat().st_size > 0
        shm.unlink(missing_ok=True)
        connection = sqlite3.connect(database)
        try:
            assert connection.execute("SELECT value FROM probe").fetchone() == (7,)
            assert shm.exists()
        finally:
            connection.close()


def test_existing_start_profile_defers_image_updates_until_after_preflight():
    script = SCRIPT.read_text(encoding="utf-8")
    preflight = script.index("# Validate start candidates before Write-EnvFile")
    write_env = script.index("Write-EnvFile\nswitch ($Action)")
    start_branch = script.index("'start' {")
    assert preflight < write_env < start_branch
    assert "if ($Action -eq 'start' -and (Test-Path $EnvFile))" in script
    assert "$ReleaseImage = $null" in script[script.index("if ($Action -eq 'start' -and (Test-Path $EnvFile))"):write_env]
    assert "$RouteImage = $null" in script[script.index("if ($Action -eq 'start' -and (Test-Path $EnvFile))"):write_env]
    assert "Set-ConfiguredValue 'LEX_RELEASE_IMAGE' (Get-ImageId $selectedImage)" in script[start_branch:]
