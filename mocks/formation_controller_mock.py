"""
CanaSwarm Swarm-Coordinator - Formation Controller Mock
=======================================================

Manages robot formations using flocking algorithms and virtual structures.

Author: Agro-Tech Ecosystem
Date: 2026-02-20
"""

import json
import math
import random
from typing import Dict, List, Optional, Any, Tuple


class FormationController:
    """
    Controls robot formations using flocking behavior.
    
    Implements:
    - Reynolds' flocking rules (separation, alignment, cohesion)
    - Virtual structures (leader-follower, grid, line)
    - Collision avoidance using potential fields
    """
    
    def __init__(self, swarm_data: Dict[str, Any], config: Dict[str, Any]):
        """
        Initialize formation controller.
        
        Args:
            swarm_data: Complete swarm state with robot info
            config: Configuration for formations
        """
        self.swarm_data = swarm_data
        self.config = config
        
        # Extract robots
        self.robots = {r['robot_id']: r for r in swarm_data['robots']}
        
        # Formation parameters (tunable weights)
        self.separation_weight = 1.5  # Avoid crowding
        self.alignment_weight = 1.0   # Match neighbors' heading
        self.cohesion_weight = 1.2    # Stay with group
        self.collision_radius_m = 2.0 # Minimum separation distance
        self.perception_radius_m = 50.0  # Neighbor detection range
        
        # Statistics
        self.collision_count = 0
        self.formation_updates = 0
    
    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS coordinates in meters."""
        R = 6371000  # Earth radius in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_phi / 2) ** 2 + 
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    def _calculate_bearing(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate bearing from point 1 to point 2 (degrees).
        
        Returns:
            Bearing in degrees (0-360)
        """
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)
        
        y = math.sin(delta_lambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
        
        bearing_rad = math.atan2(y, x)
        bearing_deg = math.degrees(bearing_rad)
        
        # Normalize to 0-360
        return (bearing_deg + 360) % 360
    
    def _angle_difference(self, angle1: float, angle2: float) -> float:
        """
        Calculate shortest difference between two angles.
        
        Args:
            angle1, angle2: Angles in degrees
            
        Returns:
            Difference in degrees (-180 to 180)
        """
        diff = angle2 - angle1
        
        # Normalize to -180 to 180
        while diff > 180:
            diff -= 360
        while diff < -180:
            diff += 360
        
        return diff
    
    def get_neighbors(self, robot_id: str) -> List[Dict[str, Any]]:
        """
        Find neighbors within perception radius.
        
        Args:
            robot_id: Robot to find neighbors for
            
        Returns:
            List of neighbor robot dicts with distance and bearing
        """
        robot = self.robots[robot_id]
        robot_pos = robot['position']
        
        neighbors = []
        
        for other_id, other in self.robots.items():
            if other_id == robot_id:
                continue
            
            # Skip disconnected robots
            if not other['communication']['connected']:
                continue
            
            other_pos = other['position']
            distance = self._haversine_distance(
                robot_pos['lat'], robot_pos['lon'],
                other_pos['lat'], other_pos['lon']
            )
            
            if distance <= self.perception_radius_m:
                bearing = self._calculate_bearing(
                    robot_pos['lat'], robot_pos['lon'],
                    other_pos['lat'], other_pos['lon']
                )
                
                neighbors.append({
                    'robot_id': other_id,
                    'robot': other,
                    'distance_m': distance,
                    'bearing_deg': bearing
                })
        
        return neighbors
    
    def calculate_separation_force(self, robot_id: str, neighbors: List[Dict]) -> Tuple[float, float]:
        """
        Separation: Avoid crowding neighbors (Reynolds rule 1).
        
        Force pushes robot away from nearby neighbors.
        Stronger for closer neighbors.
        
        Args:
            robot_id: Robot to calculate force for
            neighbors: List of neighbors
            
        Returns:
            Tuple of (force_x, force_y) in arbitrary units
        """
        force_x = 0.0
        force_y = 0.0
        
        robot = self.robots[robot_id]
        robot_pos = robot['position']
        
        for neighbor in neighbors:
            distance = neighbor['distance_m']
            
            # Only apply separation if too close
            if distance < self.collision_radius_m * 3:  # 3x collision radius = comfort zone
                neighbor_pos = neighbor['robot']['position']
                
                # Vector from neighbor to robot (repulsive)
                delta_lat = robot_pos['lat'] - neighbor_pos['lat']
                delta_lon = robot_pos['lon'] - neighbor_pos['lon']
                
                # Force magnitude (inverse square law, clamped)
                if distance > 0.1:
                    magnitude = min(1.0 / (distance ** 2), 10.0)
                else:
                    magnitude = 10.0
                
                # Normalize direction
                norm = math.sqrt(delta_lat**2 + delta_lon**2)
                if norm > 0:
                    force_x += (delta_lat / norm) * magnitude
                    force_y += (delta_lon / norm) * magnitude
        
        return force_x * self.separation_weight, force_y * self.separation_weight
    
    def calculate_alignment_force(self, robot_id: str, neighbors: List[Dict]) -> float:
        """
        Alignment: Match average heading of neighbors (Reynolds rule 2).
        
        Returns:
            Target heading adjustment in degrees
        """
        if not neighbors:
            return 0.0
        
        robot = self.robots[robot_id]
        robot_heading = robot['position']['heading_deg']
        
        # Calculate average heading of neighbors (circular mean)
        sin_sum = 0.0
        cos_sum = 0.0
        
        for neighbor in neighbors:
            heading_rad = math.radians(neighbor['robot']['position']['heading_deg'])
            sin_sum += math.sin(heading_rad)
            cos_sum += math.cos(heading_rad)
        
        avg_heading_rad = math.atan2(sin_sum / len(neighbors), cos_sum / len(neighbors))
        avg_heading_deg = math.degrees(avg_heading_rad)
        
        # Calculate heading adjustment
        heading_diff = self._angle_difference(robot_heading, avg_heading_deg)
        
        return heading_diff * self.alignment_weight
    
    def calculate_cohesion_force(self, robot_id: str, neighbors: List[Dict]) -> Tuple[float, float]:
        """
        Cohesion: Move toward center of mass of neighbors (Reynolds rule 3).
        
        Args:
            robot_id: Robot to calculate force for
            neighbors: List of neighbors
            
        Returns:
            Tuple of (force_x, force_y) in arbitrary units
        """
        if not neighbors:
            return 0.0, 0.0
        
        robot = self.robots[robot_id]
        robot_pos = robot['position']
        
        # Calculate center of mass
        center_lat = sum(n['robot']['position']['lat'] for n in neighbors) / len(neighbors)
        center_lon = sum(n['robot']['position']['lon'] for n in neighbors) / len(neighbors)
        
        # Vector from robot to center
        delta_lat = center_lat - robot_pos['lat']
        delta_lon = center_lon - robot_pos['lon']
        
        # Distance to center
        distance = math.sqrt(delta_lat**2 + delta_lon**2)
        
        # Force magnitude (proportional to distance, clamped)
        magnitude = min(distance * 100, 5.0)  # Scale factor 100 for GPS coordinates
        
        # Normalize direction
        if distance > 0:
            force_x = (delta_lat / distance) * magnitude
            force_y = (delta_lon / distance) * magnitude
        else:
            force_x = 0.0
            force_y = 0.0
        
        return force_x * self.cohesion_weight, force_y * self.cohesion_weight
    
    def update_flocking(self, formation_id: str) -> Dict[str, Any]:
        """
        Update formation using flocking behavior.
        
        Applies Reynolds' three rules:
        1. Separation: Avoid crowding
        2. Alignment: Match heading
        3. Cohesion: Stay with group
        
        Args:
            formation_id: Formation to update
            
        Returns:
            Dict with formation update results
        """
        # Find robots in formation
        formation_robots = [
            (robot_id, robot) for robot_id, robot in self.robots.items()
            if (robot.get('formation', {}).get('formation_id') == formation_id and
                robot['communication']['connected'])
        ]
        
        if len(formation_robots) < 2:
            return {
                'success': False,
                'reason': 'insufficient_robots',
                'formation_id': formation_id,
                'robots_count': len(formation_robots)
            }
        
        print(f"\n🦆 ATUALIZANDO FORMAÇÃO {formation_id}")
        print(f"   Robôs na formação: {len(formation_robots)}")
        
        updates = []
        
        # Calculate flocking forces for each robot
        for robot_id, robot in formation_robots:
            neighbors = self.get_neighbors(robot_id)
            
            # Filter neighbors to only those in same formation
            formation_neighbors = [
                n for n in neighbors
                if n['robot'].get('formation', {}).get('formation_id') == formation_id
            ]
            
            if not formation_neighbors:
                continue
            
            # Apply Reynolds' rules
            sep_x, sep_y = self.calculate_separation_force(robot_id, formation_neighbors)
            alignment_deg = self.calculate_alignment_force(robot_id, formation_neighbors)
            coh_x, coh_y = self.calculate_cohesion_force(robot_id, formation_neighbors)
            
            # Combine forces
            total_force_x = sep_x + coh_x
            total_force_y = sep_y + coh_y
            
            # Convert force to heading adjustment
            if abs(total_force_x) > 0.01 or abs(total_force_y) > 0.01:
                force_heading_rad = math.atan2(total_force_y, total_force_x)
                force_heading_deg = math.degrees(force_heading_rad)
                
                # Current heading
                current_heading = robot['position']['heading_deg']
                
                # New heading (blend forces and alignment)
                position_adjustment = self._angle_difference(current_heading, force_heading_deg) * 0.5
                total_adjustment = position_adjustment + alignment_deg * 0.5
                
                new_heading = (current_heading + total_adjustment) % 360
            else:
                new_heading = robot['position']['heading_deg']
            
            # Calculate distance to target position (if in virtual structure)
            target_pos = robot['formation'].get('target_position')
            if target_pos:
                # For virtual structures, blend flocking with structure maintenance
                distance_to_target = math.sqrt(target_pos['relative_x_m']**2 + 
                                              target_pos['relative_y_m']**2)
            else:
                distance_to_target = 0.0
            
            # Update robot state (in simulation, would send command to robot)
            robot['position']['heading_deg'] = new_heading
            
            updates.append({
                'robot_id': robot_id,
                'neighbors_count': len(formation_neighbors),
                'separation_force': (round(sep_x, 3), round(sep_y, 3)),
                'alignment_adjustment_deg': round(alignment_deg, 2),
                'cohesion_force': (round(coh_x, 3), round(coh_y, 3)),
                'new_heading_deg': round(new_heading, 1),
                'distance_to_target_m': round(distance_to_target, 2)
            })
        
        # Calculate formation quality metrics
        metrics = self._calculate_formation_quality(formation_id, formation_robots)
        
        self.formation_updates += 1
        
        return {
            'success': True,
            'formation_id': formation_id,
            'robots_updated': len(updates),
            'updates': updates[:5],  # Show first 5
            'metrics': metrics
        }
    
    def _calculate_formation_quality(self, formation_id: str, 
                                     formation_robots: List[Tuple[str, Dict]]) -> Dict[str, Any]:
        """
        Calculate formation quality metrics.
        
        Args:
            formation_id: Formation ID
            formation_robots: List of (robot_id, robot) tuples
            
        Returns:
            Dict with quality metrics
        """
        if len(formation_robots) < 2:
            return {
                'cohesion': 0.0,
                'alignment': 0.0,
                'separation': 0.0,
                'overall': 0.0
            }
        
        # Cohesion: How close robots are to center of mass
        center_lat = sum(r[1]['position']['lat'] for r in formation_robots) / len(formation_robots)
        center_lon = sum(r[1]['position']['lon'] for r in formation_robots) / len(formation_robots)
        
        distances_to_center = []
        for robot_id, robot in formation_robots:
            distance = self._haversine_distance(
                robot['position']['lat'], robot['position']['lon'],
                center_lat, center_lon
            )
            distances_to_center.append(distance)
        
        avg_distance = sum(distances_to_center) / len(distances_to_center)
        cohesion_score = max(0, 1 - avg_distance / self.perception_radius_m)
        
        # Alignment: How similar headings are
        headings = [r[1]['position']['heading_deg'] for r in formation_robots]
        heading_variance = sum((h - sum(headings)/len(headings))**2 for h in headings) / len(headings)
        alignment_score = max(0, 1 - heading_variance / 180**2)  # Normalize to 0-1
        
        # Separation: How well robots maintain safe distance
        collision_count = 0
        total_pairs = 0
        
        for i, (id1, r1) in enumerate(formation_robots):
            for id2, r2 in formation_robots[i+1:]:
                distance = self._haversine_distance(
                    r1['position']['lat'], r1['position']['lon'],
                    r2['position']['lat'], r2['position']['lon']
                )
                
                total_pairs += 1
                if distance < self.collision_radius_m:
                    collision_count += 1
        
        separation_score = 1 - (collision_count / total_pairs) if total_pairs > 0 else 1.0
        
        # Overall score (weighted average)
        overall_score = (cohesion_score * 0.35 + 
                        alignment_score * 0.30 + 
                        separation_score * 0.35)
        
        return {
            'cohesion': round(cohesion_score, 3),
            'alignment': round(alignment_score, 3),
            'separation': round(separation_score, 3),
            'overall': round(overall_score, 3),
            'avg_distance_to_center_m': round(avg_distance, 2),
            'collision_count': collision_count
        }
    
    def create_formation(self, robot_ids: List[str], formation_type: str, 
                        leader_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new formation with specified robots.
        
        Args:
            robot_ids: List of robots to include
            formation_type: 'flocking', 'line', 'grid', or 'leader_follower'
            leader_id: Leader robot (for leader_follower type)
            
        Returns:
            Formation creation result
        """
        formation_id = f"FORMATION-{formation_type.upper()}-{random.randint(1000, 9999)}"
        
        # Validate robots
        valid_robots = [rid for rid in robot_ids if rid in self.robots]
        
        if len(valid_robots) < 2:
            return {
                'success': False,
                'reason': 'insufficient_robots',
                'minimum_required': 2
            }
        
        # Assign formation
        if formation_type == 'leader_follower':
            if not leader_id or leader_id not in valid_robots:
                leader_id = valid_robots[0]  # Default to first robot
            
            # Leader at origin (0, 0)
            for i, robot_id in enumerate(valid_robots):
                robot = self.robots[robot_id]
                
                if robot_id == leader_id:
                    # Leader
                    robot['formation'] = {
                        'position_in_formation': 0,
                        'formation_id': formation_id,
                        'target_position': {
                            'relative_x_m': 0.0,
                            'relative_y_m': 0.0
                        },
                        'distance_to_target_m': 0.0,
                        'alignment_error_deg': 0.0
                    }
                else:
                    # Followers in line behind leader
                    follower_pos = valid_robots.index(robot_id)
                    robot['formation'] = {
                        'position_in_formation': follower_pos,
                        'formation_id': formation_id,
                        'target_position': {
                            'relative_x_m': follower_pos * 5.0,  # 5m spacing
                            'relative_y_m': 0.0
                        },
                        'distance_to_target_m': 0.0,
                        'alignment_error_deg': 0.0
                    }
        
        elif formation_type == 'line':
            # Robots in a line
            for i, robot_id in enumerate(valid_robots):
                robot = self.robots[robot_id]
                robot['formation'] = {
                    'position_in_formation': i,
                    'formation_id': formation_id,
                    'target_position': {
                        'relative_x_m': i * 5.0,  # 5m spacing
                        'relative_y_m': 0.0
                    },
                    'distance_to_target_m': 0.0,
                    'alignment_error_deg': 0.0
                }
        
        elif formation_type == 'grid':
            # Robots in a grid (e.g., 2x2, 3x2, etc.)
            cols = math.ceil(math.sqrt(len(valid_robots)))
            for i, robot_id in enumerate(valid_robots):
                row = i // cols
                col = i % cols
                
                robot = self.robots[robot_id]
                robot['formation'] = {
                    'position_in_formation': i,
                    'formation_id': formation_id,
                    'target_position': {
                        'relative_x_m': col * 5.0,  # 5m spacing
                        'relative_y_m': row * 5.0
                    },
                    'distance_to_target_m': 0.0,
                    'alignment_error_deg': 0.0
                }
        
        else:  # flocking (no specific structure)
            for i, robot_id in enumerate(valid_robots):
                robot = self.robots[robot_id]
                robot['formation'] = {
                    'position_in_formation': i,
                    'formation_id': formation_id,
                    'target_position': None,  # No fixed structure
                    'distance_to_target_m': None,
                    'alignment_error_deg': None
                }
        
        return {
            'success': True,
            'formation_id': formation_id,
            'formation_type': formation_type,
            'robots_count': len(valid_robots),
            'robots': valid_robots,
            'leader': leader_id if formation_type == 'leader_follower' else None
        }
    
    def get_formation_statistics(self) -> Dict[str, Any]:
        """
        Get formation statistics.
        
        Returns:
            Dict with formation metrics
        """
        # Count formations
        formations = {}
        for robot in self.robots.values():
            formation_id = robot.get('formation', {}).get('formation_id')
            if formation_id:
                if formation_id not in formations:
                    formations[formation_id] = []
                formations[formation_id].append(robot['robot_id'])
        
        # Calculate quality for each formation
        formation_quality = {}
        for formation_id, robot_ids in formations.items():
            formation_robots = [(rid, self.robots[rid]) for rid in robot_ids]
            quality = self._calculate_formation_quality(formation_id, formation_robots)
            formation_quality[formation_id] = quality
        
        # Average quality across all formations
        if formation_quality:
            avg_cohesion = sum(q['cohesion'] for q in formation_quality.values()) / len(formation_quality)
            avg_alignment = sum(q['alignment'] for q in formation_quality.values()) / len(formation_quality)
            avg_separation = sum(q['separation'] for q in formation_quality.values()) / len(formation_quality)
            avg_overall = sum(q['overall'] for q in formation_quality.values()) / len(formation_quality)
        else:
            avg_cohesion = avg_alignment = avg_separation = avg_overall = 0.0
        
        return {
            'total_formations': len(formations),
            'total_robots_in_formation': sum(len(robots) for robots in formations.values()),
            'formations': {fid: len(robots) for fid, robots in formations.items()},
            'formation_quality': formation_quality,
            'average_quality': {
                'cohesion': round(avg_cohesion, 3),
                'alignment': round(avg_alignment, 3),
                'separation': round(avg_separation, 3),
                'overall': round(avg_overall, 3)
            },
            'formation_updates': self.formation_updates,
            'collision_count': self.collision_count
        }


def test_formation_controller():
    """Test the formation controller with example data."""
    print("=" * 80)
    print("TESTANDO FORMATION CONTROLLER (FLOCKING & VIRTUAL STRUCTURES)")
    print("=" * 80)
    
    # Load example swarm data
    with open('example_swarm_data.json', 'r', encoding='utf-8') as f:
        swarm_data = json.load(f)
    
    config = swarm_data['swarm_config']
    
    # Create formation controller
    controller = FormationController(swarm_data, config)
    
    print("\n📊 ESTADO INICIAL")
    stats = controller.get_formation_statistics()
    print(f"   Total de formações: {stats['total_formations']}")
    print(f"   Robôs em formação: {stats['total_robots_in_formation']}")
    print(f"   Formações existentes:")
    for fid, count in stats['formations'].items():
        print(f"      - {fid}: {count} robôs")
    
    # Test 1: Update existing formation (flocking)
    print("\n" + "=" * 80)
    print("TESTE 1: Atualizar formação existente (flocking behavior)")
    print("=" * 80)
    
    existing_formation = list(stats['formations'].keys())[0] if stats['formations'] else None
    
    if existing_formation:
        flocking_result = controller.update_flocking(existing_formation)
        
        if flocking_result['success']:
            print(f"\n✅ Formação atualizada: {flocking_result['formation_id']}")
            print(f"   Robôs atualizados: {flocking_result['robots_updated']}")
            
            print(f"\n   📋 ATUALIZAÇÕES (primeiros 5 robôs):")
            for update in flocking_result['updates']:
                print(f"\n      🤖 {update['robot_id']}")
                print(f"         Vizinhos: {update['neighbors_count']}")
                print(f"         Força de separação: {update['separation_force']}")
                print(f"         Ajuste de alinhamento: {update['alignment_adjustment_deg']:.2f}°")
                print(f"         Força de coesão: {update['cohesion_force']}")
                print(f"         Novo heading: {update['new_heading_deg']:.1f}°")
                if update['distance_to_target_m'] > 0:
                    print(f"         Distância ao alvo: {update['distance_to_target_m']:.2f}m")
            
            metrics = flocking_result['metrics']
            print(f"\n   📊 MÉTRICAS DE QUALIDADE:")
            print(f"      Coesão: {metrics['cohesion']:.1%} (proximidade ao centro)")
            print(f"      Alinhamento: {metrics['alignment']:.1%} (headings similares)")
            print(f"      Separação: {metrics['separation']:.1%} (sem colisões)")
            print(f"      ➜ Qualidade geral: {metrics['overall']:.1%}")
            print(f"      Distância média ao centro: {metrics['avg_distance_to_center_m']:.2f}m")
            print(f"      Colisões: {metrics['collision_count']}")
    
    # Test 2: Create new formation (leader-follower)
    print("\n" + "=" * 80)
    print("TESTE 2: Criar nova formação (leader-follower)")
    print("=" * 80)
    
    # Find available robots (not in formation or in formation with less than 4 robots)
    available_robots = []
    for robot_id, robot in controller.robots.items():
        formation_id = robot.get('formation', {}).get('formation_id')
        if not formation_id or (formation_id and stats['formations'].get(formation_id, 0) < 4):
            if robot['communication']['connected']:
                available_robots.append(robot_id)
    
    if len(available_robots) >= 3:
        test_robots = available_robots[:3]
        leader = test_robots[0]
        
        creation_result = controller.create_formation(
            robot_ids=test_robots,
            formation_type='leader_follower',
            leader_id=leader
        )
        
        if creation_result['success']:
            print(f"\n✅ Formação criada: {creation_result['formation_id']}")
            print(f"   Tipo: {creation_result['formation_type']}")
            print(f"   Líder: {creation_result['leader']}")
            print(f"   Robôs: {creation_result['robots_count']}")
            print(f"   Membros: {', '.join(creation_result['robots'])}")
            
            # Update the formation
            print(f"\n   Atualizando formação...")
            update_result = controller.update_flocking(creation_result['formation_id'])
            
            if update_result['success']:
                print(f"   ✅ Atualizada com sucesso")
                print(f"   Qualidade: {update_result['metrics']['overall']:.1%}")
    else:
        print(f"\n   ⚠️  Robôs disponíveis insuficientes (precisa 3, tem {len(available_robots)})")
    
    # Test 3: Create grid formation
    print("\n" + "=" * 80)
    print("TESTE 3: Criar formação em grid")
    print("=" * 80)
    
    # Find harvesters for grid formation
    harvesters = [rid for rid, r in controller.robots.items() 
                  if r['type'] == 'harvester' and r['communication']['connected']]
    
    if len(harvesters) >= 4:
        grid_robots = harvesters[:4]
        
        grid_result = controller.create_formation(
            robot_ids=grid_robots,
            formation_type='grid'
        )
        
        if grid_result['success']:
            print(f"\n✅ Grid criado: {grid_result['formation_id']}")
            print(f"   Robôs: {grid_result['robots_count']}")
            print(f"   Configuração: 2x2")
            print(f"   Membros: {', '.join(grid_result['robots'])}")
            
            # Show positions
            print(f"\n   📐 Posições relativas:")
            for robot_id in grid_result['robots']:
                robot = controller.robots[robot_id]
                target = robot['formation']['target_position']
                pos = robot['formation']['position_in_formation']
                print(f"      Posição {pos}: {robot_id} → ({target['relative_x_m']:.1f}, {target['relative_y_m']:.1f})m")
    
    # Final statistics
    print("\n" + "=" * 80)
    print("ESTATÍSTICAS FINAIS")
    print("=" * 80)
    
    final_stats = controller.get_formation_statistics()
    print(f"\n📊 Métricas:")
    print(f"   Total de formações: {final_stats['total_formations']}")
    print(f"   Robôs em formação: {final_stats['total_robots_in_formation']}")
    print(f"   Atualizações de formação: {final_stats['formation_updates']}")
    print(f"   Colisões totais: {final_stats['collision_count']}")
    
    print(f"\n   Qualidade média das formações:")
    avg_q = final_stats['average_quality']
    print(f"      Coesão: {avg_q['cohesion']:.1%}")
    print(f"      Alinhamento: {avg_q['alignment']:.1%}")
    print(f"      Separação: {avg_q['separation']:.1%}")
    print(f"      ➜ GERAL: {avg_q['overall']:.1%}")
    
    print(f"\n   Formações ativas:")
    for fid, quality in final_stats['formation_quality'].items():
        robot_count = final_stats['formations'][fid]
        status = '🟢' if quality['overall'] >= 0.8 else ('🟡' if quality['overall'] >= 0.6 else '🔴')
        print(f"      {status} {fid}: {robot_count} robôs, qualidade {quality['overall']:.1%}")
    
    print("\n✅ Formation controller funcionando!")


if __name__ == "__main__":
    test_formation_controller()
