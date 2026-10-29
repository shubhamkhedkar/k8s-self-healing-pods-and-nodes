"""Pure functions that decide whether a node is unhealthy. No I/O, trivial to test."""
from __future__ import annotations

from datetime import UTC, datetime

from .config import Config


def _cond(node, type_: str):
    for c in node.status.conditions or []:
        if c.type == type_:
            return c
    return None


def unhealthy_reason(node, cfg: Config, now: datetime) -> str | None:
    """Return a human readable reason if the node has been unhealthy longer than the threshold."""
    labels = node.metadata.labels or {}
    if cfg.exclude_label in labels or "node-role.kubernetes.io/control-plane" in labels:
        return None

    ready = _cond(node, "Ready")
    if ready is None:
        # No Ready condition at all: kubelet never reported. Use creation time as the clock.
        since = node.metadata.creation_timestamp
        status = "Missing"
    else:
        since = ready.last_transition_time or node.metadata.creation_timestamp
        status = ready.status
    if status != "True" and since is not None:
        age = (now - _aware(since)).total_seconds()
        if age >= cfg.not_ready_threshold_seconds:
            return f"NotReady (Ready={status}) for {int(age)}s >= {cfg.not_ready_threshold_seconds}s"

    for name in cfg.bad_conditions:
        c = _cond(node, name)
        if c is not None and c.status == "True":
            since = c.last_transition_time or now
            age = (now - _aware(since)).total_seconds()
            if age >= cfg.not_ready_threshold_seconds:
                return f"NPD condition {name}=True for {int(age)}s"
    return None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
