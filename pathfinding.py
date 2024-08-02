import math
import networkx as nx
import numpy as np
from typing import List, Tuple, Dict, Any
from collections import defaultdict

import logging
import traceback

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class Pathfinder:
    def __init__(self, original_grids: List[List[List[str]]], buffered_grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float], allow_diagonal: bool = True, minimize_cost: bool = True):
        self.original_grids = original_grids
        self.buffered_grids = buffered_grids
        self.grids = buffered_grids
        self.grid_size = grid_size
        self.floors = floors
        self.bbox = bbox
        self.allow_diagonal = allow_diagonal
        self.minimize_cost = minimize_cost
        self.graph = None

    def create_graph(self):
        self.graph = self._create_graph()
        return self.graph
    
    def _create_graph(self) -> nx.Graph:
        G = nx.Graph()
        
        for floor, grid in enumerate(self.buffered_grids):
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
                            if 0 <= n_x < len(grid) and 0 <= n_y < len(grid[0]):
                                if grid[n_x][n_y] not in ['wall', 'walla']:
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

    def _group_connected_stairs(self):
        stair_groups = []
        visited = set()

        for floor in range(len(self.grids)):
            for x in range(len(self.grids[floor])):
                for y in range(len(self.grids[floor][0])):
                    if self.grids[floor][x][y] == 'stair' and (x, y, floor) not in visited:
                        group = self._flood_fill_3d(x, y, floor)
                        stair_groups.append(group)
                        visited.update(group)

        return stair_groups

    def _flood_fill_3d(self, start_x, start_y, start_floor):
        queue = [(start_x, start_y, start_floor)]
        visited = set()

        while queue:
            x, y, floor = queue.pop(0)
            if (x, y, floor) in visited:
                continue

            visited.add((x, y, floor))

            # Check neighbors on the same floor
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                nx, ny = x + dx, y + dy
                if (0 <= nx < len(self.grids[floor]) and 
                    0 <= ny < len(self.grids[floor][0]) and 
                    self.grids[floor][nx][ny] == 'stair' and
                    (nx, ny, floor) not in visited):
                    queue.append((nx, ny, floor))

            # Check directly above and below
            for adj_floor in [floor - 1, floor + 1]:
                if (0 <= adj_floor < len(self.grids) and 
                    self.grids[adj_floor][x][y] == 'stair' and
                    (x, y, adj_floor) not in visited):
                    queue.append((x, y, adj_floor))

        return visited

    def _connect_stairs(self, G: nx.Graph):
        stair_angle = math.radians(55)  # 55 degree angle for stairs
        num_directions = 16  # Number of directions to check
        stair_groups = self._group_connected_stairs()

        #print(f"Found {len(stair_groups)} stair groups")

        for group_index, group in enumerate(stair_groups):
            #print(f"Processing stair group {group_index + 1}")
            floors = sorted(set(floor for _, _, floor in group))
            #print(f"Group contains stairs on floors: {floors}")
            
            for i in range(len(floors) - 1):
                lower_floor, upper_floor = floors[i], floors[i + 1]
                lower_stairs = [pos for pos in group if pos[2] == lower_floor]
                upper_stairs = [pos for pos in group if pos[2] == upper_floor]

                #print(f"Connecting floors {lower_floor} and {upper_floor}")
                #print(f"Lower stairs: {lower_stairs}")
                #print(f"Upper stairs: {upper_stairs}")

                height_diff = self.floors[upper_floor]['elevation'] - self.floors[lower_floor]['elevation']
                horizontal_distance = height_diff / math.tan(stair_angle)
                grid_distance = int(round(horizontal_distance / self.grid_size))

                #print(f"Height difference: {height_diff}")
                print(f"Calculated horizontal distance: {horizontal_distance}")
                #print(f"Grid distance: {grid_distance}")

                connections_made = 0
                for start_x, start_y, _ in lower_stairs:
                    for end_x, end_y, _ in upper_stairs:
                        if self._check_stair_connection(start_x, start_y, lower_floor, end_x, end_y, upper_floor, grid_distance, num_directions):
                            start_node = (start_x, start_y, lower_floor)
                            end_node = (end_x, end_y, upper_floor)
                            if start_node in G and end_node in G:
                                weight = self._calculate_stair_weight(start_node, end_node, height_diff)
                                G.add_edge(start_node, end_node, weight=weight)
                                connections_made += 1
                                #print(f"Connected {start_node} to {end_node} with weight {weight}")
                        #else:
                        #    print(f"Failed to connect {(start_x, start_y, lower_floor)} to {(end_x, end_y, upper_floor)}")
                
                if connections_made == 0:
                    print(f"No connections made between floors {lower_floor} and {upper_floor}, using fallback method")
                    self._connect_stairs_fallback(G, lower_stairs, upper_stairs)
                else:
                    print(f"Made {connections_made} connections between floors {lower_floor} and {upper_floor}")

    def _check_stair_connection(self, start_x, start_y, start_floor, end_x, end_y, end_floor, grid_distance, num_directions):
        angle_step = 2 * math.pi / num_directions
        for i in range(num_directions):
            angle = i * angle_step
            dx = int(round(grid_distance * math.cos(angle)))
            dy = int(round(grid_distance * math.sin(angle)))
            
            if start_x + dx == end_x and start_y + dy == end_y:
                return self._check_path(start_x, start_y, start_floor, end_x, end_y, end_floor)
        
        return False

    def _check_path(self, start_x, start_y, start_floor, end_x, end_y, end_floor):
        dx = end_x - start_x
        dy = end_y - start_y
        steps = max(abs(dx), abs(dy))
        
        if steps == 0:
            return True

        x_step = dx / steps
        y_step = dy / steps

        for i in range(1, steps):
            x = int(start_x + i * x_step)
            y = int(start_y + i * y_step)

            if self.buffered_grids[start_floor][x][y] not in ['stair'] and self.buffered_grids[end_floor][x][y] not in ['stair']:
                return False

        return True

    def _calculate_stair_weight(self, start_node, end_node, height_diff):
        horizontal_distance = math.sqrt((end_node[0] - start_node[0])**2 + (end_node[1] - start_node[1])**2) * self.grid_size
        actual_distance = math.sqrt(height_diff**2 + horizontal_distance**2)
        return self._get_edge_weight('stair') * actual_distance / self.grid_size

    def _connect_stairs_fallback(self, G, lower_stairs, upper_stairs):
        for lower_x, lower_y, lower_floor in lower_stairs:
            for upper_x, upper_y, upper_floor in upper_stairs:
                node1 = (lower_x, lower_y, lower_floor)
                node2 = (upper_x, upper_y, upper_floor)
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
        try:
            #logger.debug(f"Calculating escape route for space: {space['name']}")
            candidate_points = self._select_candidate_points(space)
            #logger.debug(f"Candidate points: {candidate_points}")
            
            max_distance = 0
            furthest_point = None
            optimal_exit = None
            optimal_path = None
            distance_to_stair = -1

            for point in candidate_points:
                if point not in self.graph:
                    #logger.warning(f"Point {point} not in graph for space {space['name']}")
                    continue

                min_exit_distance = float('inf')
                best_exit = None
                best_path = None
                current_distance_to_stair = -1

                for exit in exits:
                    exit = (exit[0], exit[1], exit[2])
                    if exit not in self.graph:
                        #logger.warning(f"Exit {exit} not in graph")
                        continue

                    try:
                        path = nx.astar_path(self.graph, point, exit, heuristic=self._heuristic, weight='weight')
                        distance = sum(self.graph[path[i]][path[i+1]]['weight'] for i in range(len(path)-1))
                        
                        stair_index = next((i for i, node in enumerate(path) if self.grids[node[2]][node[0]][node[1]] == 'stair'), -1)
                        if stair_index != -1:
                            stair_distance = sum(self.graph[path[i]][path[i+1]]['weight'] for i in range(stair_index))
                            current_distance_to_stair = stair_distance if current_distance_to_stair == -1 else min(current_distance_to_stair, stair_distance)
                        
                        if distance < min_exit_distance:
                            min_exit_distance = distance
                            best_exit = exit
                            best_path = path
                    except nx.NetworkXNoPath:
                        #logger.warning(f"No path found from {point} to exit {exit}")
                        continue

                if min_exit_distance > max_distance:
                    max_distance = min_exit_distance
                    furthest_point = point
                    optimal_exit = best_exit
                    optimal_path = best_path
                    distance_to_stair = current_distance_to_stair

            if furthest_point and optimal_exit:
                result = {
                    'furthest_point': furthest_point,
                    'optimal_exit': optimal_exit,
                    'optimal_path': optimal_path,
                    'distance': max_distance * self.grid_size,
                    'distance_to_stair': distance_to_stair * self.grid_size if distance_to_stair > 0 else -1,
                    'space_name': space['name']
                }
            else:
                result = {
                    'furthest_point': None,
                    'optimal_exit': None,
                    'optimal_path': None,
                    'distance': None,
                    'distance_to_stair': None,
                    'space_name': space['name']
                }

            #logger.debug(f"Escape route calculation result for space {space['name']}: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in calculate_escape_route for space {space['name']}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    
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
        pathfinder = Pathfinder(grids, grids, grid_size, floors, bbox, allow_diagonal, minimize_cost)
        return pathfinder.find_path(start, goals)
    except Exception as e:
        print(f"Error in find_path: {str(e)}")
        raise

def detect_exits(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float]) -> List[Tuple[int, int, int]]:
    try:
        pathfinder = Pathfinder(grids, grids, grid_size, floors, bbox)
        return pathfinder.detect_exits()
    except Exception as e:
        print(f"Error in detect_exits: {str(e)}")
        raise

def calculate_escape_route(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], 
                           bbox: Dict[str, float], space: Dict[str, Any], exits: List[Tuple[int, int, int]], 
                           allow_diagonal: bool = False) -> Dict[str, Any]:
    try:
        logger.debug(f"Calculating escape route for space: {space['name']}")
        logger.debug(f"Grid size: {grid_size}, Floors: {floors}, Bbox: {bbox}")
        logger.debug(f"Exits: {exits}, Allow diagonal: {allow_diagonal}")
        
        pathfinder = Pathfinder(grids, grids, grid_size, floors, bbox, allow_diagonal)
        pathfinder.create_graph()
        result = pathfinder.calculate_escape_route(space, exits)
        
        logger.debug(f"Escape route calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in calculate_escape_route: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    
def calculate_escape_routes(grids: List[List[List[str]]], grid_size: float, floors: List[Dict[str, float]], 
                                              bbox: Dict[str, float], spaces: List[Dict[str, Any]], exits: List[Tuple[int, int, int]], 
                                              allow_diagonal: bool = False) -> List[Dict[str, Any]]:
    try: 
        # Create a single Pathfinder instance
        pathfinder = Pathfinder(grids, grids, grid_size, floors, bbox, allow_diagonal)
        pathfinder.create_graph()  # Create the graph once
        
        results = []
        for space in spaces:
            result = pathfinder.calculate_escape_route(space, exits)
            violations = check_escape_route_rules(result, grid_size)
            result['violations'] = violations
            results.append(result)
        
        return results
    except Exception as e:
        logger.error(f"Error in update_spaces_and_calculate_escape_routes: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def check_escape_route_rules(route, grid_size):
    violations = {
        'daytime': [],
        'nighttime': []
    }

    max_travel_distances = {
        'daytime': {
            'toEvacRoute': 30,
            'toNearestExit': 45,
            'toSecondExit': 80
        },
        'nighttime': {
            'toEvacRoute': 20,
            'toNearestExit': 30,
            'toSecondExit': 60
        }
    }
    print("Distance to stair:")
    print(route['distance_to_stair'])
    print("Distance to exit:")
    print(route['distance'])
    for time_of_day in ['daytime', 'nighttime']:
        if route['distance_to_stair'] > max_travel_distances[time_of_day]['toEvacRoute']:
            violations[time_of_day].append(f"Distance to evacuation route ({route['distance_to_stair']:.2f}m) exceeds maximum ({max_travel_distances[time_of_day]['toEvacRoute']}m)")
        
        if route['distance'] > max_travel_distances[time_of_day]['toNearestExit']:
            violations[time_of_day].append(f"Distance to nearest exit ({route['distance']:.2f}m) exceeds maximum ({max_travel_distances[time_of_day]['toNearestExit']}m)")

    # Check dead-end length (if available)
    if 'dead_end_length' in route and route['dead_end_length'] > 15:
        violations['daytime'].append(f"Dead-end length ({route['dead_end_length']:.2f}m) exceeds maximum (15m)")
        violations['nighttime'].append(f"Dead-end length ({route['dead_end_length']:.2f}m) exceeds maximum (15m)")

    # Check stairway distance (if available)
    if 'stairway_distance' in route:
        if route['stairway_distance'] < 10:
            violations['daytime'].append(f"Stairway distance ({route['stairway_distance']:.2f}m) is less than minimum (10m)")
            violations['nighttime'].append(f"Stairway distance ({route['stairway_distance']:.2f}m) is less than minimum (10m)")
        elif route['stairway_distance'] > 60:
            violations['daytime'].append(f"Stairway distance ({route['stairway_distance']:.2f}m) exceeds maximum (60m)")
            violations['nighttime'].append(f"Stairway distance ({route['stairway_distance']:.2f}m) exceeds maximum (60m)")
    print(violations)
    return violations