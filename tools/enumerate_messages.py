#!/usr/bin/env python3
"""Enumerate every output trace reachable after a 121-bit puzzle input.

Unlike probe_messages.py, this does not guess interesting concrete patterns.
It symbolically executes the recovered gate netlist, asks Z3 for one reachable
post-input output trace, blocks that complete observable trace, and repeats.
Thus a single result represents every input that produces the same message.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import z3

from probe_messages import run
from simulate_netlist import Simulator
from solve_challenge import evaluate, reset_state, transition


def output_vector(sim: Simulator, state: dict, *, clk: bool) -> list:
    values = evaluate(
        sim,
        state,
        {
            "clk": z3.BoolVal(clk),
            "rst_n": z3.BoolVal(True),
            "enable": z3.BoolVal(False),
            "I": z3.BoolVal(False),
        },
    )
    return [values[sim.ports[f"O[{bit}]"]] for bit in range(8)]


def model_bool(model: z3.ModelRef, expression) -> bool:
    return z3.is_true(model.eval(expression, model_completion=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--bits", type=int, default=121)
    parser.add_argument(
        "--trace-clocks",
        type=int,
        default=32,
        help="post-enable clock edges included in the observable trace",
    )
    args = parser.parse_args()

    sim = Simulator(json.loads(args.netlist.read_text()))
    state = reset_state(sim)
    inputs = [z3.Bool(f"input_{index:03d}") for index in range(args.bits)]
    for bit in inputs:
        state = transition(sim, state, bit, z3.BoolVal(True))

    trace = []
    for _ in range(args.trace_clocks):
        state = transition(sim, state, z3.BoolVal(False), z3.BoolVal(False))
        trace.extend(output_vector(sim, state, clk=True))

    solver = z3.Solver()
    print(
        f"built symbolic {args.bits}-bit input and {args.trace_clocks}-clock "
        "output trace",
        flush=True,
    )
    count = 0
    while solver.check() == z3.sat:
        count += 1
        model = solver.model()
        bits = [int(model_bool(model, bit)) for bit in inputs]
        observed = [model_bool(model, bit) for bit in trace]

        concrete = Simulator(sim.data)
        message, success = run(concrete, bits, args.trace_clocks)
        rendered = message.decode("ascii", "replace")
        print(
            f"trace {count}: stars={sum(bits):3d} success={int(success)} "
            f"message={rendered!r}"
        )
        print("  witness=" + "".join(map(str, bits)))

        # Exclude this complete externally visible trace, not merely this one
        # input. The next model must cause at least one output bit to differ.
        solver.add(
            z3.Or(
                *(expression != value for expression, value in zip(trace, observed))
            )
        )

    print(f"unsat after blocking {count} distinct output traces")


if __name__ == "__main__":
    main()
