#!/usr/bin/env python3
"""Boolean/event simulator for the gate netlist recovered by gds_extract.py."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path


OUTPUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
FLOP_PREFIXES = ("dfrtp", "dfstp", "dfxtp")


def active_input(pin, value):
    return not value if pin.endswith("_N") else value


def gate_value(master, pins, values):
    """Evaluate one combinational SKY130 cell and return (pin, value)."""
    base = master.rsplit("_", 1)[0]
    output = "Y" if "Y" in pins else "X"
    inputs = {p: active_input(p, values[n]) for p, n in pins.items() if p not in OUTPUT_PINS}

    if base in {"buf", "clkbuf"} or base.startswith("clkbuf"):
        result = inputs["A"]
    elif base == "inv":
        result = not inputs["A"]
    elif base == "mux2":
        result = inputs["A1"] if inputs["S"] else inputs["A0"]
    elif base == "xor2":
        result = inputs["A"] ^ inputs["B"]
    elif base == "xnor2":
        result = not (inputs["A"] ^ inputs["B"])
    elif base.startswith("nand"):
        result = not all(inputs.values())
    elif base.startswith("and"):
        result = all(inputs.values())
    elif base.startswith("nor"):
        result = not any(inputs.values())
    elif base.startswith("or"):
        result = any(inputs.values())
    elif base.startswith("a") and "o" in base:
        groups = defaultdict(list)
        for pin, value in inputs.items():
            groups[pin[0]].append(value)
        result = any(all(group) for group in groups.values())
        if output == "Y":
            result = not result
    elif base.startswith("o") and "a" in base:
        groups = defaultdict(list)
        for pin, value in inputs.items():
            groups[pin[0]].append(value)
        result = all(any(group) for group in groups.values())
        if output == "Y":
            result = not result
    else:
        raise ValueError(f"unsupported combinational cell {master}")
    return output, bool(result)


class Simulator:
    def __init__(self, netlist):
        self.data = netlist
        self.instances = netlist["instances"]
        self.ports = netlist["ports"]
        self.comb = [i for i in self.instances if not i["master"].startswith(FLOP_PREFIXES)]
        self.flops = [i for i in self.instances if i["master"].startswith(FLOP_PREFIXES)]
        self.values = defaultdict(bool)
        self.port_values = {name: False for name in self.ports}
        self.state = {i["name"]: False for i in self.flops}

        driver = {}
        for index, instance in enumerate(self.comb):
            for pin, net in instance["pins"].items():
                if pin in OUTPUT_PINS:
                    driver.setdefault(net, index)
        dependencies = [set() for _ in self.comb]
        users = defaultdict(set)
        for index, instance in enumerate(self.comb):
            for pin, net in instance["pins"].items():
                if pin in OUTPUT_PINS:
                    continue
                source = driver.get(net)
                if source is not None and source != index:
                    dependencies[index].add(source)
                    users[source].add(index)
        queue = deque(i for i, deps in enumerate(dependencies) if not deps)
        order = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for user in users[current]:
                dependencies[user].discard(current)
                if not dependencies[user]:
                    queue.append(user)
        if len(order) != len(self.comb):
            cyclic = [self.comb[i]["name"] for i, deps in enumerate(dependencies) if deps]
            raise RuntimeError(f"combinational cycle involving {cyclic[:20]}")
        self.comb_order = [self.comb[i] for i in order]
        self.settle()

    def settle(self):
        for name, value in self.port_values.items():
            self.values[self.ports[name]] = value
        for instance in self.flops:
            self.values[instance["pins"]["Q"]] = self.state[instance["name"]]
        for instance in self.comb_order:
            pins = instance["pins"]
            if instance["master"].startswith("conb"):
                self.values[pins["HI"]] = True
                self.values[pins["LO"]] = False
            else:
                output, value = gate_value(instance["master"], pins, self.values)
                self.values[pins[output]] = value

    def apply_async(self):
        changed = False
        for instance in self.flops:
            pins = instance["pins"]
            if instance["master"].startswith("dfrtp") and not self.values[pins["RESET_B"]]:
                new = False
            elif instance["master"].startswith("dfstp") and not self.values[pins["SET_B"]]:
                new = True
            else:
                continue
            if self.state[instance["name"]] != new:
                self.state[instance["name"]] = new
                changed = True
        if changed:
            self.settle()

    def update_ports(self, changes):
        """Apply simultaneous input changes and clock all newly rising flop clocks."""
        self.settle()
        old_clocks = {i["name"]: self.values[i["pins"]["CLK"]] for i in self.flops}
        self.port_values.update(changes)
        self.settle()
        self.apply_async()
        updates = {}
        for instance in self.flops:
            pins = instance["pins"]
            rising = not old_clocks[instance["name"]] and self.values[pins["CLK"]]
            reset = instance["master"].startswith("dfrtp") and not self.values[pins["RESET_B"]]
            preset = instance["master"].startswith("dfstp") and not self.values[pins["SET_B"]]
            if rising and not reset and not preset:
                updates[instance["name"]] = self.values[pins["D"]]
        if updates:
            self.state.update(updates)
            self.settle()
            self.apply_async()

    def outputs(self):
        value = 0
        for bit in range(8):
            if self.values[self.ports[f"O[{bit}]"]]:
                value |= 1 << bit
        return value, self.values[self.ports["success"]]


def parse_vcd_events(path):
    events = defaultdict(dict)
    names = {}
    time = 0
    for raw in path.read_text().splitlines():
        line = raw.strip()
        match = re.match(r"\$var\s+\w+\s+\d+\s+(\S+)\s+(\S+)", line)
        if match:
            symbol, name = match.groups()
            names[symbol] = name
        elif line.startswith("#"):
            time = int(line[1:])
        elif len(line) >= 2 and line[0] in "01" and line[1:] in names:
            name = names[line[1:]]
            if name in {"clk", "rst_n", "enable", "I"}:
                events[time][name] = line[0] == "1"
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--replay-vcd", type=Path)
    args = parser.parse_args()
    sim = Simulator(json.loads(args.netlist.read_text()))
    if args.replay_vcd:
        last = None
        for time, changes in sorted(parse_vcd_events(args.replay_vcd).items()):
            sim.update_ports(changes)
            now = sim.outputs()
            if now != last:
                print(f"{time:8d}: O=0x{now[0]:02x} success={int(now[1])}")
                last = now
    else:
        print("O=0x%02x success=%d" % sim.outputs())


if __name__ == "__main__":
    main()
