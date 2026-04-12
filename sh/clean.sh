#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
rm -rf "${ROOT_DIR}/repo" "${ROOT_DIR}/build" "${ROOT_DIR}/install" "${ROOT_DIR}/run"
