"""Node replacement strategies. All of them are no-ops in dry-run mode (handled by the caller)."""
from __future__ import annotations

import logging

from kubernetes import client

log = logging.getLogger("node-healer.replace")


def instance_id_from_provider_id(provider_id: str | None) -> str | None:
    """aws:///ap-south-1a/i-0abc123 -> i-0abc123"""
    if not provider_id or not provider_id.startswith("aws://"):
        return None
    tail = provider_id.rsplit("/", 1)[-1]
    return tail if tail.startswith("i-") else None


def delete_node(core: client.CoreV1Api, node) -> None:
    """Remove the Node object. Pods are garbage collected, and a cloud controller / autoscaler
    notices the missing instance and brings capacity back."""
    core.delete_node(node.metadata.name)


def aws_asg_terminate(node, region: str, autoscaling=None) -> str:
    """Terminate the EC2 instance through its Auto Scaling group; the ASG launches a replacement
    (ShouldDecrementDesiredCapacity=False keeps the group size constant)."""
    instance_id = instance_id_from_provider_id(node.spec.provider_id)
    if instance_id is None:
        raise ValueError(f"node {node.metadata.name} has no AWS providerID ({node.spec.provider_id!r})")
    if autoscaling is None:
        import boto3  # imported lazily: only needed for this mode

        autoscaling = boto3.client("autoscaling", region_name=region)
    autoscaling.terminate_instance_in_auto_scaling_group(InstanceId=instance_id, ShouldDecrementDesiredCapacity=False)
    return instance_id
