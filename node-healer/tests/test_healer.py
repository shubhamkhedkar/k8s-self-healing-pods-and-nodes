from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException
from node_healer import drain, replace
from node_healer.config import Config
from node_healer.controller import ANNOTATION, NodeHealer
from node_healer.health import unhealthy_reason

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def cond(type_, status, minutes_ago=10):
    return NS(type=type_, status=status, last_transition_time=NOW - timedelta(minutes=minutes_ago))


def make_node(name="n1", ready="True", minutes_ago=10, labels=None, extra=None, provider="aws:///ap-south-1a/i-0abc123", annotations=None):
    return NS(
        metadata=NS(name=name, labels=labels or {}, annotations=annotations or {}, uid="u-" + name,
                    creation_timestamp=NOW - timedelta(days=1)),
        spec=NS(provider_id=provider),
        status=NS(conditions=[cond("Ready", ready, minutes_ago)] + (extra or [])),
    )


def make_pod(name, ns="default", owner=None, mirror=False, deleting=False, phase="Running"):
    return NS(
        metadata=NS(name=name, namespace=ns, annotations={"kubernetes.io/config.mirror": "x"} if mirror else {},
                    owner_references=[NS(kind=owner)] if owner else [],
                    deletion_timestamp=NOW if deleting else None),
        status=NS(phase=phase),
    )


def cfg(**kw):
    base = dict(not_ready_threshold_seconds=300, cooldown_seconds=0, dry_run=False)
    base.update(kw)
    return Config(**base)


# ---------------------------------------------------------------- health
def test_ready_node_is_healthy():
    assert unhealthy_reason(make_node(ready="True"), cfg(), NOW) is None


def test_notready_below_threshold_is_ignored():
    assert unhealthy_reason(make_node(ready="False", minutes_ago=2), cfg(), NOW) is None


def test_notready_past_threshold():
    assert "NotReady" in unhealthy_reason(make_node(ready="Unknown", minutes_ago=6), cfg(), NOW)


def test_excluded_label_and_control_plane_never_touched():
    assert unhealthy_reason(make_node(ready="False", labels={"node-healer.io/ignore": "true"}), cfg(), NOW) is None
    assert unhealthy_reason(make_node(ready="False", labels={"node-role.kubernetes.io/control-plane": ""}), cfg(), NOW) is None


def test_npd_condition_triggers_even_if_ready():
    node = make_node(ready="True", extra=[cond("KernelDeadlock", "True", 10)])
    assert "KernelDeadlock" in unhealthy_reason(node, cfg(), NOW)


def test_npd_condition_false_is_fine():
    node = make_node(ready="True", extra=[cond("KernelDeadlock", "False", 10)])
    assert unhealthy_reason(node, cfg(), NOW) is None


# ---------------------------------------------------------------- config
def test_config_defaults_are_safe():
    c = Config.from_env({})
    assert c.dry_run is True and c.replace_mode == "none"


def test_config_env_parsing_and_validation():
    c = Config.from_env({"DRY_RUN": "false", "REPLACE_MODE": "delete-node", "BAD_CONDITIONS": "A, B"})
    assert c.dry_run is False and c.bad_conditions == ("A", "B")
    with pytest.raises(ValueError):
        Config.from_env({"REPLACE_MODE": "rm-rf"})


# ---------------------------------------------------------------- drain
def test_drain_skips_daemonset_and_mirror_pods():
    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value.items = [
        make_pod("web"), make_pod("npd", owner="DaemonSet"), make_pod("etcd", mirror=True), make_pod("done", phase="Succeeded"),
    ]
    assert [p.metadata.name for p in drain.evictable_pods(core, "n1")] == ["web"]


def test_drain_uses_eviction_api_never_delete():
    core = MagicMock()
    pods = [make_pod("a"), make_pod("b")]
    core.list_pod_for_all_namespaces.side_effect = [NS(items=pods), NS(items=[])]
    ok = drain.drain(core, "n1", node_is_ready=True, timeout_seconds=60, sleep=lambda s: None)
    assert ok and core.create_namespaced_pod_eviction.call_count == 2
    core.delete_namespaced_pod.assert_not_called()


def test_drain_retries_when_pdb_blocks_then_succeeds():
    core = MagicMock()
    pod = make_pod("a")
    core.list_pod_for_all_namespaces.side_effect = [NS(items=[pod]), NS(items=[pod]), NS(items=[])]
    core.create_namespaced_pod_eviction.side_effect = [ApiException(status=429), None]
    ok = drain.drain(core, "n1", node_is_ready=True, timeout_seconds=60, sleep=lambda s: None)
    assert ok and core.create_namespaced_pod_eviction.call_count == 2


def test_drain_times_out_when_pdb_never_allows():
    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value = NS(items=[make_pod("a")])
    core.create_namespaced_pod_eviction.side_effect = ApiException(status=429)
    t = iter(range(0, 1000, 100))
    ok = drain.drain(core, "n1", node_is_ready=True, timeout_seconds=250, sleep=lambda s: None, monotonic=lambda: next(t))
    assert ok is False


def test_drain_dead_node_done_once_pods_have_deletion_timestamp():
    core = MagicMock()
    core.list_pod_for_all_namespaces.side_effect = [NS(items=[make_pod("a")]), NS(items=[make_pod("a", deleting=True)])]
    ok = drain.drain(core, "n1", node_is_ready=False, timeout_seconds=60, sleep=lambda s: None)
    assert ok


def test_drain_reraises_unexpected_api_errors():
    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value = NS(items=[make_pod("a")])
    core.create_namespaced_pod_eviction.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        drain.drain(core, "n1", node_is_ready=True, timeout_seconds=60, sleep=lambda s: None)


# ---------------------------------------------------------------- replace
def test_instance_id_parsing():
    assert replace.instance_id_from_provider_id("aws:///ap-south-1a/i-0abc123") == "i-0abc123"
    assert replace.instance_id_from_provider_id("kind://docker/kind/worker") is None
    assert replace.instance_id_from_provider_id(None) is None


def test_aws_asg_terminate_keeps_desired_capacity():
    asg = MagicMock()
    iid = replace.aws_asg_terminate(make_node(), "ap-south-1", autoscaling=asg)
    assert iid == "i-0abc123"
    asg.terminate_instance_in_auto_scaling_group.assert_called_once_with(InstanceId="i-0abc123", ShouldDecrementDesiredCapacity=False)


def test_aws_asg_terminate_rejects_non_aws_node():
    with pytest.raises(ValueError):
        replace.aws_asg_terminate(make_node(provider="kind://x"), "ap-south-1", autoscaling=MagicMock())


# ---------------------------------------------------------------- controller
def healer(core, **kw):
    asg = kw.pop("autoscaling", None)
    return NodeHealer(core, cfg(**kw), now=lambda: NOW, sleep=lambda s: None, autoscaling=asg)


def core_with(nodes, pods=()):
    core = MagicMock()
    core.list_node.return_value = NS(items=nodes)
    core.list_pod_for_all_namespaces.return_value = NS(items=list(pods))
    return core


def three_nodes(bad_ready="Unknown"):
    return [make_node("bad", ready=bad_ready, minutes_ago=10), make_node("g1"), make_node("g2")]


def test_dry_run_default_makes_no_mutations():
    core = core_with(three_nodes(), [make_pod("a")])
    acted = healer(core, dry_run=True, replace_mode="delete-node").reconcile()
    assert acted == ["bad"]
    core.patch_node.assert_not_called()
    core.create_namespaced_pod_eviction.assert_not_called()
    core.delete_node.assert_not_called()


def test_no_unhealthy_nodes_no_action():
    core = core_with([make_node("a"), make_node("b")])
    assert healer(core).reconcile() == []
    core.patch_node.assert_not_called()


def test_cordon_and_drain_happens_before_replace():
    core = core_with(three_nodes(), [make_pod("a")])
    calls = []
    core.patch_node.side_effect = lambda *a, **k: calls.append("patch")
    core.create_namespaced_pod_eviction.side_effect = lambda *a, **k: calls.append("evict")
    core.delete_node.side_effect = lambda *a, **k: calls.append("delete")
    # after eviction the pod carries a deletionTimestamp (dead node)
    core.list_pod_for_all_namespaces.side_effect = [NS(items=[make_pod("a")]), NS(items=[make_pod("a")]), NS(items=[make_pod("a", deleting=True)])]
    healer(core, replace_mode="delete-node").reconcile()
    assert calls[0] == "patch" and calls.index("evict") < calls.index("delete")
    core.patch_node.assert_any_call("bad", {"spec": {"unschedulable": True}})


def test_replace_none_leaves_node_cordoned_only():
    core = core_with(three_nodes(), [])
    healer(core, replace_mode="none").reconcile()
    core.patch_node.assert_any_call("bad", {"spec": {"unschedulable": True}})
    core.delete_node.assert_not_called()


def test_pdb_blocked_drain_prevents_replacement():
    core = core_with(three_nodes(bad_ready="False"), [make_pod("a")])
    core.create_namespaced_pod_eviction.side_effect = ApiException(status=429)
    t = iter(range(0, 100000, 400))
    h = NodeHealer(core, cfg(replace_mode="delete-node", drain_timeout_seconds=300), now=lambda: NOW,
                   sleep=lambda s: None, monotonic=lambda: next(t))
    h.reconcile()
    core.delete_node.assert_not_called()


def test_asg_terminate_mode_calls_aws():
    core = core_with(three_nodes(), [])
    asg = MagicMock()
    healer(core, replace_mode="aws-asg-terminate", autoscaling=asg).reconcile()
    asg.terminate_instance_in_auto_scaling_group.assert_called_once()


def test_refuses_when_too_many_nodes_unhealthy():
    nodes = [make_node("a", ready="False"), make_node("b", ready="False"), make_node("c")]
    core = core_with(nodes)
    assert healer(core, replace_mode="delete-node").reconcile() == []
    core.patch_node.assert_not_called()


def test_cooldown_limits_consecutive_remediations():
    nodes = [make_node("a", ready="False"), make_node("b"), make_node("c"), make_node("d")]
    core = core_with(nodes)
    clock = iter([0, 0, 0, 0, 10, 10, 10])
    h = NodeHealer(core, cfg(cooldown_seconds=600), now=lambda: NOW, sleep=lambda s: None, monotonic=lambda: next(clock))
    assert h.reconcile() == ["a"]
    assert h.reconcile() == []  # still in cooldown


def test_already_remediated_node_not_reprocessed_when_mode_none():
    nodes = [make_node("a", ready="False", annotations={ANNOTATION: "x"}), make_node("b"), make_node("c")]
    core = core_with(nodes)
    assert healer(core).reconcile() == []


def test_event_failure_is_swallowed():
    core = core_with(three_nodes(), [])
    core.create_namespaced_event.side_effect = RuntimeError("forbidden")
    assert healer(core).reconcile() == ["bad"]
