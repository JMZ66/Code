#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
python -m bid_review.main "$@"
