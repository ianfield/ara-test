#!/bin/bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

DEPS_DIR="${ROOT_DIR}/repo/deps"

# ── Clone repos ───────────────────────────────────────────────────

clone_repo() {
    local name="$1"
    local url="$2"
    local dir="${ROOT_DIR}/repo/${name}"
    shift 2

    if [ ! -d "${dir}" ]; then
        git clone "$@" "${url}" "${dir}"
    else
        echo "[skip] ${name} already cloned"
    fi
}

clone_repo "ara-base" "https://github.com/pulp-platform/ara.git" --single-branch --branch main
clone_repo "ara-fork" "https://github.com/ianfield/ara.git"
clone_repo "spike"    "https://github.com/riscv-software-src/riscv-isa-sim.git"

# ── Fetch deps from Bender.lock (shallow, pinned revisions) ──────

# Only fetch deps we actually use in the build
NEEDED_DEPS="axi common_cells cva6 fpnew fpu_div_sqrt_mvp tech_cells_generic"

if [ ! -d "${DEPS_DIR}/cva6" ]; then
    echo "[deps] Fetching shared dependencies (shallow, pinned)..."
    mkdir -p "${DEPS_DIR}"

    LOCK_FILE="${ROOT_DIR}/repo/ara-base/Bender.lock"
    if [ ! -f "${LOCK_FILE}" ]; then
        echo "error: ${LOCK_FILE} not found" >&2
        exit 1
    fi

    # Parse Bender.lock YAML: extract package name, Git URL, and revision.
    # Format:
    #   <name>:
    #     revision: <sha>
    #     ...
    #     source:
    #       Git: <url>
    current_pkg=""
    current_rev=""
    current_url=""
    while IFS= read -r line; do
        # Package name (top-level key, no leading whitespace)
        if [[ "$line" =~ ^[[:space:]]{2}([a-z_][a-z0-9_-]*):$ ]]; then
            # Flush previous package
            if [[ -n "$current_pkg" && -n "$current_rev" && -n "$current_url" ]]; then
                for need in $NEEDED_DEPS; do
                    if [ "$need" = "$current_pkg" ]; then
                        dep_dir="${DEPS_DIR}/${current_pkg}"
                        if [ ! -d "${dep_dir}" ]; then
                            echo "  [clone] ${current_pkg} @ ${current_rev:0:12}"
                            git clone --depth 1 "${current_url}" "${dep_dir}" 2>/dev/null
                            git -C "${dep_dir}" fetch --depth 1 origin "${current_rev}" 2>/dev/null
                            git -C "${dep_dir}" checkout "${current_rev}" 2>/dev/null
                        fi
                        break
                    fi
                done
            fi
            current_pkg="${BASH_REMATCH[1]}"
            current_rev=""
            current_url=""
        fi
        if [[ "$line" =~ revision:[[:space:]]+([0-9a-f]+) ]]; then
            current_rev="${BASH_REMATCH[1]}"
        fi
        if [[ "$line" =~ Git:[[:space:]]+(https://[^ ]+) ]]; then
            current_url="${BASH_REMATCH[1]}"
        fi
    done < "${LOCK_FILE}"

    # Flush last package
    if [[ -n "$current_pkg" && -n "$current_rev" && -n "$current_url" ]]; then
        for need in $NEEDED_DEPS; do
            if [ "$need" = "$current_pkg" ]; then
                dep_dir="${DEPS_DIR}/${current_pkg}"
                if [ ! -d "${dep_dir}" ]; then
                    echo "  [clone] ${current_pkg} @ ${current_rev:0:12}"
                    git clone --depth 1 "${current_url}" "${dep_dir}" 2>/dev/null
                    git -C "${dep_dir}" fetch --depth 1 origin "${current_rev}" 2>/dev/null
                    git -C "${dep_dir}" checkout "${current_rev}" 2>/dev/null
                fi
                break
            fi
        done
    fi

    echo "[deps] Done"
else
    echo "[skip] Shared deps already present"
fi

# ── Apply patches to shared deps ──────────────────────────────

for p in "${ROOT_DIR}/patches"/*.patch; do
    [ -f "$p" ] || continue
    if patch -d "${DEPS_DIR}" -p1 --forward --batch < "$p" >/dev/null 2>&1; then
        echo "[patch] $(basename "$p")"
    fi
done

echo "[done] Repos and deps ready"
