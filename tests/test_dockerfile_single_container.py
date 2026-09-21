from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_single_container_image_keeps_app_and_gateway_roots_separate():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "LEX_DATA_DIR=/data/app" in dockerfile
    assert "LEX_GATEWAY_DIR=/data/gateway" in dockerfile
    assert "LEX_RUN_PROFILE=demo" in dockerfile
    assert "mkdir -p /data/app /data/gateway" in dockerfile
    assert "LEX_DATA_DIR=/data \\" not in dockerfile
    assert "FROM ubuntu:24.04" in dockerfile
    assert "COPY --from=llama /app /opt/llama" in dockerfile
    assert 'ENTRYPOINT ["/docker-entrypoint.sh"]' in dockerfile


def test_single_container_entrypoint_starts_edge_only_for_launcher():
    script = (ROOT / "container" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "lexaegis.cli" in script
    assert "edge --start" in script
    assert "LEX_DEMO_LIVE_EDGE_REVIEW=1" in script
    assert 'exec "$@"' in script
