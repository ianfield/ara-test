#!/bin/bash
# Run pytest against ara simulation libraries.
#
# Usage:
#   ./sh/run.sh --sim spike                          # ISA reference
#   ./sh/run.sh --sim base                           # upstream RTL
#   ./sh/run.sh --sim fork                           # patched RTL
#   ./sh/run.sh --sim fork -k test_return_zero       # filter tests
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# Require --sim
if ! printf '%s\n' "$@" | grep -q -- '--sim'; then
    echo "error: --sim is required (spike, base, fork)" >&2
    echo "usage: $0 --sim {spike|base|fork} [pytest args...]" >&2
    exit 1
fi

# Extract backend name for banner
sim_name=""
next=0
for a in "$@"; do
    if [ "$next" = 1 ]; then sim_name="$a"; break; fi
    [ "$a" = "--sim" ] && next=1
done

cd "${ROOT_DIR}"
echo ""
echo "=== [${sim_name}] ==="
exec pytest tests/ "$@"
