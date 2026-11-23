import numpy as np
from scipy import ndimage
from typing import List, Dict, Tuple, Any
import logging

from grid_codec import CODES, NAMES, EMPTY, FLOOR, WALL, DOOR, STAIR, WALLA, to_codes, encode

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

_NAME_ARRAY = np.array(NAMES, dtype=object)


class GridManager:
    """Grids of one model, held as uint8 cell codes (grid_codec). Accepts and returns nested lists of cell names
    or packed rows."""

    def __init__(self, grids: List[Any], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float]):
        self.grid_size = grid_size
        self.floors = floors
        self.bbox = bbox
        self.current_floor = 0

        for i, grid in enumerate(grids):
            if grid is None or len(grid) == 0:
                raise ValueError(f"Empty grid provided for floor {i}")
        self.codes = [c.copy() for c in to_codes(grids)]
        self.buffered_codes = [c.copy() for c in self.codes]
        self.grids = self.codes  # the editing methods below work on the original grids

    @property
    def original_grids(self) -> List[np.ndarray]:
        return [_NAME_ARRAY[c] for c in self.codes]

    @property
    def buffered_grids(self) -> List[np.ndarray]:
        return [_NAME_ARRAY[c] for c in self.buffered_codes]

    def edit_grid(self, edits: List[Dict[str, Any]]) -> List[List[List[str]]]:
        """Apply multiple edits to the grid."""
        for edit in edits:
            self.draw(edit['floor'], edit['row'], edit['col'], edit['element_type'])
        return encode(self.codes, False)

    def draw(self, floor: int, row: int, col: int, element_type: str) -> None:
        """Draw an element on the grid."""
        if self._is_valid_coordinate(floor, row, col):
            self.codes[floor][row, col] = CODES[element_type]
        else:
            raise ValueError("Invalid grid coordinates")

    def get_grid(self, floor: int) -> np.ndarray:
        """Get the grid (cell names) for a specific floor."""
        if 0 <= floor < len(self.codes):
            return _NAME_ARRAY[self.codes[floor]]
        raise ValueError("Invalid floor number")

    def get_all_grids(self) -> List[np.ndarray]:
        return self.original_grids

    def set_current_floor(self, floor: int) -> None:
        if 0 <= floor < len(self.codes):
            self.current_floor = floor
        else:
            raise ValueError("Invalid floor number")

    def get_current_floor(self) -> int:
        return self.current_floor

    def get_grid_info(self) -> Dict[str, Any]:
        return {
            'num_floors': len(self.codes),
            'grid_size': self.grid_size,
            'floors': self.floors,
            'bbox': self.bbox
        }

    def clear_floor(self, floor: int) -> None:
        """Clear all elements on a specific floor, setting them to 'empty'."""
        if 0 <= floor < len(self.codes):
            self.codes[floor].fill(EMPTY)
        else:
            raise ValueError("Invalid floor number")

    def flood_fill(self, floor: int, row: int, col: int, target_element: str, replacement_element: str) -> None:
        """Replace the 4-connected region of target_element around (row, col) by replacement_element."""
        if not self._is_valid_coordinate(floor, row, col) or target_element == replacement_element:
            return
        grid = self.codes[floor]
        target, replacement = CODES[target_element], CODES[replacement_element]
        if grid[row, col] != target:
            return
        labels, _ = ndimage.label(grid == target)
        grid[labels == labels[row, col]] = replacement

    def validate_grid(self) -> List[str]:
        """Cells are stored as known codes, so there is nothing invalid left to report."""
        return []

    def resize_grid(self, new_rows: int, new_cols: int) -> None:
        """Resize all floor grids to the specified dimensions."""
        for floor, old_grid in enumerate(self.codes):
            new_grid = np.full((new_rows, new_cols), EMPTY, dtype=np.uint8)
            rows_to_copy = min(old_grid.shape[0], new_rows)
            cols_to_copy = min(old_grid.shape[1], new_cols)
            new_grid[:rows_to_copy, :cols_to_copy] = old_grid[:rows_to_copy, :cols_to_copy]
            self.codes[floor] = new_grid
        self.bbox['max_x'] = self.bbox['min_x'] + new_cols * self.grid_size
        self.bbox['max_y'] = self.bbox['min_y'] + new_rows * self.grid_size

    def add_floor(self) -> None:
        self.codes.append(np.full_like(self.codes[0], EMPTY))
        self.floors.append({
            'elevation': self.floors[-1]['elevation'] + self.floors[-1]['height'],
            'height': self.floors[-1]['height']
        })

    def remove_floor(self, floor: int) -> None:
        if 0 < floor < len(self.codes):  # Prevent removing the ground floor
            del self.codes[floor]
            del self.floors[floor]
        else:
            raise ValueError("Cannot remove the specified floor")

    def apply_wall_buffer(self, buffer_distance: int, packed: bool = False) -> List[Any]:
        """Block ('walla') every cell a person cannot pass through when the clear width must be 2 * buffer cells.

        A passage of exactly 2 * buffer free cells (0.8 m for a buffer of 4 at 0.1 m) stays open and one cell
        narrower closes: cells within buffer - 1 cells of a wall (a disc, so diagonal passages are judged like
        straight ones) are blocked, and of the rest only cells in a free 2 x 2 block are kept. Door cells are
        judged the same way, so the opening itself is measured: a door too narrow to pass is blocked."""
        try:
            b = int(buffer_distance)
            for floor, grid in enumerate(self.codes):
                buffered = grid.copy()
                if b > 0:
                    blocked = self._dilate_disk(grid == WALL, b - 1)
                    free = ~blocked & ((grid == FLOOR) | (grid == STAIR) | (grid == DOOR))
                    narrow = blocked | (free & ~self._in_free_2x2(free))
                    buffered[narrow & (grid != WALL)] = WALLA
                self.buffered_codes[floor] = buffered
            return encode(self.buffered_codes, packed)
        except Exception as e:
            logger.error(f"Error in apply_wall_buffer: {str(e)}", exc_info=True)
            raise ValueError(f"Error applying wall buffer: {str(e)}")

    @staticmethod
    def _dilate_disk(mask: np.ndarray, radius: int) -> np.ndarray:
        """Cells within `radius` cells (Euclidean, centre to centre) of a True cell."""
        if radius <= 0:
            return mask.copy()
        rows, cols = mask.shape
        padded = np.pad(mask, radius)
        out = np.zeros_like(mask)
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if di * di + dj * dj <= radius * radius:
                    out |= padded[radius + di:radius + di + rows, radius + dj:radius + dj + cols]
        return out

    @staticmethod
    def _in_free_2x2(free: np.ndarray) -> np.ndarray:
        """Free cells that belong to at least one 2 x 2 block of free cells."""
        block = free[:-1, :-1] & free[1:, :-1] & free[:-1, 1:] & free[1:, 1:]
        keep = np.zeros_like(free)
        keep[:-1, :-1] |= block
        keep[1:, :-1] |= block
        keep[:-1, 1:] |= block
        keep[1:, 1:] |= block
        return keep

    def update_cell(self, floor: int, row: int, col: int, cell_type: str) -> None:
        if 0 <= floor < len(self.codes):
            self.codes[floor][row, col] = CODES.get(cell_type, EMPTY)
        else:
            raise ValueError(f"Invalid floor number: {floor}")

    def get_original_grids(self, packed: bool = False) -> List[Any]:
        return encode(self.codes, packed)

    def get_buffered_grids(self, packed: bool = False) -> List[Any]:
        return encode(self.buffered_codes, packed)

    def _is_valid_coordinate(self, floor: int, row: int, col: int) -> bool:
        return (0 <= floor < len(self.codes) and
                0 <= row < self.codes[floor].shape[0] and
                0 <= col < self.codes[floor].shape[1])

    def detect_spaces(self, include_empty_tiles: bool = False, ifc_spaces: List[Dict[str, Any]] = None,
                      source: str = 'ifc') -> List[Dict[str, Any]]:
        """The spaces routes are checked for.

        source 'ifc' (default): the IfcSpaces of the model, on every floor that has any; the other floors get the
        detected regions as a fallback. source 'detected': detected regions everywhere."""
        ifc_spaces = ifc_spaces or []
        if source == 'detected' or not ifc_spaces:
            return self._detected_regions(include_empty_tiles)
        ifc_floors = {s['floor'] for s in ifc_spaces}
        fallback = [f for f in range(len(self.codes)) if f not in ifc_floors]
        # Walkable area that no IfcSpace covers is still checked, as detected regions of at least 1 m².
        covered = [np.zeros(c.shape, bool) for c in self.codes]
        for ifc_space in ifc_spaces:
            if 0 <= ifc_space['floor'] < len(self.codes):
                cells = runs_to_cells(ifc_space.get('runs'), self.codes[ifc_space['floor']].shape)
                covered[ifc_space['floor']][cells[:, 0], cells[:, 1]] = True
        leftover = self._detected_regions(include_empty_tiles, sorted(ifc_floors), exclude=covered, min_area=1.0,
                                          prefix="Outside IfcSpaces")
        return (self._ifc_regions(ifc_spaces, include_empty_tiles) + leftover +
                self._detected_regions(include_empty_tiles, fallback))

    def _ifc_regions(self, ifc_spaces: List[Dict[str, Any]], include_empty_tiles: bool = False) -> List[Dict[str, Any]]:
        """IfcSpace footprints (runs of cells from the conversion); a space's points are its cells a person can
        stand on, its polygon the outline of its footprint."""
        spaces = []
        walkable = (FLOOR, DOOR, STAIR) + ((EMPTY,) if include_empty_tiles else ())
        for ifc_space in ifc_spaces:
            floor_index = ifc_space['floor']
            if not 0 <= floor_index < len(self.codes) or not ifc_space.get('runs'):
                continue
            grid = self.codes[floor_index]
            cells = runs_to_cells(ifc_space['runs'], grid.shape)
            if len(cells) == 0:
                continue
            values = grid[cells[:, 0], cells[:, 1]]
            standing = cells[np.isin(values, walkable)]
            footprint = [tuple(c) for c in cells.tolist()]
            spaces.append({
                "id": ifc_space.get('guid') or ifc_space['name'],
                "name": ifc_space['name'],
                "floor": floor_index,
                "points": [tuple(c) for c in standing.tolist()],
                "polygon": self._create_polygon(self._find_space_borders(grid, footprint, include_empty_tiles)),
                "area": len(cells) * self.grid_size ** 2,
                "is_stairway": bool((values == STAIR).any()) or self._check_if_stairway(grid == STAIR, footprint),
                "source": "ifc",
            })
        return spaces

    def _detected_regions(self, include_empty_tiles: bool = False, floors: List[int] = None, exclude: List[np.ndarray] = None,
                          min_area: float = 0.2, prefix: str = "Space") -> List[Dict[str, Any]]:
        """Connected regions of floor cells (and empty cells if asked) per floor, larger than 0.2 m².

        Spaces are numbered per floor in the order their first cell is met scanning the grid."""
        try:
            spaces = []
            structure = ndimage.generate_binary_structure(2, 1)
            for floor_index, grid in enumerate(self.codes):
                if floors is not None and floor_index not in floors:
                    continue
                mask = grid == FLOOR
                if include_empty_tiles:
                    mask |= grid == EMPTY
                if exclude is not None:
                    mask &= ~exclude[floor_index]
                labels, count = ndimage.label(mask, structure)
                if count == 0:
                    continue
                sizes = np.bincount(labels.ravel())
                stair = grid == STAIR
                for space_id, region in enumerate(ndimage.find_objects(labels), start=1):
                    area = sizes[space_id] * (self.grid_size ** 2)
                    if area <= min_area:
                        continue
                    local = np.argwhere(labels[region] == space_id)
                    local += (region[0].start, region[1].start)
                    points = [tuple(p) for p in local.tolist()]
                    border = self._find_space_borders(grid, points, include_empty_tiles)
                    spaces.append({
                        "id": f"{prefix} {floor_index}_{space_id}" if prefix != "Space" else f"{floor_index}_{space_id}",
                        "name": f"{prefix} {floor_index}_{space_id}",
                        "floor": floor_index,
                        "points": points,
                        "polygon": self._create_polygon(border),
                        "area": area,
                        "is_stairway": self._check_if_stairway(stair, border),
                        "source": "detected",
                    })
            return spaces
        except Exception as e:
            logger.error(f"Error in detect_spaces: {str(e)}", exc_info=True)
            raise ValueError(f"Error detecting spaces: {str(e)}")

    def _check_if_stairway(self, stair: np.ndarray, points: List[Tuple[int, int]]) -> bool:
        """Check if a space touches a stair element."""
        rows, cols = stair.shape
        for x, y in points:
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                nx_, ny_ = x + dx, y + dy
                if 0 <= nx_ < rows and 0 <= ny_ < cols and stair[nx_, ny_]:
                    return True
        return False

    def _find_space_borders(self, grid, points, include_empty_tiles):
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        points_set = set(points)
        start_point = min(points)  # Leftmost, then topmost point

        border = [start_point]
        current = start_point
        current_dir = 0  # Start going right

        while True:
            for _ in range(4):  # Check all 4 directions
                next_dir = (current_dir - 1) % 4  # Turn left
                dx, dy = directions[next_dir]
                next_point = (current[0] + dx, current[1] + dy)

                if next_point in points_set:
                    if next_point == start_point and len(border) > 2:
                        return border  # We've completed the loop
                    border.append(current)
                    current = next_point
                    current_dir = next_dir
                    break
                current_dir = (current_dir + 1) % 4  # Turn right if we can't go left
            else:
                # If we've checked all directions and found nothing, we're done
                return border

    def _create_polygon(self, border_points):
        # Convert grid coordinates to world coordinates
        min_x, min_y = self.bbox.get('min_x', 0.0), self.bbox.get('min_y', 0.0)
        return [(y * self.grid_size + min_x, x * self.grid_size + min_y) for x, y in border_points]


def runs_to_cells(runs: List[List[int]], shape: Tuple[int, int]) -> np.ndarray:
    """Runs [row, first column, last column] as an (n, 2) array of cells inside the grid."""
    if not runs:
        return np.empty((0, 2), dtype=np.int64)
    r = np.asarray(runs, dtype=np.int64)
    r = r[(r[:, 0] >= 0) & (r[:, 0] < shape[0])]
    r[:, 1] = np.clip(r[:, 1], 0, shape[1] - 1)
    r[:, 2] = np.clip(r[:, 2], 0, shape[1] - 1)
    r = r[r[:, 1] <= r[:, 2]]
    lengths = r[:, 2] - r[:, 1] + 1
    rows = np.repeat(r[:, 0], lengths)
    cols = np.repeat(r[:, 1], lengths) + np.arange(lengths.sum()) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    return np.stack([rows, cols], axis=1)


def validate_grid_data(grids, grid_size, floors, bbox):
    """Grids must be a non-empty list of floors, each a list of rows (lists of names, or packed row strings)."""
    if not isinstance(grids, list):
        raise ValueError(f"Grids must be a list, got {type(grids)}")
    if not grids:
        raise ValueError("Grids list is empty")
    for i, grid in enumerate(grids):
        if grid is None:
            raise ValueError(f"Grid {i} is None")
        if not isinstance(grid, list):
            raise ValueError(f"Grid {i} must be a list, got {type(grid)}")
        if not grid:
            raise ValueError(f"Grid {i} is an empty list")
        if not isinstance(grid[0], (list, str)):
            raise ValueError(f"Grid {i} must be a 2D list or a list of packed rows")
