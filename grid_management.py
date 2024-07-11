import numpy as np
from typing import List, Dict, Tuple, Any
import logging
from shapely.geometry import Polygon, MultiPolygon, MultiPoint
from shapely.ops import unary_union
import shapely

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class GridManager:
    def __init__(self, grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float]):
        self.grid_size = grid_size
        self.floors = floors
        self.bbox = bbox
        self.current_floor = 0
        
        self.original_grids = []
        for i, grid in enumerate(grids):
            if not grid:
                raise ValueError(f"Empty grid provided for floor {i}")
            self.original_grids.append(np.array(grid))
        
        self.buffered_grids = [grid.copy() for grid in self.original_grids]

    def edit_grid(self, edits: List[Dict[str, Any]]) -> List[List[List[str]]]:
        """Apply multiple edits to the grid."""
        for edit in edits:
            self.draw(edit['floor'], edit['row'], edit['col'], edit['element_type'])
        return [grid.tolist() for grid in self.grids]

    def draw(self, floor: int, row: int, col: int, element_type: str) -> None:
        """Draw an element on the grid."""
        if self._is_valid_coordinate(floor, row, col):
            self.grids[floor][row, col] = element_type
        else:
            raise ValueError("Invalid grid coordinates")

    def get_grid(self, floor: int) -> np.ndarray:
        """Get the grid for a specific floor."""
        if 0 <= floor < len(self.grids):
            return self.grids[floor]
        else:
            raise ValueError("Invalid floor number")

    def get_all_grids(self) -> List[np.ndarray]:
        """Get all grids."""
        return self.grids

    def set_current_floor(self, floor: int) -> None:
        """Set the current floor."""
        if 0 <= floor < len(self.grids):
            self.current_floor = floor
        else:
            raise ValueError("Invalid floor number")

    def get_current_floor(self) -> int:
        """Get the current floor number."""
        return self.current_floor

    def get_grid_info(self) -> Dict[str, Any]:
        """Get information about the grid."""
        return {
            'num_floors': len(self.grids),
            'grid_size': self.grid_size,
            'floors': self.floors,
            'bbox': self.bbox
        }

    def clear_floor(self, floor: int) -> None:
        """Clear all elements on a specific floor, setting them to 'empty'."""
        if 0 <= floor < len(self.grids):
            self.grids[floor].fill('empty')
        else:
            raise ValueError("Invalid floor number")

    def flood_fill(self, floor: int, row: int, col: int, target_element: str, replacement_element: str) -> None:
        """Perform a flood fill operation starting from a specific point."""
        if not self._is_valid_coordinate(floor, row, col):
            return
        
        if self.grids[floor][row, col] != target_element or target_element == replacement_element:
            return

        self.grids[floor][row, col] = replacement_element

        # Recursively fill adjacent cells
        for dr, dc in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            self.flood_fill(floor, row + dr, col + dc, target_element, replacement_element)

    def validate_grid(self) -> List[str]:
        """Validate the grid to ensure all elements are valid."""
        valid_elements = {'wall', 'stair', 'door', 'floor', 'empty'}
        errors = []

        for floor in range(len(self.grids)):
            for row in range(self.grids[floor].shape[0]):
                for col in range(self.grids[floor].shape[1]):
                    element = self.grids[floor][row, col]
                    if element not in valid_elements:
                        errors.append(f"Invalid element '{element}' at floor {floor}, row {row}, col {col}")

        return errors

    def resize_grid(self, new_rows: int, new_cols: int) -> None:
        """Resize all floor grids to the specified dimensions."""
        for floor in range(len(self.grids)):
            old_grid = self.grids[floor]
            new_grid = np.full((new_rows, new_cols), 'empty', dtype=object)

            # Copy the old grid into the new grid
            rows_to_copy = min(old_grid.shape[0], new_rows)
            cols_to_copy = min(old_grid.shape[1], new_cols)
            new_grid[:rows_to_copy, :cols_to_copy] = old_grid[:rows_to_copy, :cols_to_copy]

            self.grids[floor] = new_grid

        # Update bbox
        self.bbox['max_x'] = self.bbox['min_x'] + new_cols * self.grid_size
        self.bbox['max_y'] = self.bbox['min_y'] + new_rows * self.grid_size

    def add_floor(self) -> None:
        """Add a new floor to the grid."""
        new_floor = np.full_like(self.grids[0], 'empty', dtype=object)
        self.grids.append(new_floor)
        self.floors.append({
            'elevation': self.floors[-1]['elevation'] + self.floors[-1]['height'],
            'height': self.floors[-1]['height']
        })

    def remove_floor(self, floor: int) -> None:
        """Remove a specific floor from the grid."""
        if 0 < floor < len(self.grids):  # Prevent removing the ground floor
            del self.grids[floor]
            del self.floors[floor]
        else:
            raise ValueError("Cannot remove the specified floor")

    def apply_wall_buffer(self, buffer_distance: int) -> List[List[List[str]]]:
        for floor, original_grid in enumerate(self.original_grids):
            buffered_grid = original_grid.copy()
            wall_mask = (original_grid == 'wall')
            
            for _ in range(buffer_distance):
                wall_mask = self._expand_mask(wall_mask)

            rows, cols = wall_mask.shape
            for i in range(rows):
                for j in range(cols):
                    if wall_mask[i, j] and original_grid[i, j] not in ['wall', 'door', 'stair']:
                        buffered_grid[i, j] = 'walla'
            
            self.buffered_grids[floor] = buffered_grid

        return [grid.tolist() for grid in self.buffered_grids]

    def _expand_mask(self, mask: np.ndarray) -> np.ndarray:
        expanded = mask.copy()
        rows, cols = mask.shape
        for i in range(rows):
            for j in range(cols):
                if mask[i, j]:
                    for di in [-1, 0, 1]:
                        for dj in [-1, 0, 1]:
                            if 0 <= i + di < rows and 0 <= j + dj < cols:
                                expanded[i + di, j + dj] = True
        return expanded
    
    def update_cell(self, floor: int, row: int, col: int, cell_type: str) -> None:
        if 0 <= floor < len(self.original_grids):
            self.original_grids[floor][row, col] = cell_type
        else:
            raise ValueError(f"Invalid floor number: {floor}")

    def get_original_grids(self) -> List[List[List[str]]]:
        return [grid.tolist() for grid in self.original_grids]

    def get_buffered_grids(self) -> List[List[List[str]]]:
        return [grid.tolist() for grid in self.buffered_grids]

    def _is_valid_coordinate(self, floor: int, row: int, col: int) -> bool:
        """Check if the given coordinate is valid."""
        return (0 <= floor < len(self.grids) and
                0 <= row < self.grids[floor].shape[0] and
                0 <= col < self.grids[floor].shape[1])
    
    def detect_spaces(self, include_empty_tiles: bool = False) -> List[Dict[str, Any]]:
        spaces = []
        for floor_index, grid in enumerate(self.original_grids):
            space_id = 0
            visited = np.zeros_like(grid, dtype=bool)
            for i in range(grid.shape[0]):
                for j in range(grid.shape[1]):
                    if not visited[i, j] and (grid[i, j] == 'floor' or (include_empty_tiles and grid[i, j] == 'empty')):
                        space_id += 1
                        space = self._flood_fill(grid, visited, i, j, floor_index, space_id, include_empty_tiles)
                        if space:
                            border = self._find_space_borders(grid, space['points'], include_empty_tiles)
                            volume = len(space['points'])*(self.grid_size ** 2)
                            area = len(border)*(self.grid_size ** 1)
                            print("V: " + str(volume) + " area: " + str(area))
                            if volume > 1:
                                space['polygon'] = self._create_polygon(border)
                                spaces.append(space)
        return spaces

    def _flood_fill(self, grid, visited, i, j, floor_index, space_id, include_empty_tiles):
        stack = [(i, j)]
        points = []
        allowed_types = {'floor', 'empty'} if include_empty_tiles else {'floor'}

        while stack:
            x, y = stack.pop()
            if visited[x, y]:
                continue
            visited[x, y] = True
            points.append((x, y))

            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < grid.shape[0] and 0 <= ny < grid.shape[1]:
                    if grid[nx, ny] in allowed_types and not visited[nx, ny]:
                        stack.append((nx, ny))

        if points:
            return {
                "id": f"Space_{floor_index}_{space_id}",
                "name": f"Space {floor_index}_{space_id}",
                "floor": floor_index,
                "points": points
            }
        return None

    def _find_space_borders(self, grid, points, include_empty_tiles):
        allowed_types = {'floor', 'empty'} if include_empty_tiles else {'floor'}
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
                    border.append(next_point)
                    current = next_point
                    current_dir = next_dir
                    break
                current_dir = (current_dir + 1) % 4  # Turn right if we can't go left
            else:
                # If we've checked all directions and found nothing, we're done
                return border

    def _create_polygon(self, border_points):
        # Convert grid coordinates to world coordinates
        return [(y * self.grid_size + self.bbox['min_x'], 
                 x * self.grid_size + self.bbox['min_y']) 
                for x, y in border_points]
    
    # Helper function to validate input data
def validate_grid_data(grids, grid_size, floors, bbox):
    logger.debug(f"Validating grid data: grid_size={grid_size}, floors={floors}, bbox={bbox}")
    logger.debug(f"Grids type: {type(grids)}")
    
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
        if not isinstance(grid[0], list):
            raise ValueError(f"Grid {i} must be a 2D list, got 1D list")
    
    for i, grid in enumerate(grids):
        logger.debug(f"Validating grid {i}: type={type(grid)}")
        if not isinstance(grid, list):
            raise ValueError(f"Grid {i} must be a list, got {type(grid)}")
        if not grid:
            logger.warning(f"Grid {i} is empty")
            continue
        if not isinstance(grid[0], list):
            raise ValueError(f"Grid {i} must be a 2D list, got 1D list")
        
        grid_shape = (len(grid), len(grid[0]))
        logger.debug(f"Grid {i} dimensions: {grid_shape}")

    logger.debug(f"Grid data validated. Number of grids: {len(grids)}")