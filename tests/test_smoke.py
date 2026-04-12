# Smoke tests — bare-metal C snippets on CVA6 core via sim_top.
#
# Tests:
#   test_return_zero    main returns 0
#   test_add            main returns 2 + 3
#   test_store_load     store/load to SRAM data region
#   test_vadd           vector integer add (4 x i32)

import struct
from conftest import assert_ok, compile_snippet


def test_return_zero(sim):
    binary = compile_snippet("int main() { return 0; }")
    sim.load(binary)
    sim.boot()
    result = sim.run(max_cycles=5000)
    assert_ok(result)
    assert result.retval == 0


def test_add(sim):
    binary = compile_snippet("int main() { return 2 + 3; }")
    sim.load(binary)
    sim.boot()
    result = sim.run(max_cycles=5000)
    assert_ok(result)
    assert result.retval == 5


def test_store_load(sim):
    binary = compile_snippet("""
    int main() {
        volatile int *p = (volatile int *)0x80100000;
        *p = 42;
        return *p;
    }
    """)
    sim.load(binary)
    sim.boot()
    result = sim.run(max_cycles=5000)
    assert_ok(result)
    assert result.retval == 42


def test_vadd(sim):
    """vadd.vv: [1,2,3,4] + [10,20,30,40] = [11,22,33,44]."""
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"
            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"
            "li a2, 0x80100200\\n"
            "vle32.v v1, (a0)\\n"
            "vle32.v v2, (a1)\\n"
            "vadd.vv v3, v1, v2\\n"
            "vse32.v v3, (a2)\\n"
            ::: "a0", "a1", "a2", "memory");
        return 0;
    }
    ''')
    a = [1, 2, 3, 4]
    b = [10, 20, 30, 40]
    expected = [11, 22, 33, 44]

    sim.load(binary)
    sim.load(struct.pack('<4I', *a), sram_offset=0x100000)
    sim.load(struct.pack('<4I', *b), sram_offset=0x100100)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    got = sim.peek_u32(0x100200, 4)
    assert got == expected, f"vadd: expected {expected}, got {got}"
