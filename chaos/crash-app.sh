#!/usr/bin/env bash
# Make one pod's process exit(1). kubelet restarts the *container* (restartCount +1, same pod, same node).
source "$(dirname "$0")/lib.sh"; guard_context
POD="${1:-$(first_pod)}"
echo "Crashing $POD"; pod_post "$POD" /crash || true
watch_recovery 120
kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].restartCount}{" restart(s), last state: "}{.status.containerStatuses[0].lastState.terminated.reason}{"\n"}'
