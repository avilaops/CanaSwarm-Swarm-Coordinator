"""
CanaSwarm Swarm-Coordinator - Consensus Manager Mock
=====================================================

Manages distributed consensus and leader election using Raft algorithm.

Author: Agro-Tech Ecosystem
Date: 2026-02-20
"""

import json
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum


class RobotRole(Enum):
    """Robot roles in Raft consensus"""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class ConsensusManager:
    """
    Manages distributed consensus using Raft algorithm.
    
    Raft consensus ensures:
    - Single leader election with majority vote
    - Consistent state replication across swarm
    - Fault tolerance (tolerates f failures with 2f+1 robots)
    - Split-brain prevention
    """
    
    def __init__(self, swarm_data: Dict[str, Any], config: Dict[str, Any]):
        """
        Initialize consensus manager.
        
        Args:
            swarm_data: Complete swarm state with robot info
            config: Configuration with timeouts and intervals
        """
        self.swarm_data = swarm_data
        self.config = config
        
        # Extract robots
        self.robots = {r['robot_id']: r for r in swarm_data['robots']}
        self.total_robots = len(self.robots)
        
        # Consensus state
        self.current_leader = swarm_data['swarm_state']['leader_id']
        self.current_term = swarm_data['swarm_state']['consensus_term']
        
        # Timeouts (seconds)
        self.heartbeat_interval = config.get('heartbeat_interval_seconds', 1.0)
        self.election_timeout = config.get('election_timeout_seconds', 5.0)
        
        # Statistics
        self.election_count = swarm_data['performance_metrics']['consensus']['election_count']
        self.split_brain_incidents = 0
        
        # Network topology for communication
        self.topology = self._build_topology(swarm_data.get('network_topology', {}))
    
    def _build_topology(self, topology_data: Dict) -> Dict[str, List[str]]:
        """
        Build adjacency list from network topology.
        
        Args:
            topology_data: Network graph with nodes and edges
            
        Returns:
            Dict mapping robot_id to list of neighbor robot_ids
        """
        graph = topology_data.get('graph', {})
        edges = graph.get('edges', [])
        
        adjacency = {robot_id: [] for robot_id in self.robots.keys()}
        
        for edge in edges:
            from_id = edge['from']
            to_id = edge['to']
            
            # Undirected graph (bidirectional communication)
            if from_id in adjacency:
                adjacency[from_id].append(to_id)
            if to_id in adjacency:
                adjacency[to_id].append(from_id)
        
        return adjacency
    
    def check_leader_health(self) -> Dict[str, Any]:
        """
        Check if current leader is healthy and sending heartbeats.
        
        Returns:
            Dict with leader health status
        """
        if not self.current_leader or self.current_leader not in self.robots:
            return {
                'healthy': False,
                'reason': 'no_leader',
                'action': 'trigger_election'
            }
        
        leader = self.robots[self.current_leader]
        last_heartbeat_str = leader['swarm_role']['last_heartbeat']
        last_heartbeat = datetime.fromisoformat(last_heartbeat_str.replace('Z', '+00:00'))
        
        current_time = datetime.fromisoformat(self.swarm_data['timestamp'].replace('Z', '+00:00'))
        time_since_heartbeat = (current_time - last_heartbeat).total_seconds()
        
        # Check if leader is connected and operational
        is_connected = leader['communication']['connected']
        is_operational = leader['status']['operational'] in ['working', 'idle']
        is_heartbeat_recent = time_since_heartbeat < self.election_timeout
        
        healthy = is_connected and is_operational and is_heartbeat_recent
        
        result = {
            'healthy': healthy,
            'leader_id': self.current_leader,
            'time_since_heartbeat_s': round(time_since_heartbeat, 2),
            'connected': is_connected,
            'operational': is_operational,
            'heartbeat_recent': is_heartbeat_recent
        }
        
        if not healthy:
            if not is_connected:
                result['reason'] = 'leader_disconnected'
            elif not is_operational:
                result['reason'] = 'leader_not_operational'
            elif not is_heartbeat_recent:
                result['reason'] = 'heartbeat_timeout'
            
            result['action'] = 'trigger_election'
        
        return result
    
    def trigger_leader_election(self) -> Dict[str, Any]:
        """
        Trigger a new leader election using Raft algorithm.
        
        Raft election process:
        1. Robot becomes candidate, increments term
        2. Votes for itself
        3. Sends RequestVote RPCs to all other robots
        4. If receives votes from majority: becomes leader
        5. If another robot becomes leader: becomes follower
        6. If election timeout elapses: starts new election
        
        Returns:
            Dict with election results
        """
        print(f"\n🗳️  INICIANDO ELEIÇÃO DE LÍDER")
        print(f"   Term atual: {self.current_term}")
        print(f"   Total de robôs: {self.total_robots}")
        
        # Increment term for new election
        new_term = self.current_term + 1
        self.current_term = new_term
        self.election_count += 1
        
        # Find candidates (connected, operational, sufficient battery)
        candidates = []
        for robot_id, robot in self.robots.items():
            is_connected = robot['communication']['connected']
            is_operational = robot['status']['operational'] in ['working', 'idle', 'charging']
            has_battery = robot['status']['battery_soc_percent'] >= 40
            
            if is_connected and is_operational and has_battery:
                # Calculate candidate priority (higher is better)
                # Priority = battery(50%) + uptime(30%) + neighbors(20%)
                battery_score = robot['status']['battery_soc_percent'] / 100
                uptime_score = min(robot['status']['uptime_hours'] / 12, 1.0)  # Normalize to 12 hours
                neighbor_score = len(robot['communication']['neighbors']) / self.total_robots
                
                priority = (battery_score * 0.5 + 
                           uptime_score * 0.3 + 
                           neighbor_score * 0.2)
                
                candidates.append({
                    'robot_id': robot_id,
                    'priority': priority,
                    'battery': robot['status']['battery_soc_percent'],
                    'uptime': robot['status']['uptime_hours'],
                    'neighbors': len(robot['communication']['neighbors'])
                })
        
        if not candidates:
            return {
                'success': False,
                'reason': 'no_viable_candidates',
                'term': new_term
            }
        
        # Sort by priority (highest first)
        candidates.sort(key=lambda c: c['priority'], reverse=True)
        
        print(f"\n   📋 CANDIDATOS (ordenados por prioridade):")
        for i, candidate in enumerate(candidates[:5], 1):
            print(f"      {i}. {candidate['robot_id']}: priority {candidate['priority']:.3f} "
                  f"(battery {candidate['battery']}%, uptime {candidate['uptime']:.1f}h, "
                  f"neighbors {candidate['neighbors']})")
        
        # Top candidate initiates election
        candidate_id = candidates[0]['robot_id']
        
        # Simulate voting process
        votes = self._simulate_voting(candidate_id, candidates)
        
        votes_received = votes['votes_for']
        majority = (self.total_robots // 2) + 1
        won_election = votes_received >= majority
        
        print(f"\n   🗳️  RESULTADO DA VOTAÇÃO:")
        print(f"      Candidato: {candidate_id}")
        print(f"      Votos recebidos: {votes_received}/{self.total_robots}")
        print(f"      Maioria necessária: {majority}")
        print(f"      {'✅ ELEITO!' if won_election else '❌ NÃO ATINGIU MAIORIA'}")
        
        if won_election:
            # Update leader
            self.current_leader = candidate_id
            
            # Update all robots' swarm_role
            for robot_id, robot in self.robots.items():
                if robot_id == candidate_id:
                    robot['swarm_role']['role'] = RobotRole.LEADER.value
                    robot['swarm_role']['voted_for'] = candidate_id
                else:
                    robot['swarm_role']['role'] = RobotRole.FOLLOWER.value
                    if robot_id in votes['voted_for']:
                        robot['swarm_role']['voted_for'] = candidate_id
                
                robot['swarm_role']['term'] = new_term
            
            duration = random.uniform(1.5, 3.0)
            
            return {
                'success': True,
                'new_leader': candidate_id,
                'term': new_term,
                'votes_received': votes_received,
                'total_robots': self.total_robots,
                'majority': majority,
                'duration_seconds': round(duration, 2),
                'vote_details': votes
            }
        else:
            # Election failed, will retry
            return {
                'success': False,
                'reason': 'no_majority',
                'candidate': candidate_id,
                'term': new_term,
                'votes_received': votes_received,
                'total_robots': self.total_robots,
                'majority': majority,
                'action': 'retry_election'
            }
    
    def _simulate_voting(self, candidate_id: str, candidates: List[Dict]) -> Dict[str, Any]:
        """
        Simulate voting process.
        
        Each robot votes based on:
        - Candidate's term (must be >= robot's term)
        - Candidate's priority (higher is better)
        - Network connectivity (must be reachable)
        
        Args:
            candidate_id: ID of the candidate requesting votes
            candidates: List of all candidates with priorities
            
        Returns:
            Dict with voting results
        """
        candidate_priority = next(c['priority'] for c in candidates if c['robot_id'] == candidate_id)
        
        votes_for = 1  # Candidate votes for itself
        voted_for = [candidate_id]
        voted_against = []
        no_response = []
        
        for robot_id, robot in self.robots.items():
            if robot_id == candidate_id:
                continue  # Already voted for itself
            
            is_connected = robot['communication']['connected']
            is_reachable = self._is_reachable(robot_id, candidate_id)
            
            if not is_connected or not is_reachable:
                no_response.append(robot_id)
                continue
            
            # Vote decision based on:
            # 1. Network latency (lower is better for responsiveness)
            # 2. Candidate priority (higher is better)
            # 3. Random factor (simulates network variability)
            
            latency = robot['communication']['latency_ms']
            latency_score = max(0, 1 - latency / 100)  # Lower latency = higher score
            
            # Probability of voting for candidate
            vote_probability = (candidate_priority * 0.6 + 
                              latency_score * 0.3 + 
                              random.uniform(0, 0.1))
            
            if random.random() < vote_probability:
                votes_for += 1
                voted_for.append(robot_id)
            else:
                voted_against.append(robot_id)
        
        return {
            'votes_for': votes_for,
            'votes_against': len(voted_against),
            'no_response': len(no_response),
            'voted_for': voted_for,
            'voted_against': voted_against,
            'no_response': no_response
        }
    
    def _is_reachable(self, from_robot: str, to_robot: str) -> bool:
        """
        Check if robot can communicate with another (direct or multi-hop).
        
        Args:
            from_robot: Source robot ID
            to_robot: Destination robot ID
            
        Returns:
            True if reachable, False otherwise
        """
        # BFS to check connectivity
        if from_robot not in self.topology or to_robot not in self.topology:
            return False
        
        visited = set()
        queue = [from_robot]
        
        while queue:
            current = queue.pop(0)
            if current == to_robot:
                return True
            
            if current in visited:
                continue
            
            visited.add(current)
            
            neighbors = self.topology.get(current, [])
            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append(neighbor)
        
        return False
    
    def replicate_state(self, state_update: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replicate state from leader to followers (Raft log replication).
        
        Args:
            state_update: State update to replicate
            
        Returns:
            Dict with replication status
        """
        if self.current_leader not in self.robots:
            return {
                'success': False,
                'reason': 'no_leader'
            }
        
        leader = self.robots[self.current_leader]
        
        # Find all connected followers
        followers = []
        for robot_id, robot in self.robots.items():
            if (robot_id != self.current_leader and 
                robot['swarm_role']['role'] == RobotRole.FOLLOWER.value and
                robot['communication']['connected']):
                followers.append(robot_id)
        
        # Simulate replication (AppendEntries RPCs)
        replicated_to = []
        failed_to_replicate = []
        
        for follower_id in followers:
            is_reachable = self._is_reachable(self.current_leader, follower_id)
            
            # Replication success probability based on network quality
            follower = self.robots[follower_id]
            signal_strength = follower['communication']['signal_strength_dbm']
            latency = follower['communication']['latency_ms']
            
            # Better signal and lower latency = higher success rate
            success_probability = (min(1, (signal_strength + 100) / 50) * 0.6 +
                                  max(0, 1 - latency / 100) * 0.3 +
                                  0.1)  # Base success rate
            
            if is_reachable and random.random() < success_probability:
                replicated_to.append(follower_id)
            else:
                failed_to_replicate.append(follower_id)
        
        majority = (self.total_robots // 2) + 1
        committed = len(replicated_to) + 1 >= majority  # +1 for leader
        
        return {
            'success': committed,
            'leader_id': self.current_leader,
            'replicated_to_count': len(replicated_to),
            'replicated_to': replicated_to[:5],  # Show first 5
            'failed_count': len(failed_to_replicate),
            'failed_to': failed_to_replicate,
            'majority': majority,
            'committed': committed,
            'state_update': state_update
        }
    
    def get_consensus_status(self) -> Dict[str, Any]:
        """
        Get current consensus status.
        
        Returns:
            Dict with detailed consensus status
        """
        # Count robots by role
        role_counts = {
            'leader': 0,
            'follower': 0,
            'candidate': 0,
            'disconnected': 0
        }
        
        for robot in self.robots.values():
            if not robot['communication']['connected']:
                role_counts['disconnected'] += 1
            else:
                role = robot['swarm_role']['role']
                role_counts[role] = role_counts.get(role, 0) + 1
        
        # Check for split-brain (multiple leaders)
        split_brain = role_counts['leader'] > 1
        if split_brain:
            self.split_brain_incidents += 1
        
        # Calculate health score
        health_factors = {
            'has_leader': role_counts['leader'] == 1,
            'no_split_brain': not split_brain,
            'high_connectivity': role_counts['disconnected'] < self.total_robots * 0.2,
            'no_candidates': role_counts['candidate'] == 0
        }
        
        health_score = sum(health_factors.values()) / len(health_factors)
        
        return {
            'current_term': self.current_term,
            'current_leader': self.current_leader,
            'total_robots': self.total_robots,
            'role_counts': role_counts,
            'split_brain': split_brain,
            'split_brain_incidents': self.split_brain_incidents,
            'election_count': self.election_count,
            'health_score': round(health_score, 3),
            'health_factors': health_factors,
            'status': 'HEALTHY' if health_score >= 0.75 else ('WARNING' if health_score >= 0.5 else 'CRITICAL')
        }


def test_consensus_manager():
    """Test the consensus manager with example data."""
    print("=" * 80)
    print("TESTANDO CONSENSUS MANAGER (RAFT ALGORITHM)")
    print("=" * 80)
    
    # Load example swarm data
    with open('example_swarm_data.json', 'r', encoding='utf-8') as f:
        swarm_data = json.load(f)
    
    config = swarm_data['swarm_config']
    
    # Create consensus manager
    manager = ConsensusManager(swarm_data, config)
    
    print("\n📊 ESTADO INICIAL DO CONSENSO")
    status = manager.get_consensus_status()
    print(f"   Term atual: {status['current_term']}")
    print(f"   Líder atual: {status['current_leader']}")
    print(f"   Total de robôs: {status['total_robots']}")
    print(f"   Distribuição de papéis:")
    for role, count in status['role_counts'].items():
        print(f"      - {role}: {count}")
    print(f"   Health score: {status['health_score']:.1%} ({status['status']})")
    
    # Test 1: Check leader health
    print("\n" + "=" * 80)
    print("TESTE 1: Verificar saúde do líder")
    print("=" * 80)
    
    health = manager.check_leader_health()
    print(f"\n✅ Líder: {health.get('leader_id')}")
    print(f"   Saudável: {'✅ SIM' if health['healthy'] else '❌ NÃO'}")
    print(f"   Conectado: {'✅' if health.get('connected') else '❌'}")
    print(f"   Operacional: {'✅' if health.get('operational') else '❌'}")
    print(f"   Heartbeat recente: {'✅' if health.get('heartbeat_recent') else '❌'}")
    print(f"   Tempo desde último heartbeat: {health.get('time_since_heartbeat_s', 0):.2f}s")
    
    # Test 2: Trigger leader election
    print("\n" + "=" * 80)
    print("TESTE 2: Simular eleição de líder")
    print("=" * 80)
    
    election_result = manager.trigger_leader_election()
    
    if election_result['success']:
        print(f"\n✅ ELEIÇÃO BEM-SUCEDIDA!")
        print(f"   Novo líder: {election_result['new_leader']}")
        print(f"   Term: {election_result['term']}")
        print(f"   Votos recebidos: {election_result['votes_received']}/{election_result['total_robots']}")
        print(f"   Maioria: {election_result['majority']}")
        print(f"   Duração: {election_result['duration_seconds']}s")
        print(f"\n   📋 Votaram a favor: {', '.join(election_result['vote_details']['voted_for'][:5])}")
        if election_result['vote_details']['voted_against']:
            print(f"   📋 Votaram contra: {', '.join(election_result['vote_details']['voted_against'][:3])}")
    else:
        print(f"\n❌ ELEIÇÃO FALHOU")
        print(f"   Motivo: {election_result['reason']}")
        print(f"   Ação: {election_result.get('action')}")
    
    # Test 3: State replication
    print("\n" + "=" * 80)
    print("TESTE 3: Replicar estado do líder para seguidores")
    print("=" * 80)
    
    state_update = {
        'type': 'task_assignment',
        'task_id': 'TASK-NEW-001',
        'robot_id': 'MICROBOT-003',
        'timestamp': datetime.now().isoformat()
    }
    
    replication_result = manager.replicate_state(state_update)
    
    if replication_result['success']:
        print(f"\n✅ REPLICAÇÃO BEM-SUCEDIDA (commitada)")
        print(f"   Líder: {replication_result['leader_id']}")
        print(f"   Replicado para: {replication_result['replicated_to_count']} robôs")
        print(f"   Maioria atingida: {replication_result['majority']}")
        if replication_result['replicated_to']:
            print(f"   Robôs atualizados: {', '.join(replication_result['replicated_to'])}")
        if replication_result['failed_to']:
            print(f"   ⚠️  Falhou para {replication_result['failed_count']}: {', '.join(replication_result['failed_to'][:3])}")
    else:
        print(f"\n❌ REPLICAÇÃO FALHOU")
        print(f"   Motivo: {replication_result['reason']}")
    
    # Final status
    print("\n" + "=" * 80)
    print("ESTADO FINAL DO CONSENSO")
    print("=" * 80)
    
    final_status = manager.get_consensus_status()
    print(f"\n📊 Métricas:")
    print(f"   Term: {final_status['current_term']}")
    print(f"   Líder: {final_status['current_leader']}")
    print(f"   Total de eleições: {final_status['election_count']}")
    print(f"   Incidentes de split-brain: {final_status['split_brain_incidents']}")
    print(f"   Health score: {final_status['health_score']:.1%} ({final_status['status']})")
    print(f"\n   Fatores de saúde:")
    for factor, value in final_status['health_factors'].items():
        icon = '✅' if value else '❌'
        print(f"      {icon} {factor}")
    
    print("\n✅ Consensus manager funcionando!")


if __name__ == "__main__":
    test_consensus_manager()
