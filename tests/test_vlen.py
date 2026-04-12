# VL-sensitive mask-unit op correctness.
# Tests ops that reduce or reshape across elements — the kind most likely
# to have VL trim bugs (counting/scanning the full datapath instead of vl).

import struct

from conftest import assert_ok, compile_snippet


# ── vcpop.m — mask popcount, scalar result ──────────────────────

def _test_vcpop(sim, vl, mask_pattern, expected):
    """Helper: set vl, load mask_pattern into v0 via memory, vcpop, check."""
    mask_byte = 0
    for i, b in enumerate(mask_pattern):
        mask_byte |= (b << i)
    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "vsetivli zero, {vl}, e32, m1, ta, ma\\n"
            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"
            "vlm.v v0, (a0)\\n"
            "vcpop.m a2, v0\\n"
            "sw a2, 0(a1)\\n"
            ::: "a0", "a1", "a2", "memory");
        return 0;
    }}
    ''')
    sim.load(binary)
    sim.load(struct.pack('<B', mask_byte) + b'\x00' * 15, sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)
    got = sim.peek_u32(0x100100, 1)[0]
    assert got == expected, (
        f"vcpop vl={vl} mask=0b{mask_byte:0{vl}b}: expected {expected}, got {got}")


def test_vcpop_vl4(sim):
    _test_vcpop(sim, 4, [1, 1, 1, 1], 4)

def test_vcpop_vl1(sim):
    _test_vcpop(sim, 1, [1], 1)


# vcpop with vmset — tests VL trim when bits beyond vl are set.

def _test_vcpop_vmset(sim, vl):
    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "vsetivli zero, {vl}, e32, m1, ta, ma\\n"
            "li a1, 0x80100100\\n"
            "vmset.m v0\\n"
            "vcpop.m a2, v0\\n"
            "sw a2, 0(a1)\\n"
            ::: "a1", "a2", "memory");
        return 0;
    }}
    ''')
    sim.load(binary)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)
    got = sim.peek_u32(0x100100, 1)[0]
    assert got == vl, f"vcpop vmset vl={vl}: expected {vl}, got {got}"


def test_vcpop_vmset_vl1(sim):
    _test_vcpop_vmset(sim, 1)

def test_vcpop_vmset_vl2(sim):
    _test_vcpop_vmset(sim, 2)

def test_vcpop_vmset_vl3(sim):
    _test_vcpop_vmset(sim, 3)

def test_vcpop_vmset_vl4(sim):
    _test_vcpop_vmset(sim, 4)


# ── vfirst.m — find first set bit, scalar result ────────────────

def _test_vfirst(sim, vl, mask_pattern, expected):
    mask_byte = 0
    for i, b in enumerate(mask_pattern):
        mask_byte |= (b << i)
    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "vsetivli zero, {vl}, e32, m1, ta, ma\\n"
            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"
            "vlm.v v0, (a0)\\n"
            "vfirst.m a2, v0\\n"
            "sw a2, 0(a1)\\n"
            ::: "a0", "a1", "a2", "memory");
        return 0;
    }}
    ''')
    sim.load(binary)
    sim.load(struct.pack('<B', mask_byte) + b'\x00' * 15, sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)
    raw = sim.peek_u32(0x100100, 1)[0]
    got = raw if raw < 0x80000000 else raw - 0x100000000
    assert got == expected, (
        f"vfirst vl={vl} mask=0b{mask_byte:0{vl}b}: expected {expected}, got {got}")


def test_vfirst_vl4_bit2(sim):
    _test_vfirst(sim, 4, [0, 0, 1, 0], 2)

def test_vfirst_vl1(sim):
    _test_vfirst(sim, 1, [1], 0)

def test_vfirst_vmset_vl4(sim):
    """vmset → vfirst: first bit always at 0."""
    _test_vfirst(sim, 4, [1, 1, 1, 1], 0)

def test_vfirst_vmclr_vl4(sim):
    """vmclr → vfirst: no bits set → -1."""
    _test_vfirst(sim, 4, [0, 0, 0, 0], -1)


# ── viota.m — prefix popcount, vector result ────────────────────

def _test_viota(sim, vl, mask_pattern, expected):
    mask_byte = 0
    for i, b in enumerate(mask_pattern):
        mask_byte |= (b << i)
    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "vsetivli zero, {vl}, e32, m1, ta, ma\\n"
            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"
            "vlm.v v0, (a0)\\n"
            "viota.m v2, v0\\n"
            "vse32.v v2, (a1)\\n"
            ::: "a0", "a1", "memory");
        return 0;
    }}
    ''')
    sim.load(binary)
    sim.load(struct.pack('<B', mask_byte) + b'\x00' * 15, sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)
    got = sim.peek_u32(0x100100, vl)
    assert got == expected, (
        f"viota vl={vl} mask=0b{mask_byte:0{vl}b}: expected {expected}, got {got}")


def test_viota_vl4(sim):
    _test_viota(sim, 4, [0, 1, 0, 1], [0, 0, 1, 1])

def test_viota_vl4_zeros(sim):
    _test_viota(sim, 4, [0, 0, 0, 0], [0, 0, 0, 0])

def test_viota_vl1(sim):
    _test_viota(sim, 1, [1], [0])


# ── vmsbf.m — set-before-first, mask result ─────────────────────

def _test_vmsbf(sim, vl, mask_pattern, expected):
    mask_byte = 0
    for i, b in enumerate(mask_pattern):
        mask_byte |= (b << i)
    exp_byte = 0
    for i, b in enumerate(expected):
        exp_byte |= (b << i)
    binary = compile_snippet(f'''
    int main() {{
        asm volatile(
            "vsetivli zero, {vl}, e32, m1, ta, ma\\n"
            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"
            "vlm.v v0, (a0)\\n"
            "vmsbf.m v2, v0\\n"
            "vsm.v v2, (a1)\\n"
            ::: "a0", "a1", "memory");
        return 0;
    }}
    ''')
    sim.load(binary)
    sim.load(struct.pack('<B', mask_byte) + b'\x00' * 15, sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)
    got_byte = sim.peek_u32(0x100100, 1)[0] & ((1 << vl) - 1)
    assert got_byte == exp_byte, (
        f"vmsbf vl={vl} mask=0b{mask_byte:0{vl}b}: "
        f"expected 0b{exp_byte:0{vl}b}, got 0b{got_byte:0{vl}b}")


def test_vmsbf_vl4(sim):
    _test_vmsbf(sim, 4, [0, 0, 1, 0], [1, 1, 0, 0])

def test_vmsbf_vl1(sim):
    _test_vmsbf(sim, 1, [0], [1])

def test_vmsbf_vmset_vl4(sim):
    """vmset → vmsbf: first bit at 0, nothing before → 0b0000."""
    _test_vmsbf(sim, 4, [1, 1, 1, 1], [0, 0, 0, 0])

def test_vmsbf_vmclr_vl4(sim):
    """vmclr → vmsbf: no bit set, all before → 0b1111."""
    _test_vmsbf(sim, 4, [0, 0, 0, 0], [1, 1, 1, 1])
