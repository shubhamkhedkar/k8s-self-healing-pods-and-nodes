from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Callable

from kubernetes import client
from prometheus_client import Counter, Gauge

from . import drain as drain_mod
from . import replace as replace_mod
from .config import Config
from .health import _cond, unhealthy_reason

log = logging.getLogger("node-healer")

UNHEALTHY_NODES = Gauge("node_healer_unhealthy_nodes", "Nodes currently considered unhealthy")
ACTIONS = Counter("node_healer_actions_total", "Remediation steps", ["action", "result"])

ANNOTATION = "node-healer.io/remediation"


class NodeHealer:
    def __init__(
        self,
        core: client.CoreV1Api,
        cfg: Config,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        autoscaling=None,
    ) -> None:
        self.core, self.cfg = core, cfg
        self._now, self._sleep, self._monotonic = now, sleep, monotonic
        self._autoscaling = autoscaling
        self._last_action: float | None = None

    # ------------------------------------------------------------------ one reconcile pass
    def reconcile(self) -> list[str]:
        """Evaluate all nodes once; returns the names of nodes that were (or would be) remediated."""
        nodes = self.core.list_node().items
        now = self._now()
        unhealthy = [(n, r) for n in nodes if (r := unhealthy_reason(n, self.cfg, now))]
        UNHEALTHY_NODES.set(len(unhealthy))
        if self.cfg.replace_mode == "none":
            # already cordoned+drained by an earlier pass: nothing more this controller would do
            unhealthy = [(n, r) for n, r in unhealthy if ANNOTATION not in (n.metadata.annotations or {})]
        if not unhealthy:
            return []

        fraction = len(unhealthy) / max(len(nodes), 1)
        if fraction > self.cfg.max_unhealthy_fraction:
            log.error(
                "%d/%d nodes unhealthy (%.0f%% > %.0f%%): refusing to act, likely a wider incident",
                len(unhealthy), len(nodes), fraction * 100, self.cfg.max_unhealthy_fraction * 100,
            )
            ACTIONS.labels("remediate", "refused-too-many").inc()
            return []

        if self._last_action is not None and self._monotonic() - self._last_action < self.cfg.cooldown_seconds:
            log.info("cooldown active; skipping remediation this pass")
            ACTIONS.labels("remediate", "cooldown").inc()
            return []

        node, reason = unhealthy[0]  # one node per pass keeps the blast radius small
        self.remediate(node, reason)
        self._last_action = self._monotonic()
        return [node.metadata.name]

    # ------------------------------------------------------------------ remediation
    def remediate(self, node, reason: str) -> None:
        name = node.metadata.name
        ready = _cond(node, "Ready")
        node_ready = bool(ready and ready.status == "True")
        prefix = "[DRY-RUN] would " if self.cfg.dry_run else ""
        log.warning("node %s unhealthy: %s", name, reason)

        log.info("%scordon %s", prefix, name)
        if not self.cfg.dry_run:
            drain_mod.cordon(self.core, name)
            self.core.patch_node(name, {"metadata": {"annotations": {ANNOTATION: reason}}})
            self._event(node, "NodeHealerCordoned", reason)
        ACTIONS.labels("cordon", "dry-run" if self.cfg.dry_run else "done").inc()

        victims = drain_mod.evictable_pods(self.core, name)
        log.info("%sdrain %s (%d pod(s), PDB-respecting eviction)", prefix, name, len(victims))
        if not self.cfg.dry_run:
            ok = drain_mod.drain(
                self.core, name, node_is_ready=node_ready,
                timeout_seconds=self.cfg.drain_timeout_seconds,
                sleep=self._sleep, monotonic=self._monotonic,
            )
            ACTIONS.labels("drain", "done" if ok else "timeout").inc()
            if not ok:
                self._event(node, "NodeHealerDrainTimeout", "PDB blocked drain; not replacing node", "Warning")
                return  # never replace a node we could not drain safely
        else:
            ACTIONS.labels("drain", "dry-run").inc()

        mode = self.cfg.replace_mode
        if mode == "none":
            log.info("replace_mode=none: node left cordoned+drained for manual/ASG handling")
            return
        log.info("%sreplace %s via %s", prefix, name, mode)
        if self.cfg.dry_run:
            ACTIONS.labels("replace", "dry-run").inc()
            return
        if mode == "delete-node":
            replace_mod.delete_node(self.core, node)
        elif mode == "aws-asg-terminate":
            iid = replace_mod.aws_asg_terminate(node, self.cfg.aws_region, self._autoscaling)
            log.info("terminated instance %s via ASG", iid)
        ACTIONS.labels("replace", "done").inc()
        self._event(node, "NodeHealerReplaced", f"replaced using {mode}")

    def _event(self, node, reason: str, message: str, type_: str = "Normal") -> None:
        try:
            self.core.create_namespaced_event(
                "default",
                client.CoreV1Event(
                    metadata=client.V1ObjectMeta(generate_name="node-healer-"),
                    involved_object=client.V1ObjectReference(kind="Node", name=node.metadata.name, uid=node.metadata.uid),
                    reason=reason, message=message, type=type_,
                    reporting_component="node-healer", source=client.V1EventSource(component="node-healer"),
                ),
            )
        except Exception:  # events are best-effort
            log.debug("could not record event", exc_info=True)

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:  # pragma: no cover - thin loop
        log.info("node-healer started: %s", self.cfg)
        while True:
            try:
                self.reconcile()
            except Exception:
                log.exception("reconcile failed")
                ACTIONS.labels("reconcile", "error").inc()
            self._sleep(self.cfg.poll_interval_seconds)
