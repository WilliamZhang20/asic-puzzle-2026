#!/usr/bin/env python3
"""Concrete replay and sanity checks for the recovered puzzle solution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulate_netlist import Simulator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("bits", type=Path)
    args = parser.parse_args()
    bits = [int(bit) for bit in args.bits.read_text().strip()]
    if len(bits) != 121 or any(bit not in (0, 1) for bit in bits):
        raise ValueError("solution must contain exactly 121 binary digits")

    grid = [bits[offset : offset + 11] for offset in range(0, 121, 11)]
    assert [sum(row) for row in grid] == [2] * 11
    assert [sum(grid[row][column] for row in range(11)) for column in range(11)] == [2] * 11
    for row in range(11):
        for column in range(11):
            if not grid[row][column]:
                continue
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    neighbor = (row + dr, column + dc)
                    if (dr, dc) > (0, 0) and 0 <= neighbor[0] < 11 and 0 <= neighbor[1] < 11:
                        assert not grid[neighbor[0]][neighbor[1]]

    sim = Simulator(json.loads(args.netlist.read_text()))
    sim.update_ports({"clk": False, "rst_n": False, "enable": False, "I": False})
    for _ in range(3):
        sim.update_ports({"clk": True})
        sim.update_ports({"clk": False})
    sim.update_ports({"rst_n": True, "enable": True})
    for bit in bits:
        sim.update_ports({"I": bool(bit)})
        sim.update_ports({"clk": True})
        sim.update_ports({"clk": False})

    sim.update_ports({"enable": False, "I": False})
    emitted = []
    success = False
    for _ in range(80):
        sim.update_ports({"clk": True})
        output, success = sim.outputs()
        sim.update_ports({"clk": False})
        if output:
            emitted.append(output)
        elif emitted:
            break
    message = bytes(emitted)
    assert success
    assert message == b"(* TWO STARS *)"
    print("PASS: success=1")
    print(f"output={message.decode()}")
    print("rows=2 each, columns=2 each, adjacent-star conflicts=0")


if __name__ == "__main__":
    main()
