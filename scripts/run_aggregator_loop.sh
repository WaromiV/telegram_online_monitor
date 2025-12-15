#!/usr/bin/env sh
set -euo pipefail

INTERVAL="${AGGREGATE_INTERVAL_SECONDS:-600}"

echo "[aggregator-loop] starting with interval=${INTERVAL}s"
while true; do
  echo "[aggregator-loop] running aggregation"
  python -m unhinged_spyware.aggregator || echo "[aggregator-loop] aggregation failed, will retry after sleep"
  echo "[aggregator-loop] sleeping for ${INTERVAL}s"
  sleep "${INTERVAL}"
done
