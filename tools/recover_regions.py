#!/usr/bin/env python3
"""Recover the 11 irregular regions from input-to-state influence sets."""

from argparse import ArgumentParser
from collections import defaultdict
import json
from pathlib import Path

from simulate_netlist import Simulator


SIZE = 11
CELL_COUNT = SIZE * SIZE


def reset(sim: Simulator) -> dict[str, bool]:
    sim.update_ports({"clk": False, "rst_n": False, "enable": False, "I": False})
    for _ in range(3):
        sim.update_ports({"clk": True})
        sim.update_ports({"clk": False})
    sim.update_ports({"rst_n": True})
    return sim.state.copy()


def next_state(sim: Simulator, state: dict[str, bool], bit: bool) -> dict[str, bool]:
    sim.state = state.copy()
    sim.port_values.update(
        {"clk": False, "rst_n": True, "enable": True, "I": bit}
    )
    sim.settle()
    return {
        instance["name"]: bool(sim.values[instance["pins"]["D"]])
        for instance in sim.flops
    }


def exact_covers(candidates: list[frozenset[int]]) -> list[list[frozenset[int]]]:
    by_cell: dict[int, list[frozenset[int]]] = defaultdict(list)
    for candidate in candidates:
        for cell in candidate:
            by_cell[cell].append(candidate)

    answers: list[list[frozenset[int]]] = []

    def search(used: frozenset[int], chosen: list[frozenset[int]]) -> None:
        if len(chosen) == SIZE:
            if len(used) == CELL_COUNT:
                answers.append(chosen.copy())
            return
        uncovered = set(range(CELL_COUNT)) - used
        if not uncovered:
            return
        cell = min(uncovered, key=lambda item: len([
            candidate for candidate in by_cell[item] if candidate.isdisjoint(used)
        ]))
        for candidate in by_cell[cell]:
            if candidate.isdisjoint(used):
                search(used | candidate, chosen + [candidate])

    search(frozenset(), [])
    return answers


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()

    sim = Simulator(json.loads(args.netlist.read_text()))
    state = reset(sim)
    influence: dict[str, set[int]] = defaultdict(set)
    for position in range(CELL_COUNT):
        zero = next_state(sim, state, False)
        one = next_state(sim, state, True)
        for flop in state:
            if zero[flop] != one[flop]:
                influence[flop].add(position)
        state = zero

    columns = {
        frozenset(range(column, CELL_COUNT, SIZE)) for column in range(SIZE)
    }
    candidates = sorted(
        {frozenset(cells) for cells in influence.values()} - columns,
        key=lambda cells: (len(cells), sorted(cells)),
    )
    covers = exact_covers(candidates)
    if len(covers) != 1:
        raise SystemExit(f"expected one 11-set exact cover, found {len(covers)}")

    regions = sorted(covers[0], key=min)
    labels = {}
    representatives = {}
    for index, cells in enumerate(regions):
        label = chr(ord("A") + index)
        for cell in cells:
            labels[cell] = label
        representatives[label] = sorted(
            name for name, positions in influence.items() if frozenset(positions) == cells
        )

    rendered = "\n".join(
        "".join(labels[SIZE * row + column] for column in range(SIZE))
        for row in range(SIZE)
    )
    print(rendered)
    print()
    for label, cells in zip("ABCDEFGHIJK", regions):
        print(f"{label}: {len(cells):2d} cells, flop={','.join(representatives[label])}")

    if args.expected:
        expected = "\n".join(
            line.strip() for line in args.expected.read_text().splitlines() if line.strip()
        )
        if rendered != expected:
            raise SystemExit("recovered map differs from expected map")
        print("PASS: recovered map matches expected artifact")


if __name__ == "__main__":
    main()
