"""LEX_EDGE_REQUEST_TIMEOUT / LEX_EDGE_EXTRACT_CHUNK_*: opt-in knobs for CPU-only hosts.

Unset (default) must behave exactly as before: 120 s per edge call, 14000 chars / 8 blocks per batch.
"""
import pytest

from lexaegis import providers
from lexaegis.providers import EdgeClient, edge_request_timeout
from lexaegis.worker import (
    EXTRACT_CHUNK_BLOCKS, EXTRACT_CHUNK_CHARS, chunk_extract_blocks,
    extract_chunk_blocks, extract_chunk_chars,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LEX_EDGE_REQUEST_TIMEOUT", "LEX_EDGE_EXTRACT_CHUNK_CHARS", "LEX_EDGE_EXTRACT_CHUNK_BLOCKS"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_unchanged():
    assert edge_request_timeout() == 120
    assert extract_chunk_chars() == EXTRACT_CHUNK_CHARS == 14000
    assert extract_chunk_blocks() == EXTRACT_CHUNK_BLOCKS == 8


def test_timeout_env_overrides_and_is_clamped(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", "900")
    assert edge_request_timeout() == 900
    monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", "1")
    assert edge_request_timeout() == 10
    monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", "999999")
    assert edge_request_timeout() == 3600
    monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", "soon")
    assert edge_request_timeout() == 120
    monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", "")
    assert edge_request_timeout() == 120


def test_chunk_env_overrides_and_is_clamped(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_CHARS", "4000")
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_BLOCKS", "3")
    assert (extract_chunk_chars(), extract_chunk_blocks()) == (4000, 3)
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_CHARS", "10")
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_BLOCKS", "0")
    assert (extract_chunk_chars(), extract_chunk_blocks()) == (500, 1)
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_CHARS", "x")
    assert extract_chunk_chars() == 14000


def test_chunking_follows_env_and_explicit_arguments_still_win(monkeypatch):
    blocks = [{"id": f"b{i}", "text": "文" * 1000} for i in range(10)]
    assert [len(b) for b in chunk_extract_blocks(blocks)] == [8, 2]          # defaults: 8 blocks
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_CHARS", "2500")
    sizes = [sum(len(x["text"]) for x in batch) for batch in chunk_extract_blocks(blocks)]
    assert max(sizes) <= 2500 and sum(sizes) == 10000
    assert [len(b) for b in chunk_extract_blocks(blocks, max_chars=14000, max_blocks=4)] == [4, 4, 2]


def test_oversized_single_block_is_never_split(monkeypatch):
    monkeypatch.setenv("LEX_EDGE_EXTRACT_CHUNK_CHARS", "500")
    batches = chunk_extract_blocks([{"id": "big", "text": "文" * 3000}, {"id": "s", "text": "短"}])
    assert [[b["id"] for b in batch] for batch in batches] == [["big"], ["s"]]


class _Captured(Exception):
    pass


@pytest.mark.parametrize("call", ["extract", "review_outbound", "draft_review"])
def test_timeout_reaches_the_http_client(monkeypatch, call):
    seen = []

    class Spy:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise _Captured

    monkeypatch.setattr(providers.httpx, "Client", Spy)
    client = EdgeClient("http://edge-model:8080/v1", "edge-small")
    args = {
        "extract": ([{"id": "b1", "text": "文本"}],),
        "review_outbound": ([{"id": "f1", "field": "event", "text": "x"}],),
        "draft_review": ([{"id": "f1", "field": "event", "text": "x"}], [{"id": "s1"}], [{"id": "c1"}]),
    }[call]
    for env, expected in ((None, 120), ("900", 900)):
        if env is None:
            monkeypatch.delenv("LEX_EDGE_REQUEST_TIMEOUT", raising=False)
        else:
            monkeypatch.setenv("LEX_EDGE_REQUEST_TIMEOUT", env)
        with pytest.raises(_Captured):
            getattr(client, call)(*args)
        assert seen[-1] == expected
    with pytest.raises(_Captured):                                   # an explicit timeout still wins
        getattr(client, call)(*args, timeout=33)
    assert seen[-1] == 33
