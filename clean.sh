#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sh/common.sh"
"${ROOT_DIR}/sh/clean.sh"
