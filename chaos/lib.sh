#!/usr/bin/env bash
# Shared helpers for the chaos scripts. Everything targets the *current* kubectl context:
# only ever run these against a disposable demo cluster (kind-self-healing).
set -euo pipefail
NS="${NS:-self-healing}"
APP_LABEL="app.kubernetes.io/name=demo-app"

need() { command -v "$1" >/dev/null || { echo "missing dependency: $1" >&2; exit 1; }; }
need kubectl

guard_context() {
  local ctx; ctx="$(kubectl config current-context)"
  if [[ "$ctx" != kind-* && "${I_KNOW_WHAT_IM_DOING:-}" != "yes" ]]; then
    echo "Refusing to run chaos against context '$ctx' (not a kind cluster)." >&2
    echo "Set I_KNOW_WHAT_IM_DOING=yes to override." >&2
    exit 1
  fi
}

pods()      { kubectl -n "$NS" get pods -l "$APP_LABEL" -o wide; }
pod_names() { kubectl -n "$NS" get pods -l "$APP_LABEL" -o jsonpath='{.items[*].metadata.name}'; }
first_pod() { kubectl -n "$NS" get pods -l "$APP_LABEL" -o jsonpath='{.items[0].metadata.name}'; }

# POST to an endpoint inside a pod (the image has python, not curl).
pod_post() {  # pod path
  kubectl -n "$NS" exec "$1" -- python -c \
    "import urllib.request as u; print(u.urlopen(u.Request('http://127.0.0.1:8080$2', method='POST')).read().decode())"
}

ready_count() {
  kubectl -n "$NS" get deploy demo-app -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true
}

# Poll until the Deployment has all replicas Ready again; prints a timeline.
watch_recovery() {  # [timeout_seconds]
  local timeout="${1:-180}" start now want ready
  start=$(date +%s)
  want=$(kubectl -n "$NS" get deploy demo-app -o jsonpath='{.spec.replicas}')
  echo "--- watching recovery (want $want Ready, timeout ${timeout}s)"
  while true; do
    now=$(date +%s); ready=$(ready_count); ready=${ready:-0}
    printf '[+%3ss] ready=%s/%s  restarts=%s\n' "$((now-start))" "$ready" "$want" \
      "$(kubectl -n "$NS" get pods -l "$APP_LABEL" -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount} {end}')"
    if [[ "$ready" == "$want" && $((now-start)) -ge 3 ]]; then
      echo "RECOVERED in $((now-start))s"; return 0
    fi
    if (( now-start > timeout )); then echo "TIMEOUT waiting for recovery"; return 1; fi
    sleep 3
  done
}
