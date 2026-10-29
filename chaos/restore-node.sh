#!/usr/bin/env bash
# Undo node-failure.sh: start the kubelet / container again and uncordon the node.
source "$(dirname "$0")/lib.sh"; guard_context; need docker
NODE="${1:?usage: restore-node.sh <kind-node-name>}"
docker start "$NODE" >/dev/null 2>&1 || true
docker exec "$NODE" systemctl start kubelet
echo "waiting for $NODE to re-register ..."
# node-healer may have deleted the Node object: wait for the kubelet to re-register it first
for _ in $(seq 1 60); do kubectl get node "$NODE" >/dev/null 2>&1 && break; sleep 3; done
kubectl wait --for=condition=Ready "node/$NODE" --timeout=180s
kubectl uncordon "$NODE" || true
kubectl get nodes
