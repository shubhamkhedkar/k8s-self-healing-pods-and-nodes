#!/usr/bin/env bash
# Extract the rule groups from the PrometheusRule CR and lint them with promtool (optional tool).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v promtool >/dev/null || { echo "promtool not installed - skipping rule lint"; exit 0; }
python3 - <<'PY' > /tmp/self-healing-rules.yaml
import yaml
doc = yaml.safe_load(open("deploy/monitoring/prometheusrule.yaml"))
print(yaml.safe_dump({"groups": doc["spec"]["groups"]}))
PY
promtool check rules /tmp/self-healing-rules.yaml
