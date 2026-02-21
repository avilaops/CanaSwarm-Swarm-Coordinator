"""
CanaSwarm Swarm-Coordinator - Task Distributor Mock
===================================================

Manages task allocation using auction-based mechanisms and Hungarian algorithm.

Author: Agro-Tech Ecosystem
Date: 2026-02-20
"""

import json
import math
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple


class TaskDistributor:
    """
    Allocates tasks to robots using market-based mechanisms.
    
    Methods:
    - Auction-based: Robots bid on tasks, highest utility wins
    - Hungarian algorithm: Optimal assignment minimizing total cost
    - Priority-based: High priority tasks allocated first
    """
    
    def __init__(self, swarm_data: Dict[str, Any], config: Dict[str, Any]):
        """
        Initialize task distributor.
        
        Args:
            swarm_data: Complete swarm state with robots and tasks
            config: Configuration for task allocation
        """
        self.swarm_data = swarm_data
        self.config = config
        
        # Extract robots and tasks
        self.robots = {r['robot_id']: r for r in swarm_data['robots']}
        self.task_pool = swarm_data['task_pool']
        
        # Statistics
        self.tasks_allocated = 0
        self.auction_rounds = []
        
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
    
    def _calculate_bid(self, robot: Dict[str, Any], task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Calculate robot's bid for a task.
        
        Bid considers:
        - Distance to task (shorter = better)
        - Battery level (higher = better)
        - Current workload (lower = better)
        - Task priority (higher = incentivized)
        
        Args:
            robot: Robot state
            task: Task details
            
        Returns:
            Bid dict with value and details, or None if robot cannot bid
        """
        # Check if robot can perform task
        requirements = task['requirements']
        
        # Type check
        if robot['type'] != requirements['robot_type']:
            return None
        
        # Battery check
        if robot['status']['battery_soc_percent'] < requirements['min_battery_percent']:
            return None
        
        # Operational check
        if robot['status']['operational'] not in ['working', 'idle']:
            return None
        
        # Connected check
        if not robot['communication']['connected']:
            return None
        
        # Calculate distance to task
        robot_pos = robot['position']
        
        if 'location' in task:
            task_location = task['location']
            
            if 'centroid' in task_location:
                task_pos = task_location['centroid']
                distance_km = self._haversine_distance(
                    robot_pos['lat'], robot_pos['lon'],
                    task_pos['lat'], task_pos['lon']
                ) / 1000
            elif 'origin' in task_location:
                # For transport tasks, use origin
                task_pos = task_location['origin']
                distance_km = self._haversine_distance(
                    robot_pos['lat'], robot_pos['lon'],
                    task_pos['lat'], task_pos['lon']
                ) / 1000
            else:
                # Direct coordinates
                distance_km = self._haversine_distance(
                    robot_pos['lat'], robot_pos['lon'],
                    task_location['lat'], task_location['lon']
                ) / 1000
        elif 'route' in task:
            # Transport task with route
            origin = task['route']['origin']
            distance_km = self._haversine_distance(
                robot_pos['lat'], robot_pos['lon'],
                origin['lat'], origin['lon']
            ) / 1000
        else:
            distance_km = 0.1  # Default minimal distance
        
        # Calculate estimated time (hours)
        # Time = travel time + task duration
        travel_speed_kmh = 3.0 if robot['type'] == 'harvester' else 5.0
        travel_time_h = distance_km / travel_speed_kmh
        task_duration_h = requirements['estimated_duration_minutes'] / 60
        total_time_h = travel_time_h + task_duration_h
        
        # Calculate estimated energy cost (kWh)
        # Energy = travel energy + task energy
        energy_per_km = 0.3 if robot['type'] == 'harvester' else 0.2  # kWh/km
        travel_energy_kwh = distance_km * energy_per_km
        
        if robot['type'] == 'harvester':
            # Harvesting is energy-intensive
            task_energy_kwh = task_duration_h * 1.2  # kW average
        elif robot['type'] == 'transport':
            # Transport energy depends on cargo
            cargo_mass_kg = task.get('cargo', {}).get('mass_kg', 200)
            base_power_kw = 0.6
            cargo_factor = 1 + (cargo_mass_kg / 500)  # 500kg nominal
            task_energy_kwh = task_duration_h * base_power_kw * cargo_factor
        else:
            # Inspection/maintenance
            task_energy_kwh = task_duration_h * 0.4
        
        total_energy_kwh = travel_energy_kwh + task_energy_kwh
        
        # Check if robot has enough energy
        battery_capacity_kwh = robot['status']['battery_soc_percent'] / 100 * 10  # Assume 10 kWh battery
        if total_energy_kwh > battery_capacity_kwh * 0.8:  # Leave 20% margin
            return None
        
        # Calculate bid value (0-1, higher is better)
        # Factors:
        # - Distance (40%): closer is better
        # - Battery (30%): more battery is better
        # - Workload (20%): less busy is better
        # - Priority match (10%): higher priority tasks incentivized
        
        # Distance score (inverse, normalized to 5km max)
        distance_score = max(0, 1 - distance_km / 5)
        
        # Battery score
        battery_score = robot['status']['battery_soc_percent'] / 100
        
        # Workload score (inverse of current task progress)
        current_task = robot['task_assignment']
        if current_task:
            workload_score = 1 - (current_task['progress_percent'] / 100)
        else:
            workload_score = 1.0  # Idle robot
        
        # Priority score
        priority_map = {'low': 0.5, 'medium': 0.75, 'high': 1.0}
        priority_score = priority_map.get(task['priority'], 0.5)
        
        # Weighted bid value
        bid_value = (distance_score * 0.4 +
                    battery_score * 0.3 +
                    workload_score * 0.2 +
                    priority_score * 0.1)
        
        return {
            'robot_id': robot['robot_id'],
            'bid_value': round(bid_value, 3),
            'estimated_cost_kwh': round(total_energy_kwh, 2),
            'estimated_time_minutes': round(total_time_h * 60, 1),
            'distance_km': round(distance_km, 2),
            'components': {
                'distance_score': round(distance_score, 3),
                'battery_score': round(battery_score, 3),
                'workload_score': round(workload_score, 3),
                'priority_score': round(priority_score, 3)
            }
        }
    
    def run_auction(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run auction for a single task.
        
        Process:
        1. All eligible robots submit bids
        2. Highest bid wins (utility-based)
        3. Task allocated to winner
        
        Args:
            task: Task to allocate
            
        Returns:
            Auction result with winner and bids
        """
        task_id = task['task_id']
        
        # Collect bids from all robots
        bids = []
        for robot_id, robot in self.robots.items():
            bid = self._calculate_bid(robot, task)
            if bid:
                bids.append(bid)
        
        if not bids:
            return {
                'success': False,
                'task_id': task_id,
                'reason': 'no_bids',
                'bids_received': 0
            }
        
        # Sort bids by value (highest first)
        bids.sort(key=lambda b: b['bid_value'], reverse=True)
        
        # Winner is highest bidder
        winner = bids[0]
        
        # Allocate task
        winning_robot = self.robots[winner['robot_id']]
        winning_robot['task_assignment'] = {
            'task_id': task_id,
            'task_type': task['task_type'],
            'priority': task['priority'],
            'progress_percent': 0,
            'estimated_completion_minutes': winner['estimated_time_minutes']
        }
        
        # Update task status
        task['status'] = 'allocated'
        task['allocated_to'] = winner['robot_id']
        task['bids'] = bids[:5]  # Keep top 5 bids
        
        self.tasks_allocated += 1
        
        return {
            'success': True,
            'task_id': task_id,
            'winner': winner,
            'bids_received': len(bids),
            'all_bids': bids[:10],  # Top 10 for analysis
            'allocation_method': 'auction'
        }
    
    def hungarian_assignment(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Optimal task assignment using Hungarian algorithm.
        
        Finds minimum cost assignment of tasks to robots.
        
        Args:
            tasks: List of tasks to assign
            
        Returns:
            Assignment result with allocations
        """
        # Filter eligible robots for each task
        eligible_robots = {}
        for task in tasks:
            eligible = []
            for robot_id, robot in self.robots.items():
                if self._calculate_bid(robot, task) is not None:
                    eligible.append(robot_id)
            eligible_robots[task['task_id']] = eligible
        
        # Build cost matrix
        # Rows = tasks, Columns = robots
        all_robots = list(self.robots.keys())
        cost_matrix = []
        
        for task in tasks:
            row = []
            for robot_id in all_robots:
                bid = self._calculate_bid(self.robots[robot_id], task)
                if bid:
                    # Cost = 1 - bid_value (lower cost is better for Hungarian)
                    cost = 1 - bid['bid_value']
                else:
                    # Infinite cost (not eligible)
                    cost = 999
                row.append(cost)
            cost_matrix.append(row)
        
        # Simplified Hungarian algorithm (for demo, not full implementation)
        # In production, use scipy.optimize.linear_sum_assignment
        assignments = self._simplified_hungarian(cost_matrix, all_robots, tasks)
        
        # Apply assignments
        for task_id, robot_id in assignments.items():
            if robot_id:
                task = next(t for t in tasks if t['task_id'] == task_id)
                robot = self.robots[robot_id]
                bid = self._calculate_bid(robot, task)
                
                robot['task_assignment'] = {
                    'task_id': task_id,
                    'task_type': task['task_type'],
                    'priority': task['priority'],
                    'progress_percent': 0,
                    'estimated_completion_minutes': bid['estimated_time_minutes']
                }
                
                task['status'] = 'allocated'
                task['allocated_to'] = robot_id
                
                self.tasks_allocated += 1
        
        total_cost = sum(
            cost_matrix[tasks.index(next(t for t in tasks if t['task_id'] == tid))][all_robots.index(rid)]
            for tid, rid in assignments.items() if rid
        )
        
        return {
            'success': True,
            'assignments': assignments,
            'total_cost': round(total_cost, 3),
            'tasks_assigned': len([r for r in assignments.values() if r]),
            'allocation_method': 'hungarian'
        }
    
    def _simplified_hungarian(self, cost_matrix: List[List[float]], 
                             robots: List[str], tasks: List[Dict]) -> Dict[str, Optional[str]]:
        """
        Simplified Hungarian algorithm (greedy approximation).
        
        For production, use scipy.optimize.linear_sum_assignment.
        
        Args:
            cost_matrix: Cost matrix (tasks x robots)
            robots: List of robot IDs
            tasks: List of tasks
            
        Returns:
            Dict mapping task_id to robot_id
        """
        assignments = {}
        assigned_robots = set()
        
        # Create list of (task_idx, robot_idx, cost) sorted by cost
        candidates = []
        for task_idx, row in enumerate(cost_matrix):
            for robot_idx, cost in enumerate(row):
                if cost < 999:  # Eligible
                    candidates.append((task_idx, robot_idx, cost))
        
        # Sort by cost (lowest first)
        candidates.sort(key=lambda x: x[2])
        
        # Greedy assignment
        for task_idx, robot_idx, cost in candidates:
            task_id = tasks[task_idx]['task_id']
            robot_id = robots[robot_idx]
            
            if task_id not in assignments and robot_id not in assigned_robots:
                assignments[task_id] = robot_id
                assigned_robots.add(robot_id)
        
        # Fill unassigned tasks
        for task in tasks:
            if task['task_id'] not in assignments:
                assignments[task['task_id']] = None
        
        return assignments
    
    def allocate_tasks(self, method: str = 'auction') -> Dict[str, Any]:
        """
        Allocate all open tasks using specified method.
        
        Args:
            method: 'auction' or 'hungarian'
            
        Returns:
            Allocation results
        """
        # Filter open tasks
        open_tasks = [t for t in self.task_pool if t['status'] == 'open']
        
        if not open_tasks:
            return {
                'success': True,
                'tasks_allocated': 0,
                'reason': 'no_open_tasks'
            }
        
        results = []
        
        if method == 'auction':
            # Run auction for each task
            for task in open_tasks:
                result = self.run_auction(task)
                results.append(result)
        
        elif method == 'hungarian':
            # Batch assignment
            result = self.hungarian_assignment(open_tasks)
            results.append(result)
        
        else:
            return {
                'success': False,
                'reason': 'invalid_method',
                'valid_methods': ['auction', 'hungarian']
            }
        
        # Calculate statistics
        successful = [r for r in results if r['success']]
        
        return {
            'success': len(successful) > 0,
            'method': method,
            'tasks_processed': len(open_tasks),
            'tasks_allocated': len(successful),
            'tasks_failed': len(results) - len(successful),
            'results': results
        }
    
    def get_allocation_statistics(self) -> Dict[str, Any]:
        """
        Get task allocation statistics.
        
        Returns:
            Dict with allocation metrics
        """
        # Count tasks by status
        status_counts = {}
        for task in self.task_pool:
            status = task['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Count robots by workload
        robot_workload = {
            'idle': 0,
            'working': 0,
            'overloaded': 0
        }
        
        for robot in self.robots.values():
            if robot['task_assignment'] is None:
                robot_workload['idle'] += 1
            elif robot['task_assignment']['progress_percent'] < 80:
                robot_workload['working'] += 1
            else:
                robot_workload['overloaded'] += 1
        
        # Calculate utilization
        total_robots = len(self.robots)
        utilization = (robot_workload['working'] + robot_workload['overloaded']) / total_robots if total_robots > 0 else 0
        
        # Calculate average task priority
        priority_map = {'low': 1, 'medium': 2, 'high': 3}
        avg_priority = sum(priority_map.get(t['priority'], 1) for t in self.task_pool) / len(self.task_pool) if self.task_pool else 0
        
        return {
            'total_tasks': len(self.task_pool),
            'status_distribution': status_counts,
            'total_robots': total_robots,
            'robot_workload': robot_workload,
            'utilization_percent': round(utilization * 100, 1),
            'tasks_allocated_total': self.tasks_allocated,
            'average_priority': round(avg_priority, 2),
            'idle_robots': robot_workload['idle'],
            'status': 'OPTIMAL' if utilization > 0.7 else ('GOOD' if utilization > 0.5 else 'UNDERUTILIZED')
        }


def test_task_distributor():
    """Test the task distributor with example data."""
    print("=" * 80)
    print("TESTANDO TASK DISTRIBUTOR (AUCTION & HUNGARIAN)")
    print("=" * 80)
    
    # Load example swarm data
    with open('example_swarm_data.json', 'r', encoding='utf-8') as f:
        swarm_data = json.load(f)
    
    config = swarm_data['swarm_config']
    
    # Create task distributor
    distributor = TaskDistributor(swarm_data, config)
    
    print("\n📊 ESTADO INICIAL")
    stats = distributor.get_allocation_statistics()
    print(f"   Total de tarefas: {stats['total_tasks']}")
    print(f"   Distribuição de status:")
    for status, count in stats['status_distribution'].items():
        print(f"      - {status}: {count}")
    print(f"   Total de robôs: {stats['total_robots']}")
    print(f"   Carga de trabalho:")
    for workload, count in stats['robot_workload'].items():
        print(f"      - {workload}: {count}")
    print(f"   Utilização: {stats['utilization_percent']}% ({stats['status']})")
    
    # Test 1: Auction-based allocation
    print("\n" + "=" * 80)
    print("TESTE 1: Alocação por leilão (auction-based)")
    print("=" * 80)
    
    auction_result = distributor.allocate_tasks(method='auction')
    
    print(f"\n✅ Método: {auction_result['method']}")
    print(f"   Tarefas processadas: {auction_result['tasks_processed']}")
    print(f"   Tarefas alocadas: {auction_result['tasks_allocated']}")
    print(f"   Tarefas falhadas: {auction_result['tasks_failed']}")
    
    # Show auction details for first 3 tasks
    print(f"\n   📋 DETALHES DOS LEILÕES (primeiras 3 tarefas):")
    for i, result in enumerate(auction_result['results'][:3], 1):
        if result['success']:
            winner = result['winner']
            print(f"\n      {i}. Tarefa {result['task_id']}")
            print(f"         Vencedor: {winner['robot_id']}")
            print(f"         Lance vencedor: {winner['bid_value']:.3f}")
            print(f"         Custo estimado: {winner['estimated_cost_kwh']:.2f} kWh")
            print(f"         Tempo estimado: {winner['estimated_time_minutes']:.1f} min")
            print(f"         Distância: {winner['distance_km']:.2f} km")
            print(f"         Total de lances: {result['bids_received']}")
            
            # Show bid components
            components = winner['components']
            print(f"         Componentes do lance:")
            print(f"            - Distância: {components['distance_score']:.3f}")
            print(f"            - Bateria: {components['battery_score']:.3f}")
            print(f"            - Carga trabalho: {components['workload_score']:.3f}")
            print(f"            - Prioridade: {components['priority_score']:.3f}")
        else:
            print(f"\n      {i}. Tarefa {result['task_id']}")
            print(f"         ❌ Falhou: {result['reason']}")
    
    # Test 2: Reset and test Hungarian
    print("\n" + "=" * 80)
    print("TESTE 2: Alocação por Hungarian (optimal assignment)")
    print("=" * 80)
    
    # Reload data to reset
    with open('example_swarm_data.json', 'r', encoding='utf-8') as f:
        swarm_data = json.load(f)
    
    distributor2 = TaskDistributor(swarm_data, config)
    
    hungarian_result = distributor2.allocate_tasks(method='hungarian')
    
    if hungarian_result['success']:
        print(f"\n✅ Método: {hungarian_result['method']}")
        print(f"   Tarefas processadas: {hungarian_result['tasks_processed']}")
        print(f"   Tarefas alocadas: {hungarian_result['tasks_allocated']}")
        
        for result in hungarian_result['results']:
            if 'assignments' in result:
                print(f"\n   📋 ATRIBUIÇÕES:")
                print(f"      Custo total: {result['total_cost']:.3f}")
                print(f"      Tarefas atribuídas: {result['tasks_assigned']}")
                
                for i, (task_id, robot_id) in enumerate(result['assignments'].items(), 1):
                    if robot_id:
                        print(f"      {i}. {task_id} → {robot_id}")
                    else:
                        print(f"      {i}. {task_id} → (não atribuída)")
    
    # Final statistics
    print("\n" + "=" * 80)
    print("ESTATÍSTICAS FINAIS (após auction)")
    print("=" * 80)
    
    final_stats = distributor.get_allocation_statistics()
    print(f"\n📊 Métricas:")
    print(f"   Total de tarefas: {final_stats['total_tasks']}")
    print(f"   Tarefas alocadas: {final_stats['tasks_allocated_total']}")
    print(f"   Total de robôs: {final_stats['total_robots']}")
    print(f"   Robôs ociosos: {final_stats['idle_robots']}")
    print(f"   Utilização: {final_stats['utilization_percent']}%")
    print(f"   Prioridade média: {final_stats['average_priority']:.2f}")
    print(f"   Status: {final_stats['status']}")
    
    print(f"\n   Distribuição de status:")
    for status, count in final_stats['status_distribution'].items():
        print(f"      - {status}: {count}")
    
    print(f"\n   Carga de trabalho dos robôs:")
    for workload, count in final_stats['robot_workload'].items():
        icon = '💼' if workload == 'working' else ('😴' if workload == 'idle' else '🔥')
        print(f"      {icon} {workload}: {count}")
    
    print("\n✅ Task distributor funcionando!")


if __name__ == "__main__":
    test_task_distributor()
