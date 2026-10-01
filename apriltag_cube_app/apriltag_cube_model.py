"""
    Geometry construction for a two-colour cube with an AprilTag (tag16h5) on each face.

    The cube is split into two solids that together fill the cube exactly:
      * "white": the cube with the black tag cells cut out as shallow pockets
      * "black": the tag cells that fill those pockets
    Both are exported as separate bodies in one STEP file, so a multimaterial
    slicer can assign one filament to each body.

    Can also be run standalone:  python apriltag_cube_model.py --id 3 --size 40 --out cube.step
"""

from __future__ import annotations

import argparse

from build123d import Box, Compound, Part, Pos, Rot, export_step

# Official codes of the AprilTag tag16h5 family (AprilRobotics/apriltag, tag16h5.c).
TAG16H5_CODES = [
    0x27C8, 0x31B6, 0x3859, 0x569C, 0x6C76, 0x7DDB, 0xAF09, 0xF5A1, 0xFB8B, 0x1CB9,
    0x28CA, 0xE8DC, 0x1426, 0x5770, 0x9253, 0xB702, 0x063A, 0x8F34, 0xB4C0, 0x51EC,
    0xE6F0, 0x5FA4, 0xDD43, 0x1AAA, 0xE62F, 0x6DBC, 0xB6EB, 0xDE10, 0x154D, 0xB57A,
]

# (x, y) of each code bit inside the 6x6 black-bordered square; bit 0 is the MSB.
_BIT_XY = [(1, 1), (2, 1), (3, 1), (2, 2), (4, 1), (4, 2), (4, 3), (3, 2),
           (4, 4), (3, 4), (2, 4), (3, 3), (1, 4), (1, 3), (1, 2), (2, 3)]

GRID = 8  # total tag width in cells: 6x6 black-bordered tag + 1 white cell margin


def tag16h5_grid(tag_id: int) -> list[list[bool]]:
    """Return an 8x8 grid [row][col] (row 0 = top) where True means a black cell."""
    if not 0 <= tag_id < len(TAG16H5_CODES):
        raise ValueError(f"tag16h5 id must be between 0 and {len(TAG16H5_CODES) - 1}.")
    code = TAG16H5_CODES[tag_id]
    black = [[False] * GRID for _ in range(GRID)]
    for r in range(1, 7):
        for c in range(1, 7):
            black[r][c] = True  # border ring + data, data bits overwritten below
    for i, (x, y) in enumerate(_BIT_XY):
        is_white = bool(code & (1 << (15 - i)))
        black[y + 1][x + 1] = not is_white
    return black


def _face_cells(tag_id: int, size: float, depth: float) -> list[Part]:
    """Black cells for the +Z face, viewed from outside (x right, y up)."""
    cell = size / GRID
    grid = tag16h5_grid(tag_id)
    boxes = []
    for r in range(GRID):
        for c in range(GRID):
            if grid[r][c]:
                x = -size / 2 + (c + 0.5) * cell
                y = size / 2 - (r + 0.5) * cell
                z = size / 2 - depth / 2
                boxes.append(Pos(x, y, z) * Box(cell, cell, depth))
    return boxes


# Rotations taking the +Z face to each of the six faces (proper rotations, so no mirroring).
_FACE_ROTATIONS = [(0, 0, 0), (180, 0, 0), (90, 0, 0), (-90, 0, 0), (0, 90, 0), (0, -90, 0)]


def build_apriltag_cube(tag_id: int, size: float, depth: float = 1.0) -> Compound:
    """Build a compound with two bodies (labels 'white' and 'black')."""
    if size <= 0:
        raise ValueError("Cube size must be greater than 0.")
    if not 0 < depth < size / 2:
        raise ValueError("Tag depth must be positive and smaller than half the cube size.")

    cells = _face_cells(tag_id, size, depth)
    face_parts = []
    for rot in _FACE_ROTATIONS:
        for b in cells:
            face_parts.append(Rot(*rot) * b)

    black = Part(face_parts[0].fuse(*face_parts[1:]).clean().wrapped)
    white = Part(Box(size, size, size).cut(black).clean().wrapped)

    white.label, black.label = "white", "black"
    return Compound(children=[white, black], label="apriltag_cube")


def export_apriltag_cube(cube: Compound, path: str) -> None:
    export_step(cube, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="AprilTag tag16h5 two-colour cube (STEP)")
    ap.add_argument("--id", type=int, default=0, help="tag16h5 id, 0-29")
    ap.add_argument("--size", type=float, default=40.0, help="cube edge length (mm)")
    ap.add_argument("--depth", type=float, default=1.0, help="black layer depth (mm)")
    ap.add_argument("--out", default="apriltag_cube.step")
    a = ap.parse_args()
    export_apriltag_cube(build_apriltag_cube(a.id, a.size, a.depth), a.out)
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
