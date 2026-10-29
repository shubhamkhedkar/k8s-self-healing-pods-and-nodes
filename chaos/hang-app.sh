#!/usr/bin/env bash
# Make /healthz block. Liveness (3 x 5s timeouts) fails => kubelet kills + restarts the container.
source "$(dirname "$0")/lib.sh"; guard_context
POD="${1:-$(first_pod)}"
echo "Hanging $POD"; pod_post "$POD" /hang
kubectl -n "$NS" get events --watch-only --field-selector involvedObject.name="$POD" &
EV=$!; trap 'kill $EV 2>/dev/null || true' EXIT
sleep 25
watch_recovery 120
kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].restartCount}{" restart(s)\n"}'
