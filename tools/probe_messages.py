#!/usr/bin/env python3
"""Drive the puzzle chip with an arbitrary 121-bit pattern and print the
string it emits on O[7:0].

Used to discover the alternate messages (EMPTY SKY, BIG BANG, TRY AGAIN)
that are not reachable through the intended solution.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from simulate_netlist import Simulator

PATTERNS = {
    "zeros": lambda: [0] * 121,
    "ones": lambda: [1] * 121,
    "random": lambda: [random.getrandbits(1) for _ in range(121)],
}


def run(sim: Simulator, bits: list[int], post_clocks: int) -> tuple[bytes, bool]:
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

    emitted = bytearray()
    success = False
    for _ in range(post_clocks):
        sim.update_ports({"clk": True})
        output, success_now = sim.outputs()
        success = success or success_now
        sim.update_ports({"clk": False})
        if output:
            emitted.append(output)
        elif emitted:
            break
    return bytes(emitted), success


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument(
        "--pattern",
        choices=sorted(PATTERNS) + ["file"],
        default="zeros",
        help="built-in input pattern, or 'file' to read --bits",
    )
    parser.add_argument("--bits", type=Path, help="file holding 121 binary digits")
    parser.add_argument("--post-clocks", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    random.seed(args.seed)
    if args.pattern == "file":
        if args.bits is None:
            parser.error("--pattern file requires --bits")
        bits = [int(c) for c in args.bits.read_text().strip()]
    else:
        bits = PATTERNS[args.pattern]()
    if len(bits) != 121 or any(bit not in (0, 1) for bit in bits):
        raise ValueError("input must be exactly 121 binary digits")

    sim = Simulator(json.loads(args.netlist.read_text()))
    message, success = run(sim, bits, args.post_clocks)
    print(f"stars={sum(bits)} success={int(success)}")
    print("bytes=" + " ".join(f"{b:02x}" for b in message))
    print("string=" + repr(message.decode("ascii", "replace")))


if __name__ == "__main__":
    main()
