import json

import httpx

from scripts.fetch_eval_data import SOURCES, fetch_dataset, sha256


def test_pinned_cache_detects_modified_corpus(tmp_path, monkeypatch):
    monkeypatch.setitem(
        SOURCES,
        "test",
        {
            "repository": "owner/data",
            "revision": "fixedsha",
            "license": "MIT",
            "files": {"sample.json": "sample.json"},
        },
    )
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b'{"verified":true}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = fetch_dataset("test", tmp_path, client)
        repeated = fetch_dataset("test", tmp_path, client)
        assert len(calls) == 1
        assert repeated == first
        path = tmp_path / "test" / "sample.json"
        path.write_text("corrupted")
        recovered = fetch_dataset("test", tmp_path, client)
    assert len(calls) == 2
    assert json.loads(path.read_text()) == {"verified": True}
    assert first["files"][0]["sha256"] == recovered["files"][0]["sha256"] == sha256(path)
    assert "/fixedsha/" in calls[0]
