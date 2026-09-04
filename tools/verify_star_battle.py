#!/usr/bin/env python3
"""Verify and uniquely solve the recovered high-level Star Battle puzzle."""

from argparse import ArgumentParser
from collections import Counter
from itertools import combinations
from pathlib import Path

from z3 import Bool, If, Or, Solver, Sum, sat, unsat


def load_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def enumerate_without_smt(
    regions: list[str], limit: int = 2
) -> tuple[list[str], int]:
    """Enumerate up to ``limit`` solutions with a plain Python backtracker."""
    row_masks = [
        (1 << left) | (1 << right)
        for left, right in combinations(range(11), 2)
        if right > left + 1
    ]
    column_counts = [0] * 11
    region_counts = {label: 0 for label in "ABCDEFGHIJK"}
    answers: list[str] = []
    nodes = 0

    def search(row: int, previous: int, chosen: list[int]) -> None:
        nonlocal nodes
        nodes += 1
        if len(answers) >= limit:
            return
        if row == 11:
            if all(count == 2 for count in column_counts) and all(
                count == 2 for count in region_counts.values()
            ):
                answers.append("".join(
                    "1" if mask & (1 << column) else "0"
                    for mask in chosen for column in range(11)
                ))
            return

        remaining_rows = 10 - row
        forbidden = previous | (previous << 1) | (previous >> 1)
        for mask in row_masks:
            if mask & forbidden:
                continue
            columns = [column for column in range(11) if mask & (1 << column)]
            labels = [regions[row][column] for column in columns]
            if any(column_counts[column] >= 2 for column in columns):
                continue
            if any(
                region_counts[label] + labels.count(label) > 2
                for label in set(labels)
            ):
                continue

            for column in columns:
                column_counts[column] += 1
            for label in labels:
                region_counts[label] += 1

            # Every deficient column must still have enough rows left to reach 2.
            if all(
                column_counts[column] + remaining_rows >= 2
                for column in range(11)
            ):
                search(row + 1, mask, chosen + [mask])

            for column in columns:
                column_counts[column] -= 1
            for label in labels:
                region_counts[label] -= 1

    search(0, 0, [])
    return answers, nodes


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("region_map", type=Path)
    parser.add_argument("solution_bits", type=Path)
    args = parser.parse_args()

    regions = load_lines(args.region_map)
    if len(regions) != 11 or any(len(row) != 11 for row in regions):
        raise SystemExit("region map must be 11 rows of 11 labels")

    labels = sorted(set("".join(regions)))
    if labels != list("ABCDEFGHIJK"):
        raise SystemExit(f"expected regions A-K, got {labels}")

    bits = "".join(args.solution_bits.read_text().split())
    if len(bits) != 121 or set(bits) - {"0", "1"}:
        raise SystemExit("solution must contain exactly 121 binary digits")

    x = [[Bool(f"x_{r}_{c}") for c in range(11)] for r in range(11)]
    solver = Solver()

    for row in x:
        solver.add(Sum([If(cell, 1, 0) for cell in row]) == 2)
    for c in range(11):
        solver.add(Sum([If(x[r][c], 1, 0) for r in range(11)]) == 2)
    for label in labels:
        cells = [x[r][c] for r in range(11) for c in range(11)
                 if regions[r][c] == label]
        solver.add(Sum([If(cell, 1, 0) for cell in cells]) == 2)

    # No two stars may touch, including diagonally.  Add each pair once.
    for r in range(11):
        for c in range(11):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < 11 and 0 <= cc < 11:
                    solver.add(Or(~x[r][c], ~x[rr][cc]))

    if solver.check() != sat:
        raise SystemExit("recovered high-level puzzle is unsatisfiable")
    model = solver.model()
    solved = "".join(
        "1" if bool(model.evaluate(x[r][c])) else "0"
        for r in range(11) for c in range(11)
    )
    if solved != bits:
        raise SystemExit("high-level solution differs from gate-level solution")

    solver.add(Or([
        x[r][c] != (bits[11 * r + c] == "1")
        for r in range(11) for c in range(11)
    ]))
    if solver.check() != unsat:
        raise SystemExit("high-level puzzle has more than one solution")

    plain_answers, nodes = enumerate_without_smt(regions)
    if plain_answers != [bits]:
        raise SystemExit(
            f"plain backtracker found {len(plain_answers)} unexpected solutions"
        )

    sizes = Counter("".join(regions))
    print("PASS: high-level Star Battle solution matches gate-level bitstream")
    print("PASS: blocking the solution is UNSAT (unique)")
    print(f"PASS: independent backtracker found one solution ({nodes} nodes)")
    print("region sizes:", " ".join(f"{label}={sizes[label]}" for label in labels))


if __name__ == "__main__":
    main()
