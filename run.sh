#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sh/common.sh"

"${ROOT_DIR}/sh/checkout.sh"
"${ROOT_DIR}/sh/build.sh"
"${ROOT_DIR}/sh/run.sh" --sim base "$@" || true
"${ROOT_DIR}/sh/run.sh" --sim spike "$@"
"${ROOT_DIR}/sh/run.sh" --sim fork "$@"
