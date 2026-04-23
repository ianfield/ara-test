# Reduction kernels — widening load + accumulate + reduce.

from conftest import assert_ok, compile_snippet


# ── sum_bytes: u8[N] -> u64 ─────────────────────────────────────
#
# Strip-mined widening reduction, mirroring a compiler-emitted
# sum_bytes kernel:
#   1. Zero a u64 accumulator in v8 (m2) at e64.
#   2. Per iteration at e32/m1:
#        vle8.v        load u8 chunk into v10
#        vzext.vf4     u8 -> u32 in v11
#        vwaddu.wv     v8 (u64, m2) += v11 (u32, m1)   (tail-undisturbed)
#   3. Re-widen to e64/m2 and vredsum.vs v8, v8, {0} to reduce.
#
# Exercises: multiple vsetvli transitions, widening load, vf4 extend,
# widening add accumulating across LMUL groups, tu-mask preservation,
# full-width reduction, and vmv.x.s scalar extract.

def _test_sum_bytes(sim, N: int):
    data = bytes([(i * 7 + 13) & 0xFF for i in range(N)])
    expected = sum(data)

    off_src = 0x100000
    off_dst = 0x100200

    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "li a0, 0x80100000\\n"         // src base
            "li a1, {N}\\n"                 // remaining count
            "li a2, 0x80100200\\n"         // &dst (u64)
            "li a3, 0\\n"                   // strip-mine offset

            // Zero 64-bit accumulator (v8,v9 as m2)
            "vsetvli a4, zero, e64, m2, ta, ma\\n"
            "vmv.v.i v8, 0\\n"

            "1:\\n"
            "vsetvli a4, a1, e32, m1, ta, ma\\n"
            "add a5, a0, a3\\n"
            "vle8.v v10, (a5)\\n"
            "sub a1, a1, a4\\n"
            "vzext.vf4 v11, v10\\n"
            "vsetvli zero, zero, e32, m1, tu, ma\\n"
            "vwaddu.wv v8, v8, v11\\n"
            "add a3, a3, a4\\n"
            "bnez a1, 1b\\n"

            // Final reduction: v8 (u64 m2) -> v8[0]
            "vsetvli a4, zero, e64, m2, ta, ma\\n"
            "vmv.s.x v10, zero\\n"
            "vredsum.vs v8, v8, v10\\n"

            // Extract scalar and store 64-bit sum
            "vmv.x.s a4, v8\\n"
            "sd a4, 0(a2)\\n"

            ::: "a0", "a1", "a2", "a3", "a4", "a5", "memory");
        return 0;
    }}
    ''')

    sim.load(binary)
    sim.load(data, sram_offset=off_src)
    sim.boot()
    result = sim.run(max_cycles=1000)
    assert_ok(result)

    lo, hi = sim.peek_u32(off_dst, 2)
    got = lo | (hi << 32)
    assert got == expected, (
        f"sum_bytes N={N}: expected {expected} (0x{expected:x}), "
        f"got {got} (0x{got:x})"
    )


def test_sum_bytes_n4(sim):
    _test_sum_bytes(sim, 4)


def test_sum_bytes_n64(sim):
    _test_sum_bytes(sim, 64)
