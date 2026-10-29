"""Cordon + PDB-respecting drain using the Eviction API (never a plain pod delete)."""
from __future__ import annotations

import logging
import time
from typing import Callable

from kubernetes import client
from kubernetes.client.rest import ApiException

log = logging.getLogger("node-healer.drain")

MIRROR_ANNOTATION = "kubernetes.io/config.mirror"


def cordon(core: client.CoreV1Api, node_name: str) -> None:
    core.patch_node(node_name, {"spec": {"unschedulable": True}})


def _skip(pod) -> bool:
    """DaemonSet pods and static (mirror) pods are not evicted - same rules as `kubectl drain`."""
    if (pod.metadata.annotations or {}).get(MIRROR_ANNOTATION) is not None:
        return True
    return any(o.kind == "DaemonSet" for o in (pod.metadata.owner_references or []))


def evictable_pods(core: client.CoreV1Api, node_name: str):
    pods = core.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}").items
    return [p for p in pods if not _skip(p) and p.status.phase not in ("Succeeded", "Failed")]


def drain(
    core: client.CoreV1Api,
    node_name: str,
    *,
    node_is_ready: bool,
    timeout_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    retry_interval: float = 5.0,
) -> bool:
    """Evict every evictable pod. Returns True when the node is drained.

    * HTTP 429 from the Eviction API means a PodDisruptionBudget currently forbids the eviction;
      we keep retrying until `timeout_seconds` (the budget recovers once replacement pods are Ready).
    * On a node whose kubelet is dead the pods can never finish terminating. For those nodes we
      consider the drain complete once every pod has a deletionTimestamp - the node object
      deletion (or ASG termination) that follows lets the control plane garbage-collect them.
    """
    deadline = monotonic() + timeout_seconds
    while True:
        remaining = evictable_pods(core, node_name)
        if not node_is_ready:
            remaining = [p for p in remaining if p.metadata.deletion_timestamp is None]
        if not remaining:
            return True
        blocked = 0
        for pod in remaining:
            try:
                core.create_namespaced_pod_eviction(
                    pod.metadata.name,
                    pod.metadata.namespace,
                    client.V1Eviction(metadata=client.V1ObjectMeta(name=pod.metadata.name, namespace=pod.metadata.namespace)),
                )
                log.info("evicted %s/%s from %s", pod.metadata.namespace, pod.metadata.name, node_name)
            except ApiException as e:
                if e.status == 429:
                    blocked += 1
                    log.warning("eviction of %s/%s blocked by PDB; will retry", pod.metadata.namespace, pod.metadata.name)
                elif e.status == 404:
                    continue
                else:
                    raise
        if monotonic() >= deadline:
            log.error("drain of %s timed out with %d pod(s) still blocked", node_name, blocked)
            return False
        sleep(retry_interval)
