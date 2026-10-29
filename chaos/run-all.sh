#!/usr/bin/env bash
# Run the full pod-level chaos suite in order (node failure is separate: it is slower and noisier).
set -euo pipefail
cd "$(dirname "$0")"
for s in kill-pods crash-app hang-app unready-app; do
  echo; echo "================ $s ================"; ./$s.sh
done
