import time

import pytest
import server


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(server, "CHAOS_ENABLED", True)
    monkeypatch.setattr(server, "STARTUP_DELAY", 0)
    server.state.hung = False
    server.state.unready = False
    return server.create_app().test_client()


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_ready_warming_up(client, monkeypatch):
    monkeypatch.setattr(server, "STARTUP_DELAY", 3600)
    monkeypatch.setattr(server, "_started_at", time.monotonic())
    assert client.get("/ready").status_code == 503


def test_ready_after_warmup(client):
    assert client.get("/ready").status_code == 200


def test_unready_and_recover(client):
    client.post("/unready")
    assert client.get("/ready").status_code == 503
    client.post("/recover")
    assert client.get("/ready").status_code == 200


def test_hang_blocks_healthz(client, monkeypatch):
    slept = []
    monkeypatch.setattr(server.time, "sleep", lambda s: slept.append(s))
    client.post("/hang")
    client.get("/healthz")
    assert slept, "healthz should block while hung"
    client.post("/recover")
    slept.clear()
    client.get("/healthz")
    assert not slept


def test_crash_exits_process(client, monkeypatch):
    calls = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.fn = fn

        def start(self):
            calls.append(self.fn)

    monkeypatch.setattr(server.threading, "Timer", FakeTimer)
    monkeypatch.setattr(server.os, "_exit", lambda code: calls.append(("exit", code)))
    assert client.post("/crash").status_code == 200
    calls[0]()
    assert ("exit", 1) in calls


def test_chaos_disabled(monkeypatch):
    monkeypatch.setattr(server, "CHAOS_ENABLED", False)
    c = server.create_app().test_client()
    for path in ("/crash", "/hang", "/unready", "/recover"):
        assert c.post(path).status_code == 403


def test_metrics(client):
    assert b"demo_requests_total" in client.get("/metrics").data
