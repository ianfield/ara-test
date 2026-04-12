#!/usr/bin/env python3
"""Annotate CVA6 commit traces with cycle deltas and objdump mnemonics."""

import argparse
import bisect
import re
import subprocess
import sys
from pathlib import Path


def parse_objdump(elf_path: str, objdump: str, color: bool
                  ) -> tuple[dict[int, str], list[tuple[int, str]]]:
    """Run llvm-objdump -d and parse into {pc: mnemonic} and [(pc, name)] function list."""
    cmd = [objdump, "-d", elf_path]
    if color:
        cmd.append("--disassembler-color=on")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    pc_map: dict[int, str] = {}
    funcs: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        # Function label: "0000000001000000 <_start>:"
        fm = re.match(r'([0-9a-fA-F]+)\s+<(.+)>:', line)
        if fm:
            funcs.append((int(fm.group(1), 16), fm.group(2)))
            continue
        # Instruction: " 1000004: 04c28293     \taddi\tt0, t0, 0x4c"
        # ANSI escapes only appear in the mnemonic portion (after the tab).
        m = re.match(r'\s*([0-9a-fA-F]+):\s+[0-9a-fA-F]+\s*\t(.+)', line)
        if m:
            pc = int(m.group(1), 16)
            # Normalize objdump tabs to single space, then pad mnemonic to fixed width
            parts = m.group(2).rstrip().split('\t', 1)
            if len(parts) == 2:
                pc_map[pc] = f"{parts[0]:<14s}{parts[1]}"
            else:
                pc_map[pc] = parts[0]
    return pc_map, funcs


# hart_0.dasm line: "                  89 0x1000000 M (0x00000297) DASM(00000297)"
DASM_RE = re.compile(r'\s*(\d+)\s+0x([0-9a-fA-F]+)\s+')


def parse_trace(trace_path: str) -> list[tuple[int, int]]:
    """Parse hart_0.dasm into [(cycle, pc), ...]."""
    entries = []
    with open(trace_path) as f:
        for line in f:
            m = DASM_RE.match(line)
            if m:
                entries.append((int(m.group(1)), int(m.group(2), 16)))
    return entries


LINE_WIDTH = 72


def func_for_pc(funcs: list[tuple[int, str]], func_addrs: list[int],
                pc: int) -> str | None:
    """Return the function name containing pc, or None."""
    idx = bisect.bisect_right(func_addrs, pc) - 1
    if idx >= 0:
        return funcs[idx][1]
    return None


def separator(label: str, char: str = '─') -> str:
    """Centered label in a repeated-char line."""
    text = f" {label} "
    pad = LINE_WIDTH - len(text)
    left = pad // 2
    right = pad - left
    return f"{char * left}{text}{char * right}\n"


def print_annotated(entries: list[tuple[int, int]], pc_map: dict[int, str],
                    funcs: list[tuple[int, str]], mark: bool) -> None:
    """Print [delta] cycle pc mnemonic with column alignment."""
    if not entries:
        return

    func_addrs = [addr for addr, _ in funcs]

    # Compute deltas
    deltas = [0]
    for i in range(1, len(entries)):
        deltas.append(entries[i][0] - entries[i - 1][0])

    # Column widths
    max_delta = max(len(str(d)) for d in deltas)
    max_cycle = max(len(str(c)) for c, _ in entries)

    loop_start_cycle = entries[0][0]
    cur_func = func_for_pc(funcs, func_addrs, entries[0][1])

    # Label the initial function (loop only prints on transitions)
    if mark and cur_func:
        sys.stdout.write(separator(cur_func, '═'))

    for i, (cycle, pc) in enumerate(entries):
        if mark and i > 0:
            fn = func_for_pc(funcs, func_addrs, pc)
            backwards_branch = pc < entries[i - 1][1]
            function_boundary = fn != cur_func

            if backwards_branch or function_boundary:
                loop_cycles = entries[i - 1][0] - loop_start_cycle
                if loop_cycles > 0:
                    sys.stdout.write(separator(str(loop_cycles)))
                loop_start_cycle = entries[i - 1][0]

            if function_boundary:
                sys.stdout.write(separator(fn or '???', '═'))
                cur_func = fn

        delta = deltas[i]
        mnemonic = pc_map.get(pc, '???')
        sys.stdout.write(
            f"[{delta:>{max_delta}}] {cycle:>{max_cycle}}  {pc:08x}  {mnemonic}\n"
        )

    # Final cycle count after last instruction
    if mark and entries:
        final_cycles = entries[-1][0] - loop_start_cycle
        if final_cycles > 0:
            sys.stdout.write(separator(str(final_cycles)))


def main():
    parser = argparse.ArgumentParser(description='Annotate CVA6 commit traces')
    parser.add_argument('test_dir',
                        help='Test directory containing hart_0.dasm and test.elf')
    parser.add_argument('--objdump', default='llvm-objdump',
                        help='Path to llvm-objdump')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable color output')
    parser.add_argument('--no-less', action='store_true',
                        help='Print to stdout instead of paging with less')
    parser.add_argument('--no-mark', action='store_true',
                        help='Disable function and loop cycle markers')
    args = parser.parse_args()

    test_dir = Path(args.test_dir)
    color = not args.no_color
    mark = not args.no_mark

    pc_map, funcs = parse_objdump(str(test_dir / 'test.elf'), args.objdump, color)
    entries = parse_trace(str(test_dir / 'hart_0.dasm'))

    # Pipe through less -R when stdout is a TTY (unless --no-less)
    if not args.no_less and sys.stdout.isatty():
        pager = subprocess.Popen(['less', '-R'], stdin=subprocess.PIPE, text=True)
        sys.stdout = pager.stdin
        try:
            print_annotated(entries, pc_map, funcs, mark)
        except BrokenPipeError:
            pass
        finally:
            try:
                pager.stdin.close()
            except BrokenPipeError:
                pass
            pager.wait()
    else:
        print_annotated(entries, pc_map, funcs, mark)


if __name__ == '__main__':
    main()
