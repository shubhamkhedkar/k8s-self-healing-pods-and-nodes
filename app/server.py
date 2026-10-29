"""Tiny Flask service used to demonstrate Kubernetes pod self-healing.

Endpoints
---------
GET  /            -> hello + pod name
GET  /healthz     -> liveness   (200 unless the process is "hung"; hang => blocks)
GET  /ready       -> readiness  (503 while warming up or when toggled unready)
GET  /metrics     -> Prometheus metrics

Chaos endpoints (only when CHAOS_ENABLED=true, which the demo manifests set):
POST /crash       -> exits the process with code 1 shortly after replying
POST /hang        -> /healthz starts blocking => liveness probe times out => kubelet restarts container
POST /unready     -> /ready returns 503 => pod removed from Service endpoints (no restart)
POST /recover     -> clear hang/unready flags
"""
from __future__ import annotations

import os
import socket
import threading
import time

from flask import Flask, Response, jsonify
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

POD_NAME = os.getenv("POD_NAME", socket.gethostname())
STARTUP_DELAY = float(os.getenv("STARTUP_DELAY_SECONDS", "5"))
CHAOS_ENABLED = os.getenv("CHAOS_ENABLED", "false").lower() == "true"
HANG_SECONDS = float(os.getenv("HANG_SECONDS", "3600"))

_started_at = time.monotonic()


class State:
    """Mutable process state, guarded by a lock (gunicorn runs 1 worker, N threads)."""

    def __init__(self) -> None:
        self.hung = False
        self.unready = False
        self.lock = threading.Lock()


state = State()

REQUESTS = Counter("demo_requests_total", "HTTP requests", ["path"])
HUNG = Gauge("demo_hung", "1 if the app is simulating a hang")
UNREADY = Gauge("demo_unready", "1 if the app is simulating unreadiness")


def create_app() -> Flask:
    app = Flask(__name__)

    def warmed_up() -> bool:
        return (time.monotonic() - _started_at) >= STARTUP_DELAY

    @app.get("/")
    def index():
        REQUESTS.labels("/").inc()
        return jsonify(message="hello from a self-healing pod", pod=POD_NAME)

    @app.get("/healthz")
    def healthz():
        REQUESTS.labels("/healthz").inc()
        if state.hung:
            # Simulate a deadlocked process: the kubelet's probe times out.
            time.sleep(HANG_SECONDS)
        return jsonify(status="ok", pod=POD_NAME)

    @app.get("/ready")
    def ready():
        REQUESTS.labels("/ready").inc()
        if not warmed_up():
            return jsonify(status="warming-up"), 503
        if state.unready:
            return jsonify(status="unready"), 503
        return jsonify(status="ready", pod=POD_NAME)

    @app.get("/metrics")
    def metrics():
        HUNG.set(1 if state.hung else 0)
        UNREADY.set(1 if state.unready else 0)
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    def chaos_guard():
        if not CHAOS_ENABLED:
            return jsonify(error="chaos endpoints disabled"), 403
        return None

    @app.post("/crash")
    def crash():
        denied = chaos_guard()
        if denied:
            return denied
        threading.Timer(0.5, lambda: os._exit(1)).start()
        return jsonify(status="crashing", pod=POD_NAME)

    @app.post("/hang")
    def hang():
        denied = chaos_guard()
        if denied:
            return denied
        state.hung = True
        return jsonify(status="hung", pod=POD_NAME)

    @app.post("/unready")
    def unready():
        denied = chaos_guard()
        if denied:
            return denied
        state.unready = True
        return jsonify(status="unready", pod=POD_NAME)

    @app.post("/recover")
    def recover():
        denied = chaos_guard()
        if denied:
            return denied
        state.hung = False
        state.unready = False
        return jsonify(status="recovered", pod=POD_NAME)

    return app


app = create_app()

if __name__ == "__main__":  # local dev only; containers use gunicorn
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), threaded=True)
