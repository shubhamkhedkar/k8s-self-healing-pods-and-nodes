from __future__ import annotations

import os
from dataclasses import dataclass, field

REPLACE_MODES = ("none", "delete-node", "aws-asg-terminate")


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Safety: the healer only *logs* what it would do unless DRY_RUN=false.
    dry_run: bool = True
    # A node must be NotReady (or carry a bad NPD condition) for this long before we act.
    not_ready_threshold_seconds: int = 300
    poll_interval_seconds: int = 30
    # How long we keep retrying evictions that a PodDisruptionBudget refuses (HTTP 429).
    drain_timeout_seconds: int = 300
    # none | delete-node | aws-asg-terminate
    replace_mode: str = "none"
    # Never act if more than this fraction of nodes is unhealthy (likely a control-plane/network incident).
    max_unhealthy_fraction: float = 0.34
    # Minimum seconds between two remediations (limits blast radius).
    cooldown_seconds: int = 600
    # Nodes carrying this label are never touched (e.g. control plane / stateful pool).
    exclude_label: str = "node-healer.io/ignore"
    # NPD conditions (status True) that mark a node unhealthy, even if kubelet still says Ready.
    bad_conditions: tuple[str, ...] = ("KernelDeadlock", "ReadonlyFilesystem", "FrequentKubeletRestart")
    metrics_port: int = 9102
    aws_region: str = field(default="ap-south-1")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = os.environ if env is None else env
        cfg = cls(
            dry_run=_bool(e.get("DRY_RUN"), True),
            not_ready_threshold_seconds=int(e.get("NOT_READY_THRESHOLD_SECONDS", 300)),
            poll_interval_seconds=int(e.get("POLL_INTERVAL_SECONDS", 30)),
            drain_timeout_seconds=int(e.get("DRAIN_TIMEOUT_SECONDS", 300)),
            replace_mode=e.get("REPLACE_MODE", "none"),
            max_unhealthy_fraction=float(e.get("MAX_UNHEALTHY_FRACTION", 0.34)),
            cooldown_seconds=int(e.get("COOLDOWN_SECONDS", 600)),
            exclude_label=e.get("EXCLUDE_LABEL", "node-healer.io/ignore"),
            bad_conditions=tuple(
                c.strip()
                for c in e.get("BAD_CONDITIONS", "KernelDeadlock,ReadonlyFilesystem,FrequentKubeletRestart").split(",")
                if c.strip()
            ),
            metrics_port=int(e.get("METRICS_PORT", 9102)),
            aws_region=e.get("AWS_REGION", "ap-south-1"),
        )
        if cfg.replace_mode not in REPLACE_MODES:
            raise ValueError(f"REPLACE_MODE must be one of {REPLACE_MODES}, got {cfg.replace_mode!r}")
        if not 0 < cfg.max_unhealthy_fraction <= 1:
            raise ValueError("MAX_UNHEALTHY_FRACTION must be in (0, 1]")
        return cfg
