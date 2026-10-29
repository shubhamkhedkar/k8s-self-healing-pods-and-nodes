#!/usr/bin/env bash
# Simulate a server failure on a kind worker (kind nodes are Docker containers).
#   MODE=stop-kubelet (default) systemctl stop kubelet inside the node container  -> node goes NotReady
#   MODE=stop-node             docker stop the whole node container               -> hard power-off
#   MODE=cordon                just cordon+drain (planned maintenance) to show PDB protection
# Then watch: pods rescheduled (tolerationSeconds=30), node-healer logs, node recovery.
source "$(dirname "$0")/lib.sh"; guard_context; need docker
MODE="${MODE:-stop-kubelet}"
NODE="${1:-$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[0].metadata.name}')}"
echo "Target node: $NODE   mode: $MODE"
echo "Pods on node before:"; kubectl get pods -A --field-selector spec.nodeName="$NODE" -o wide

case "$MODE" in
  stop-kubelet) docker exec "$NODE" systemctl stop kubelet ;;
  stop-node)    docker stop "$NODE" ;;
  cordon)
    kubectl cordon "$NODE"
    # `kubectl drain` uses the Eviction API, so the demo-app PDB (minAvailable: 2) is honoured.
    kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=120s
    watch_recovery 120; kubectl uncordon "$NODE"; exit 0 ;;
  *) echo "unknown MODE=$MODE" >&2; exit 1 ;;
esac

echo "--- waiting for the control plane to notice (node-monitor-grace-period ~40s) ..."
for i in $(seq 1 40); do
  st=$(kubectl get node "$NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo gone)
  echo "[+$((i*5))s] node Ready=$st"; [[ "$st" != "True" ]] && break; sleep 5
done
watch_recovery 240    # app pods get rescheduled to healthy nodes
echo "--- node-healer decisions:"
kubectl -n "$NS" logs deploy/node-healer --tail=20 || true
echo
echo "To bring the node back:  ./chaos/restore-node.sh $NODE"
