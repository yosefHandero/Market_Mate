#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${SCANNER_DIR}"
python -m app.worker
