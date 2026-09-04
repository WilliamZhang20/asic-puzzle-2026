#!/usr/bin/env python3
"""Symbolically solve the recovered 121-bit serial-input state machine."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import z3

from simulate_netlist import FLOP_PREFIXES, OUTPUT_PINS, Simulator


def znot(value):
    return z3.Not(value)


def symbolic_gate(master, pins, values):
    base = master.rsplit("_", 1)[0]
    output = "Y" if "Y" in pins else "X"
    inputs = {
        pin: znot(values[net]) if pin.endswith("_N") else values[net]
        for pin, net in pins.items()
        if pin not in OUTPUT_PINS
    }
    vals = list(inputs.values())
    if base in {"buf", "clkbuf"} or base.startswith("clkbuf"):
        result = inputs["A"]
    elif base == "inv":
        result = znot(inputs["A"])
    elif base == "mux2":
        result = z3.If(inputs["S"], inputs["A1"], inputs["A0"])
    elif base == "xor2":
        result = z3.Xor(inputs["A"], inputs["B"])
    elif base == "xnor2":
        result = znot(z3.Xor(inputs["A"], inputs["B"]))
    elif base.startswith("nand"):
        result = znot(z3.And(*vals))
    elif base.startswith("and"):
        result = z3.And(*vals)
    elif base.startswith("nor"):
        result = znot(z3.Or(*vals))
    elif base.startswith("or"):
        result = z3.Or(*vals)
    elif base.startswith("a") and "o" in base:
        groups = defaultdict(list)
        for pin, value in inputs.items():
            groups[pin[0]].append(value)
        result = z3.Or(*(z3.And(*group) for group in groups.values()))
        if output == "Y":
            result = znot(result)
    elif base.startswith("o") and "a" in base:
        groups = defaultdict(list)
        for pin, value in inputs.items():
            groups[pin[0]].append(value)
        result = z3.And(*(z3.Or(*group) for group in groups.values()))
        if output == "Y":
            result = znot(result)
    else:
        raise ValueError(f"unsupported combinational cell {master}")
    return output, result


def evaluate(sim, state, port_values):
    values = {}
    for name, value in port_values.items():
        values[sim.ports[name]] = value
    for instance in sim.flops:
        values[instance["pins"]["Q"]] = state[instance["name"]]
    for instance in sim.comb_order:
        pins = instance["pins"]
        if instance["master"].startswith("conb"):
            values[pins["HI"]] = z3.BoolVal(True)
            values[pins["LO"]] = z3.BoolVal(False)
        else:
            output, value = symbolic_gate(instance["master"], pins, values)
            values[pins[output]] = value
    return values


def reset_state(sim):
    sim.update_ports({"clk": False, "rst_n": False, "enable": False, "I": False})
    for _ in range(3):
        sim.update_ports({"clk": True})
        sim.update_ports({"clk": False})
    sim.update_ports({"rst_n": True})
    return {name: z3.BoolVal(value) for name, value in sim.state.items()}


def transition(sim, state, input_value, enable):
    values = evaluate(
        sim,
        state,
        {
            "clk": z3.BoolVal(False),
            "rst_n": z3.BoolVal(True),
            "enable": enable,
            "I": input_value,
        },
    )
    return {instance["name"]: values[instance["pins"]["D"]] for instance in sim.flops}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--bits", type=int, default=121)
    parser.add_argument("--max-solutions", type=int, default=1)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.netlist.read_text())
    sim = Simulator(data)
    state = reset_state(sim)
    bits = [z3.Bool(f"input_{i:03d}") for i in range(args.bits)]
    success_flop = next(
        i for i in sim.flops if i["pins"]["Q"] == sim.ports["success"]
    )
    history = []
    for bit in bits:
        state = transition(sim, state, bit, z3.BoolVal(True))
        history.append(state[success_flop["name"]])
    # The example protocol lowers enable and clocks once before the first
    # output byte.  Include that cycle in the success condition.
    state = transition(sim, state, z3.BoolVal(False), z3.BoolVal(False))
    history.append(state[success_flop["name"]])

    solver = z3.Solver()
    solver.add(history[-1])
    print(f"built {args.bits}-cycle transition formula; solving...", flush=True)
    answers = []
    for index in range(args.max_solutions):
        status = solver.check()
        print(status)
        if status != z3.sat:
            break
        model = solver.model()
        answer = [
            1 if z3.is_true(model.eval(bit, model_completion=True)) else 0
            for bit in bits
        ]
        answers.append(answer)
        rendered = "".join(map(str, answer))
        print(f"solution {index + 1}: {rendered}")
        print("11x11 input, in serial order:")
        for row in range(0, len(answer), 11):
            print("".join("#" if bit else "." for bit in answer[row : row + 11]))
        solver.add(z3.Or(*(bit != bool(value) for bit, value in zip(bits, answer))))
    if not answers:
        raise SystemExit(1)
    if args.output:
        args.output.write_text("".join(map(str, answers[0])) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
