#!/usr/bin/env bash
set -euo pipefail

PROJ_ROOT=$(git rev-parse --show-toplevel)
if [ -z "${LLVM_RISCV:-}" ]; then
    echo "error: LLVM_RISCV not set." >&2
    exit 1
fi
OBJDUMP="${LLVM_RISCV}/llvm-objdump"

if [[ $# -lt 1 ]]; then
    echo "usage: trace.sh <test_name_or_path>" >&2
    exit 1
fi

arg="$1"; shift
if [[ "$arg" = /* ]]; then
    test_dir="$arg"
else
    test_dir="$PROJ_ROOT/$arg"
fi

for f in hart_0.dasm test.elf; do
    if [[ ! -f "$test_dir/$f" ]]; then
        echo "error: $test_dir/$f not found" >&2
        exit 1
    fi
done

exec python3 "$PROJ_ROOT/tools/trace.py" "$test_dir" --objdump "$OBJDUMP" "$@"
