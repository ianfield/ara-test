#!/bin/bash
# Build Verilator simulation libraries for ara-base and ara-fork.
#
# Produces:
#   install/base/libAra.so  — upstream ara
#   install/fork/libAra.so  — our patched ara
#
# Usage:
#   ./sh/build.sh                # default: DLEN=128 (NrLanes=2)
#   ./sh/build.sh --dlen=1024    # DLEN=1024 (NrLanes=16)
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
SIMS_DIR="${ROOT_DIR}/sims"
DEPS="${ROOT_DIR}/repo/deps"
CVA6="${DEPS}/cva6"

# ---------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------
DLEN=128
OPT=Os
TRACE_DEPTH=0
THREADS=1
for arg in "$@"; do
    case "$arg" in
        --dlen=*) DLEN="${arg#*=}" ;;
        --trace-depth=*) TRACE_DEPTH="${arg#*=}" ;;
        -O*) OPT="${arg#-}" ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

# Validate DLEN: power of 2, 128..1024. NrLanes=1 not supported by ARA.
if [ "$DLEN" -lt 128 ] || [ "$DLEN" -gt 1024 ]; then
    echo "error: --dlen must be 128..1024 (got $DLEN)" >&2
    exit 1
fi
if [ $((DLEN & (DLEN - 1))) -ne 0 ]; then
    echo "error: --dlen must be a power of 2 (got $DLEN)" >&2
    exit 1
fi

NRLANES=$((DLEN / 64))
VLEN=$((DLEN * 16))
echo "[config] DLEN=${DLEN}, VLEN=${VLEN}, NrLanes=${NRLANES}"

# ---------------------------------------------------------------
# Build one variant
# ---------------------------------------------------------------
build_variant() {
    local name="$1"
    local ara="$2"           # path to ara repo root

    local build_dir="${ROOT_DIR}/build/${name}"
    local verilator_dir="${build_dir}/verilator"
    local obj_dir="${build_dir}/obj"
    local install_dir="${ROOT_DIR}/install/sim/${name}"

    echo ""
    echo "=== Building ${name} ==="
    mkdir -p "${verilator_dir}" "${obj_dir}" "${install_dir}"

    # ── Include paths ─────────────────────────────────────────
    local incdirs=(
        -I"${ara}/hardware/include"
        -I"${DEPS}/axi/include"
        -I"${DEPS}/common_cells/include"
        -I"${CVA6}/core/include"
    )

    # ── Packages (order matters) ──────────────────────────────
    local pkgs=(
        "${CVA6}/core/include/config_pkg.sv"
        "${CVA6}/core/include/cv64a6_imafdcv_sv39_config_pkg.sv"
        "${CVA6}/core/include/build_config_pkg.sv"
        "${CVA6}/core/include/riscv_pkg.sv"
        "${CVA6}/core/include/ariane_pkg.sv"
        "${CVA6}/core/include/wt_cache_pkg.sv"
        "${DEPS}/common_cells/src/cf_math_pkg.sv"
        "${DEPS}/fpnew/src/fpnew_pkg.sv"
        "${DEPS}/axi/src/axi_pkg.sv"
        "${DEPS}/fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv"
        "${ara}/hardware/include/rvv_pkg.sv"
        "${ara}/hardware/include/ara_pkg.sv"
    )

    # ── Modules — curated list ────────────────────────────────

    # Helper: skip packages, headers, and test/tb files
    is_skip() {
        local f="$1"
        local bn; bn="$(basename "$f")"
        [[ "$bn" == *.svh ]] && return 0
        [[ "$bn" == *_test.sv ]] && return 0
        [[ "$bn" == *_tb*.sv ]] && return 0
        for p in "${pkgs[@]}"; do [ "$f" = "$p" ] && return 0; done
        return 1
    }

    # common_cells
    local modules=()
    while IFS= read -r f; do
        is_skip "$f" || modules+=("$f")
    done < <(find "${DEPS}/common_cells/src" -maxdepth 1 -name "*.sv" | sort)
    # sram from cva6 (has rst_ni, wuser_i, ruser_o)
    modules+=("${CVA6}/common/local/util/sram.sv")

    # axi
    while IFS= read -r f; do
        is_skip "$f" || modules+=("$f")
    done < <(find "${DEPS}/axi/src" -maxdepth 1 -name "*.sv" | sort)

    # fpnew
    while IFS= read -r f; do
        is_skip "$f" || modules+=("$f")
    done < <(find "${DEPS}/fpnew/src" -maxdepth 1 -name "*.sv" | sort)

    # fpu_div_sqrt_mvp
    while IFS= read -r f; do
        is_skip "$f" || modules+=("$f")
    done < <(find "${DEPS}/fpu_div_sqrt_mvp/hdl" -maxdepth 1 -name "*.sv" | sort)

    # tech_cells_generic
    modules+=("${DEPS}/tech_cells_generic/src/rtl/tc_sram.sv")
    modules+=("${DEPS}/tech_cells_generic/src/rtl/tc_clk.sv")

    # cva6 — curated subset (WT cache, no hpdcache)
    local cva6_files=(
        cva6.sv commit_stage.sv csr_regfile.sv perf_counters.sv
        controller.sv acc_dispatcher.sv cva6_rvfi_probes.sv
        id_stage.sv issue_stage.sv ex_stage.sv
        alu.sv branch_unit.sv compressed_decoder.sv csr_buffer.sv
        cva6_fifo_v3.sv fpu_wrap.sv issue_read_operands.sv
        load_store_unit.sv mult.sv scoreboard.sv
        ariane_regfile_ff.sv axi_shim.sv
        cvxif_issue_register_commit_if_driver.sv
        decoder.sv instr_realign.sv load_unit.sv lsu_bypass.sv
        multiplier.sv serdiv.sv store_unit.sv
        amo_buffer.sv store_buffer.sv
    )
    for f in "${cva6_files[@]}"; do
        modules+=("${CVA6}/core/${f}")
    done
    # cva6 frontend
    modules+=("${CVA6}/core/frontend/frontend.sv")
    modules+=("${CVA6}/core/frontend/btb.sv")
    modules+=("${CVA6}/core/frontend/ras.sv")
    modules+=("${CVA6}/core/frontend/bht.sv")
    modules+=("${CVA6}/core/frontend/instr_queue.sv")
    modules+=("${CVA6}/core/frontend/instr_scan.sv")
    # cva6 cache (WT only)
    modules+=("${CVA6}/core/cache_subsystem/wt_cache_subsystem.sv")
    modules+=("${CVA6}/core/cache_subsystem/cva6_icache.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_axi_adapter.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_dcache.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_dcache_ctrl.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_dcache_mem.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_dcache_missunit.sv")
    modules+=("${CVA6}/core/cache_subsystem/wt_dcache_wbuffer.sv")
    # cva6 mmu
    modules+=("${CVA6}/core/cva6_mmu/cva6_mmu.sv")
    modules+=("${CVA6}/core/cva6_mmu/cva6_ptw.sv")
    modules+=("${CVA6}/core/cva6_mmu/cva6_shared_tlb.sv")
    modules+=("${CVA6}/core/cva6_mmu/cva6_tlb.sv")
    # cva6 pmp
    modules+=("${CVA6}/core/pmp/src/pmp.sv")
    modules+=("${CVA6}/core/pmp/src/pmp_data_if.sv")
    # cva6 util
    modules+=("${CVA6}/common/local/util/sram_cache.sv")
    modules+=("${CVA6}/common/local/util/tc_sram_wrapper.sv")

    # ara (from whichever repo variant) — exclude SoC-level files
    local ara_exclude="ara_soc.sv|ctrl_registers.sv|accel_dispatcher_ideal.sv"
    while IFS= read -r f; do
        is_skip "$f" && continue
        [[ "$(basename "$f")" =~ ^(${ara_exclude})$ ]] && continue
        modules+=("$f")
    done < <(find "${ara}/hardware/src" -name "*.sv" | sort)

    # ara_cva6 wrapper
    modules+=("${ROOT_DIR}/config/ara_cva6.sv")

    local all_src=("${pkgs[@]}" "${modules[@]}")
    echo "[${name}] ${#pkgs[@]} pkgs + ${#modules[@]} modules = ${#all_src[@]} source files"

    # ── Verilate ──────────────────────────────────────────────
    echo "[${name}] Verilating..."
    rm -rf "${verilator_dir:?}"/*

    local trace_flags=()
    if [ "$TRACE_DEPTH" -gt 0 ]; then
        trace_flags=(--trace-fst --trace-depth "${TRACE_DEPTH}")
    fi

    verilator --cc -j 1 \
        --Mdir "${verilator_dir}" \
        --O3 --x-assign fast --x-initial fast \
        --noassert \
        +define+COMMON_CELLS_ASSERTS_OFF \
        ${trace_flags[@]+"${trace_flags[@]}"} \
        --threads "${THREADS}" \
        --top-module ara_cva6 \
        -GNrLanes=${NRLANES} -GVLEN=${VLEN} \
        -Wno-ENUMVALUE -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
        -Wno-ASCRANGE -Wno-SELRANGE \
        -Wno-REDEFMACRO -Wno-IMPLICITSTATIC \
        -Wno-fatal \
        "${incdirs[@]}" \
        "${all_src[@]}"

    # ── Compile C++ ───────────────────────────────────────────
    echo "[${name}] Compiling..."

    local verilator_root
    verilator_root="$(verilator --getenv VERILATOR_ROOT)"

    local cxxflags=(
        -"${OPT}" -fPIC -std=c++14
        -I"${verilator_dir}"
        -I"${verilator_root}/include"
        -I"${verilator_root}/include/vltstd"
        -DVERILATOR=1
        -DAXI_DATA_BITS=$((DLEN / 2))
        -DVM_COVERAGE=0 -DVM_SC=0 -DVM_TIMING=0
        -DVM_TRACE=0 -DVM_TRACE_FST=0 -DVM_TRACE_VCD=0 -DVM_TRACE_SAIF=0
    )
    if [ "$TRACE_DEPTH" -gt 0 ]; then
        cxxflags=("${cxxflags[@]/-DVM_TRACE=0/-DVM_TRACE=1}")
        cxxflags=("${cxxflags[@]/-DVM_TRACE_FST=0/-DVM_TRACE_FST=1}")
    fi

    local runtime_srcs=(
        "${verilator_root}/include/verilated.cpp"
        "${verilator_root}/include/verilated_threads.cpp"
    )
    if [ "$TRACE_DEPTH" -gt 0 ]; then
        runtime_srcs+=("${verilator_root}/include/verilated_fst_c.cpp")
    fi

    local gen_srcs=()
    for f in "${verilator_dir}"/Vara_cva6*.cpp; do
        [[ "$(basename "$f")" == *vm_classes* ]] && continue
        gen_srcs+=("$f")
    done

    local all_cpps=("${runtime_srcs[@]}" "${SIMS_DIR}/hdl/sim.cpp" "${gen_srcs[@]}")
    local ncpu
    ncpu="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"

    local cxx="c++"
    command -v ccache &>/dev/null && cxx="ccache c++"

    echo "[${name}] ${#all_cpps[@]} C++ files, -j ${ncpu}, cxx=${cxx}"

    printf '%s\n' "${all_cpps[@]}" | xargs -P "${ncpu}" -n1 \
        sh -c "${cxx} ${cxxflags[*]} -c -o \"${obj_dir}/\$(basename \"\$1\").o\" \"\$1\"" _

    # ── Link ──────────────────────────────────────────────────
    echo "[${name}] Linking..."

    local objs=()
    for f in "${all_cpps[@]}"; do
        objs+=("${obj_dir}/$(basename "$f").o")
    done

    c++ -shared -o "${install_dir}/libAra.so" "${objs[@]}"

    echo "[${name}] Done — ${install_dir}/libAra.so"
}

# ---------------------------------------------------------------
# Build spike (ISA reference)
# ---------------------------------------------------------------
build_spike() {
    local spike_src="${ROOT_DIR}/repo/spike"
    local spike_build="${ROOT_DIR}/build/spike"
    local spike_install="${ROOT_DIR}/install/spike"
    local spike_lib="${ROOT_DIR}/install/sim/spike"

    if [ -f "${spike_lib}/libIss.so" ]; then
        echo "[skip] spike already built"
        return
    fi

    echo ""
    echo "=== Building spike ==="

    # Configure + build + install libriscv
    if [ ! -f "${spike_build}/Makefile" ]; then
        echo "[spike] Configuring..."
        mkdir -p "${spike_build}"
        cd "${spike_build}"
        "${spike_src}/configure" --prefix="${spike_install}" \
            CC="ccache gcc" CXX="ccache g++" 2>&1 | tail -3
    fi

    echo "[spike] Building..."
    local ncpu
    ncpu="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"
    make -C "${spike_build}" -j"${ncpu}" 2>&1 | tail -3
    make -C "${spike_build}" install 2>&1 | tail -3

    # Compile bridge → libAra.so
    echo "[spike] Compiling bridge..."
    mkdir -p "${spike_lib}"
    c++ -std=c++17 -O2 -fPIC -shared \
        -I"${spike_install}/include" \
        -I"${SIMS_DIR}" \
        -L"${spike_install}/lib" -lriscv -lsoftfloat \
        -Wl,-rpath,"${spike_install}/lib" \
        -o "${spike_lib}/libIss.so" \
        "${SIMS_DIR}/spike/sim.cpp"

    echo "[spike] Done — ${spike_lib}/libIss.so"
}

# ---------------------------------------------------------------
# Build all
# ---------------------------------------------------------------
build_spike
build_variant "base" "${ROOT_DIR}/repo/ara-base"
build_variant "fork" "${ROOT_DIR}/repo/ara-fork"
