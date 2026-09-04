#!/usr/bin/env python3
"""Recover the input grids from example_inputs.vcd and decode the hidden
ASCII message they spell.

Each of the two "wrong" attempts in the provided waveform is a 121-bit
grid whose columns 7..10 are always zero.  Reading columns 0..6 of each
row as a 7-bit character, least-significant bit first, spells a sentence.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from simulate_netlist import parse_vcd_events


def extract_attempts(path: Path) -> list[list[int]]:
    events = parse_vcd_events(path)
    state = {"clk": False, "rst_n": False, "enable": False, "I": False}
    attempts: list[list[int]] = []
    current: list[int] = []
    for time in sorted(events):
        changes = events[time]
        rising = changes.get("clk") and not state["clk"]
        state.update(changes)
        if rising and state["enable"]:
            current.append(int(state["I"]))
        elif current and not state["enable"]:
            attempts.append(current)
            current = []
    if current:
        attempts.append(current)
    return attempts


def decode(bits: list[int]) -> str:
    rows = [bits[offset : offset + 11] for offset in range(0, len(bits), 11)]
    out = []
    for row in rows:
        value = sum(bit << index for index, bit in enumerate(row[:7]))
        out.append(chr(value))
    return "".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("vcd", type=Path)
    args = parser.parse_args()

    message = []
    for index, bits in enumerate(extract_attempts(args.vcd), start=1):
        print(f"attempt {index}: {len(bits)} bits, {sum(bits)} stars")
        for offset in range(0, len(bits), 11):
            row = bits[offset : offset + 11]
            print("  " + "".join("#" if bit else "." for bit in row))
        text = decode(bits)
        print(f"  columns 0..6 as 7-bit LSB-first ASCII: {text!r}")
        message.append(text)
    print()
    print("hidden message: " + repr("".join(message)))


if __name__ == "__main__":
    main()
