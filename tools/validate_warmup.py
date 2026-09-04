#!/usr/bin/env python3
"""Check a recovered warm-up netlist against its known Verilog and DEF."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def normalized(name):
    return name.lstrip("\\")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("extracted", type=Path)
    parser.add_argument("--verilog", type=Path, default=Path("warmup/01_netlist.v"))
    parser.add_argument(
        "--def-file", type=Path, default=Path("warmup/03_post_place_and_route.def")
    )
    args = parser.parse_args()

    verilog = args.verilog.read_text()
    expected_instances = {}
    instance_pattern = re.compile(
        r"(sky130_fd_sc_hd__\w+)\s+(\\?[^\s(]+)\s*\((.*?)\);", re.S
    )
    pin_pattern = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")
    for match in instance_pattern.finditer(verilog):
        master, name, body = match.groups()
        pins = {p.group(1): p.group(2).strip() for p in pin_pattern.finditer(body)}
        expected_instances[normalized(name)] = (
            master.removeprefix("sky130_fd_sc_hd__"),
            pins,
        )

    placements = {}
    def_text = args.def_file.read_text()
    placement_pattern = re.compile(
        r"^\s*-\s+(\\?\S+)\s+(sky130_fd_sc_hd__\w+).*?"
        r"\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)",
        re.M,
    )
    for match in placement_pattern.finditer(def_text):
        name, master, x, y = match.groups()
        placements[
            (master.removeprefix("sky130_fd_sc_hd__"), int(x) / 1000, int(y) / 1000)
        ] = normalized(name)

    recovered = json.loads(args.extracted.read_text())
    errors = []
    mapped = {}
    for instance in recovered["instances"]:
        key = (
            instance["master"],
            round(instance["placement"][0], 6),
            round(instance["placement"][1], 6),
        )
        name = placements.get(key)
        if name is None:
            errors.append(("no placement", key))
        else:
            mapped[name] = instance

    logical_nets = {}
    for name, (_, pins) in expected_instances.items():
        if name not in mapped:
            continue
        for pin, wire in pins.items():
            actual = mapped[name]["pins"].get(pin)
            if actual is None:
                errors.append(("missing pin", name, pin, wire))
            else:
                logical_nets.setdefault(wire, set()).add(actual)
    for port, actual in recovered["ports"].items():
        if port not in {"VPWR", "VGND"}:
            logical_nets.setdefault(port, set()).add(actual)

    for wire, actuals in logical_nets.items():
        if len(actuals) != 1:
            errors.append(("split net", wire, sorted(actuals)))
    reverse = {}
    for wire, actuals in logical_nets.items():
        if len(actuals) == 1:
            reverse.setdefault(next(iter(actuals)), []).append(wire)
    for actual, wires in reverse.items():
        if len(wires) > 1:
            errors.append(("shorted nets", actual, wires))

    print(
        f"validated {len(mapped)} functional instances and "
        f"{len(logical_nets)} logical nets"
    )
    if errors:
        for error in errors:
            print("ERROR", error)
        raise SystemExit(1)
    print("PASS: no missing pins, split nets, or shorted nets")


if __name__ == "__main__":
    main()
