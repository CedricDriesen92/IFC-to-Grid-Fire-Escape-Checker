"""Cell types as small integer codes, and the compact grid format of the API.

Grids travel either as nested lists of cell names (the original format, still accepted everywhere) or packed:
per floor a list of row strings with one character per cell. Packed grids are about 8 times smaller in JSON and
turn into a numpy array without a Python loop per cell."""
from typing import Any, List

import numpy as np

NAMES = ('empty', 'floor', 'wall', 'door', 'stair', 'walla')
CODES = {name: code for code, name in enumerate(NAMES)}
EMPTY, FLOOR, WALL, DOOR, STAIR, WALLA = range(len(NAMES))
CHARS = 'efwdsa'                  # packed character of each code
PASSABLE = (FLOOR, DOOR, STAIR)

_NAME_ARRAY = np.array(NAMES, dtype=object)
_CHAR_BYTES = np.frombuffer(CHARS.encode('ascii'), dtype=np.uint8)
_FROM_CHAR = np.zeros(256, dtype=np.uint8)
for _code, _char in enumerate(CHARS):
    _FROM_CHAR[ord(_char)] = _code


def is_packed(grids: Any) -> bool:
    """True for packed grids: floors of row strings."""
    return bool(grids) and len(grids[0]) > 0 and isinstance(grids[0][0], str)


def floor_codes(grid: Any) -> np.ndarray:
    """One floor (nested list of names, list of packed rows, or an array) as a uint8 code array."""
    if isinstance(grid, np.ndarray):
        if grid.dtype == np.uint8:
            return grid
        grid = grid.tolist()
    if len(grid) and isinstance(grid[0], str):
        rows = len(grid)
        flat = np.frombuffer(''.join(grid).encode('ascii'), dtype=np.uint8)
        return _FROM_CHAR[flat].reshape(rows, -1)
    names = np.asarray(grid, dtype='<U5')
    out = np.zeros(names.shape, dtype=np.uint8)  # unknown names read as empty
    for name, code in CODES.items():
        if code:
            out[names == name] = code
    return out


def to_codes(grids: Any) -> List[np.ndarray]:
    return [floor_codes(g) for g in grids]


def to_names(codes: List[np.ndarray]) -> List[List[List[str]]]:
    return [_NAME_ARRAY[c].tolist() for c in codes]


def pack(codes: List[np.ndarray]) -> List[List[str]]:
    out = []
    for c in codes:
        text = _CHAR_BYTES[c].tobytes().decode('ascii')
        width = c.shape[1]
        out.append([text[i:i + width] for i in range(0, len(text), width)])
    return out


def encode(codes: List[np.ndarray], packed: bool) -> list:
    """Grids for a response, in the format the request used."""
    return pack(codes) if packed else to_names(codes)
