import networkx as nx
import numpy as np
from typing import List, Tuple, Dict, Any
from collections import defaultdict

class Pathfinder:
    def __init__(self, grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float], allow_diagonal: bool = True, minimize_cost: bool = True):
        self.grids = grids
        self.grid_size = grid_size
        self.floors = floors
        self.bbox = bbox
        self.allow_diagonal = allow_diagonal
        self.minimize_cost = minimize_cost
        self.graph = self._create_graph()

    def _create_graph(self) -> nx.Graph:
        G = nx.Graph()
        
        for floor, grid in enumerate(self.grids):
            for x in range(len(grid)):
                for y in range(len(grid[0])):
                    if grid[x][y] not in ['wall', 'walla']:
                        node = (x, y, floor)
                        G.add_node(node, floor=floor, type=grid[x][y])
                        
                        # Connect to neighbors
                        neighbors = [(0, 1), (1, 0), (0, -1), (-1, 0)]
                        if self.allow_diagonal:
                            neighbors += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
                        
                        for dx, dy in neighbors:
                            n_x, n_y = x + dx, y + dy
                            if 0 <= n_x < len(grid) and 0 <= n_y < len(grid[0]) and grid[n_x][n_y] not in ['wall', 'walla']:
                                neighbor = (n_x, n_y, floor)
                                weight = self._get_edge_weight(grid[x][y], neighbor=neighbor, is_diagonal=(dx != 0 and dy != 0))
                                G.add_edge(node, neighbor, weight=weight)
        
        self._connect_stairs(G)
        
        return G

    def _get_edge_weight(self, cell_type: str, neighbor: str = None, is_diagonal: bool = False) -> float:
        if self.minimize_cost:
            if neighbor and self != neighbor:
                weights = {
                    'empty': 1.0,
                    'floor': 1.0,
                    'door': 4,
                    'stair': 4,
                }
                weight = weights.get(cell_type, 1.0)
            else:
                weight = 1.0
        else:
            weight = 1.0  # All edges have the same weight when minimizing distance
        
        return weight * (2**0.5 if is_diagonal else 1.0)

    def _connect_stairs(self, G: nx.Graph):
        stair_positions = defaultdict(list)
        for floor, grid in enumerate(self.grids):
            for x, row in enumerate(grid):
                for y, cell in enumerate(row):
                    if cell == 'stair':
                        stair_positions[(x, y)].append(floor)
        
        for pos, floors in stair_positions.items():
            if len(floors) > 1:
                for i in range(len(floors)):
                    for j in range(i + 1, len(floors)):
                        node1 = (pos[0], pos[1], floors[i])
                        node2 = (pos[0], pos[1], floors[j])
                        if node1 in G and node2 in G:
                            G.add_edge(node1, node2, weight=self._get_edge_weight('stair'))
        
    def _calculate_path_lengths(self, path: List[Tuple[int, int, int]]) -> Dict[str, float]:
        total_length = 0
        floor_lengths = defaultdict(float)
        stairway_distance = 0
        current_floor = path[0][2]
        found_stair = False

        for i in range(len(path) - 1):
            current_node = path[i]
            next_node = path[i + 1]
            edge_length = self.graph[current_node][next_node]['weight'] * self.grid_size

            if current_node[2] == next_node[2]:  # Same floor
                floor_lengths[f"floor_{current_node[2]}"] += edge_length
                if not found_stair:
                    stairway_distance += edge_length
            else:  # Floor change
                found_stair = True

            if self.grids[current_node[2]][current_node[0]][current_node[1]] == 'stair':
                found_stair = True

            total_length += edge_length
        
        print(total_length)

        return {
            "total_length": total_length,
            "floor_lengths": dict(floor_lengths),
            "stairway_distance": stairway_distance
        }

    def detect_exits(self) -> List[Tuple[int, int, int]]:
        exits = []
        for floor_index, floor in enumerate(self.grids):
            door_groups = self._group_connected_doors(floor)
            for door_group in door_groups:
                if self._is_exit_group(floor, door_group):
                    exit_coords = self._calculate_average_position(door_group, floor_index)
                    exits.append(exit_coords)
        return exits

    def _group_connected_doors(self, floor: List[List[str]]) -> List[List[Tuple[int, int]]]:
        rows, cols = len(floor), len(floor[0])
        visited = set()
        door_groups = []

        def dfs(x, y, group):
            if (x, y) in visited or not (0 <= x < rows and 0 <= y < cols) or floor[x][y] != 'door':
                return
            visited.add((x, y))
            group.append((x, y))
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                dfs(x + dx, y + dy, group)

        for i in range(rows):
            for j in range(cols):
                if floor[i][j] == 'door' and (i, j) not in visited:
                    group = []
                    dfs(i, j, group)
                    door_groups.append(group)

        return door_groups

    def _is_exit_group(self, floor: List[List[str]], door_group: List[Tuple[int, int]]) -> bool:
        rows, cols = len(floor), len(floor[0])
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]

        for x, y in door_group:
            for dx, dy in directions:
                nx, ny = x + dx, y + dy
                if 0 <= nx < rows and 0 <= ny < cols and floor[nx][ny] not in ['wall', 'door']:
                    while 0 <= nx < rows and 0 <= ny < cols:
                        if floor[nx][ny] in ['wall', 'door']:
                            break
                        if nx == 0 or nx == rows - 1 or ny == 0 or ny == cols - 1:
                            return True
                        nx, ny = nx + dx, ny + dy

        return False

    def _calculate_average_position(self, door_group: List[Tuple[int, int]], floor_index: int) -> Tuple[int, int, int]:
        avg_x = sum(x for x, _ in door_group) / len(door_group)
        avg_y = sum(y for _, y in door_group) / len(door_group)
        return (round(avg_x), round(avg_y), floor_index)

    def find_path(self, start: Dict[str, int], goals: List[Dict[str, int]]) -> Tuple[List[Tuple[int, int, int]], Dict[str, float]]:
        start_node = (start['row'], start['col'], start['floor'])
        goal_nodes = [(goal['row'], goal['col'], goal['floor']) for goal in goals]
        
        if start_node not in self.graph:
            raise ValueError(f"Start node {start_node} is not in the graph. Cell type: {self.grids[start['floor']][start['row']][start['col']]}")
        if not all(node in self.graph for node in goal_nodes):
            invalid_goals = [node for node in goal_nodes if node not in self.graph]
            raise ValueError(f"The following goal nodes are not in the graph: {invalid_goals}")
        
        def heuristic(a, b):
            (x1, y1, z1) = a
            (x2, y2, z2) = b
            return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 + abs(z1 - z2) * 3

        path = None
        shortest_length = float('inf')
        for goal in goal_nodes:
            try:
                current_path = nx.astar_path(self.graph, start_node, goal, heuristic, weight='weight')
                current_length = sum(self.graph[current_path[i]][current_path[i+1]]['weight'] for i in range(len(current_path)-1))
                if current_length < shortest_length:
                    path = current_path
                    shortest_length = current_length
            except nx.NetworkXNoPath:
                continue

        if not path:
            return [], {}

        path_lengths = self._calculate_path_lengths(path)
        return path, path_lengths
    
    def calculate_escape_route(self, space: Dict[str, Any], exits: List[Tuple[int, int, int]]) -> Dict[str, Any]:
        print(space['name'])
        candidate_points = self._select_candidate_points(space)
        print(candidate_points)
        
        max_distance = 0
        furthest_point = None
        optimal_exit = None
        optimal_path = None
        distance_to_stair = -1  # Initialize to -1

        for point in candidate_points:
            min_exit_distance = float('inf')
            best_exit = None
            best_path = None
            current_distance_to_stair = -1  # Initialize to -1 for each point

            for exit in exits:
                exit = (exit[0], exit[1], exit[2])
                try:
                    if point not in self.graph:
                        print("point not in graph")
                    if exit not in self.graph:
                        print("exit not in graph") 
                    path = nx.astar_path(self.graph, point, exit, heuristic=self._heuristic, weight='weight')
                    distance = sum(self.graph[path[i]][path[i+1]]['weight'] for i in range(len(path)-1))
                    
                    # Calculate distance to first stair
                    stair_index = next((i for i, node in enumerate(path) if self.grids[node[2]][node[0]][node[1]] == 'stair'), -1)
                    if stair_index != -1:
                        stair_distance = sum(self.graph[path[i]][path[i+1]]['weight'] for i in range(stair_index))
                        current_distance_to_stair = stair_distance if current_distance_to_stair == -1 else min(current_distance_to_stair, stair_distance)
                    
                    if distance < min_exit_distance:
                        min_exit_distance = distance
                        best_exit = exit
                        best_path = path
                except nx.NetworkXNoPath:
                    continue

            if min_exit_distance > max_distance:
                max_distance = min_exit_distance
                furthest_point = point
                optimal_exit = best_exit
                optimal_path = best_path
                distance_to_stair = current_distance_to_stair

        if furthest_point and optimal_exit:
            return {
                'furthest_point': furthest_point,
                'optimal_exit': optimal_exit,
                'optimal_path': optimal_path,
                'distance': max_distance * self.grid_size,  # Convert to real-world distance
                'distance_to_stair': distance_to_stair * self.grid_size if distance_to_stair <= -1 else -1,  # Convert to real-world distance or keep as -1
                'space_name': space['name']
            }
        else:
            return {
                'furthest_point': None,
                'optimal_exit': None,
                'optimal_path': None,
                'distance': None,
                'distance_to_stair': None,
                'space_name': space['name']
            }
    
    def _select_candidate_points(self, space: Dict[str, Any]) -> List[Tuple[int, int, int]]:
        points = np.array(space['points'])
        
        # Calculate the centroid
        centroid = np.mean(points, axis=0)
        
        # Find points furthest from the centroid in each quadrant
        quadrants = [
            points[np.logical_and(points[:, 0] >= centroid[0], points[:, 1] >= centroid[1])],
            points[np.logical_and(points[:, 0] < centroid[0], points[:, 1] >= centroid[1])],
            points[np.logical_and(points[:, 0] < centroid[0], points[:, 1] < centroid[1])],
            points[np.logical_and(points[:, 0] >= centroid[0], points[:, 1] < centroid[1])]
        ]
        
        candidates = []
        for quadrant in quadrants:
            if len(quadrant) > 0:
                furthest = max(quadrant, key=lambda p: np.sum((p - centroid)**2))
                candidates.append((int(furthest[0]), int(furthest[1]), space['floor']))
        
        return candidates

    def _heuristic(self, a, b):
        (x1, y1, z1) = a
        (x2, y2, z2) = b
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 + abs(z1 - z2) * 3


def find_path(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float], 
              start: Dict[str, int], goals: List[Dict[str, int]], allow_diagonal: bool = False, minimize_cost: bool = True) -> Tuple[List[Tuple[int, int, int]], Dict[str, float]]:
    try:
        pathfinder = Pathfinder(grids, grid_size, floors, bbox, allow_diagonal, minimize_cost)
        return pathfinder.find_path(start, goals)
    except Exception as e:
        print(f"Error in find_path: {str(e)}")
        raise

def detect_exits(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float]) -> List[Tuple[int, int, int]]:
    try:
        pathfinder = Pathfinder(grids, grid_size, floors, bbox)
        return pathfinder.detect_exits()
    except Exception as e:
        print(f"Error in detect_exits: {str(e)}")
        raise

def calculate_escape_route(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], 
                           bbox: Dict[str, float], space: Dict[str, Any], exits: List[Tuple[int, int, int]], 
                           allow_diagonal: bool = False) -> Dict[str, Any]:
    pathfinder = Pathfinder(grids, grid_size, floors, bbox, allow_diagonal)
    return pathfinder.calculate_escape_route(space, exits)