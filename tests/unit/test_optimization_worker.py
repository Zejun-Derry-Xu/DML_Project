import pytest

from scripts import run_optimization_validation as worker


def test_worker_pins_current_candidate_source():
    assert worker.candidate_hash() == worker.CANDIDATE_SHA256


def test_smoke_refuses_occupied_port_before_starting_or_writing(monkeypatch):
    def occupied(port):
        assert port == 18620
        raise ValueError("busy")

    def forbidden(*args, **kwargs):
        pytest.fail("Must not start a process on an occupied demo port")

    monkeypatch.setattr(worker, "require_free_port", occupied)
    monkeypatch.setattr(worker.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="busy"):
        worker.live_smoke()
