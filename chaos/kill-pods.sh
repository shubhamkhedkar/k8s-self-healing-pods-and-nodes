#!/usr/bin/env bash
# Delete random demo-app pods (default 2 of 3). ReplicaSet recreates them; the PDB does NOT apply to
# direct deletes, but the Service keeps serving from the surviving replica(s).
source "$(dirname "$0")/lib.sh"; guard_context
COUNT="${1:-2}"
echo "Before:"; pods
victims=$(kubectl -n "$NS" get pods -l "$APP_LABEL" -o name | shuf -n "$COUNT")
echo "Deleting: $victims"
# shellcheck disable=SC2086
kubectl -n "$NS" delete $victims --wait=false
watch_recovery 120
pods
