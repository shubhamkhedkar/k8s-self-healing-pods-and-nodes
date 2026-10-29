#!/usr/bin/env bash
# Readiness failure: the pod stays running (no restart) but is removed from the Service endpoints.
source "$(dirname "$0")/lib.sh"; guard_context
POD="${1:-$(first_pod)}"
pod_post "$POD" /unready
sleep 8
echo "Endpoints now (should list 2 of 3 pods):"
kubectl -n "$NS" get endpointslices -l kubernetes.io/service-name=demo-app -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{" ready="}{.conditions.ready}{"\n"}{end}'
echo "Recovering $POD"; pod_post "$POD" /recover
watch_recovery 60
