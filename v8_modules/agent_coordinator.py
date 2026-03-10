"""
Agent Coordinator Module
Main orchestration layer for multi-agent coordination with adaptive learning
"""

import logging
from typing import Dict, Any, Optional
from v8_modules.agent_performance import AgentPerformanceTracker
from v8_modules.consensus_engine import ConsensusEngine

logger = logging.getLogger(__name__)


class AgentCoordinator:
    """
    Coordinates multiple agents with adaptive learning.
    
    Responsibilities:
    1. Collect votes from all agents
    2. Calculate weighted consensus
    3. Record predictions for learning
    4. Update agent weights based on outcomes
    5. Provide explainable decisions
    
    Features:
    - Adaptive learning from trade outcomes
    - Performance tracking per agent
    - Weighted voting with confidence
    - Market regime awareness
    - Full explainability
    """
    
    def __init__(
        self,
        agents: Dict[str, Any],
        market_regime_detector: Optional[Any] = None,
        consensus_threshold: float = 0.6,
        performance_file: str = 'agent_performance_history.json'
    ):
        """
        Initialize AgentCoordinator.
        
        Args:
            agents: Dictionary of agent instances {'sentiment': SentimentAgent, ...}
            market_regime_detector: Optional MarketRegimeDetector instance
            consensus_threshold: Minimum score to trigger BUY (default: 0.6)
            performance_file: Path to save/load performance data
        """
        self.agents = agents
        self.market_regime = market_regime_detector
        self.performance_file = performance_file
        
        # Initialize performance tracker
        self.performance_tracker = AgentPerformanceTracker()
        
        # Load historical performance if available
        self.performance_tracker.load_from_file(performance_file)
        
        # Initialize consensus engine
        self.consensus_engine = ConsensusEngine(
            performance_tracker=self.performance_tracker,
            consensus_threshold=consensus_threshold
        )
        
        logger.info(f"AgentCoordinator initialized with {len(agents)} agents")
        logger.info(f"Consensus threshold: {consensus_threshold}")
        
        # Log loaded performance
        summary = self.performance_tracker.get_summary()
        if summary:
            logger.info("Loaded agent performance:")
            for agent, metrics in summary.items():
                logger.info(
                    f"  {agent}: {metrics['accuracy']:.1%} accuracy "
                    f"({metrics['total_trades']} trades)"
                )
    
    def get_consensus(self, symbol: str) -> Dict[str, Any]:
        """
        Get weighted consensus for a symbol.
        
        Workflow:
        1. Get market conditions (if available)
        2. Collect votes from all agents
        3. Calculate weighted consensus
        4. Return decision with full explanation
        
        Args:
            symbol: Stock symbol to analyze
            
        Returns:
            Consensus dictionary with signal, score, confidence, and reasoning
        """
        # 1. Get market conditions
        market_conditions = None
        if self.market_regime:
            try:
                market_conditions = self.market_regime.get_market_conditions()
                logger.debug(f"Market regime: {market_conditions.regime.value}")
            except Exception as e:
                logger.warning(f"Failed to get market conditions: {e}")
        
        # 2. Collect votes from all agents
        votes = {}
        for agent_name, agent in self.agents.items():
            try:
                logger.debug(f"Collecting vote from {agent_name}...")
                result = agent.analyze(symbol)
                votes[agent_name] = result
                logger.debug(
                    f"{agent_name}: {result.get('signal', 'ERROR')} "
                    f"(conf: {result.get('confidence', 0.0):.2f})"
                )
            except Exception as e:
                logger.error(f"{agent_name} analysis failed: {e}")
                votes[agent_name] = {
                    'signal': 'ERROR',
                    'confidence': 0.0,
                    'reasoning': f'Analysis error: {str(e)}'
                }
        
        # 3. Calculate weighted consensus
        consensus = self.consensus_engine.calculate_consensus(
            votes=votes,
            symbol=symbol,
            market_conditions=market_conditions
        )
        
        logger.info(
            f"Consensus for {symbol}: {consensus['signal']} "
            f"(score: {consensus['consensus_score']:.2f}, "
            f"confidence: {consensus['confidence']:.2f})"
        )
        
        return consensus
    
    def record_trade_entry(
        self,
        symbol: str,
        consensus: Dict[str, Any],
        trade_id: str
    ):
        """
        Record agent predictions when a trade is opened.
        
        This links agent votes to trade outcomes for learning.
        
        Args:
            symbol: Stock symbol
            consensus: Consensus dictionary from get_consensus()
            trade_id: Unique trade identifier
        """
        votes = consensus.get('votes', {})
        
        for agent_name, vote in votes.items():
            if vote.get('signal') != 'ERROR':
                self.performance_tracker.record_prediction(
                    agent_name=agent_name,
                    symbol=symbol,
                    signal=vote['signal'],
                    confidence=vote.get('confidence', 0.5),
                    trade_id=trade_id
                )
        
        logger.info(f"Recorded predictions for trade {trade_id}")
    
    def update_from_trade_outcome(self, trade_id: str, pnl_pct: float):
        """
        Update agent performance when a trade closes.
        
        Args:
            trade_id: Trade identifier
            pnl_pct: P&L percentage (positive = profit, negative = loss)
        
        Logic:
        - If profitable (pnl_pct > 0): Agents that voted BUY were correct
        - If loss (pnl_pct < 0): Agents that voted BUY were incorrect
        - Agents that voted WAIT: Opposite outcome
        """
        outcome = 'correct' if pnl_pct > 0 else 'incorrect'
        self.performance_tracker.update_outcome(trade_id, outcome)
        
        logger.info(
            f"Updated agent performance for trade {trade_id}: "
            f"{outcome} (P&L: {pnl_pct:+.2f}%)"
        )
        
        # Auto-save every 10 trades
        if self.performance_tracker.total_trades % 10 == 0:
            self.save_performance()
            logger.info(f"Auto-saved performance data ({self.performance_tracker.total_trades} trades)")
    
    def save_performance(self):
        """Save performance data to file"""
        try:
            self.performance_tracker.save_to_file(self.performance_file)
            logger.debug(f"Saved performance data to {self.performance_file}")
        except Exception as e:
            logger.error(f"Failed to save performance data: {e}")
    
    def get_performance_summary(self) -> Dict[str, Dict]:
        """
        Get summary of all agent performance metrics.
        
        Returns:
            Dictionary with performance summary for each agent
        """
        return self.performance_tracker.get_summary()
    
    def get_detailed_metrics(self, agent_name: str) -> Dict[str, Any]:
        """
        Get detailed metrics for a specific agent.
        
        Args:
            agent_name: Agent to query
            
        Returns:
            Detailed metrics dictionary
        """
        return self.performance_tracker.get_metrics(agent_name)
    
    def adjust_agent_weight(self, agent_name: str, adjustment: float):
        """
        Manually adjust an agent's base weight.
        
        Args:
            agent_name: Agent to adjust
            adjustment: Weight adjustment (e.g., 1.1 = 10% increase)
        """
        current = self.consensus_engine.base_weights.get(agent_name, 1.0)
        new_weight = current * adjustment
        self.consensus_engine.set_base_weight(agent_name, new_weight)
        
        logger.info(
            f"Adjusted {agent_name} weight: {current:.2f} → {new_weight:.2f} "
            f"({adjustment:+.1%} change)"
        )
    
    def auto_adjust_weights(self, min_trades: int = 10):
        """
        Automatically adjust agent weights based on recent performance.
        
        Args:
            min_trades: Minimum trades before adjusting weights
        """
        if self.performance_tracker.total_trades < min_trades:
            logger.info(
                f"Insufficient trades for weight adjustment "
                f"({self.performance_tracker.total_trades}/{min_trades})"
            )
            return
        
        logger.info("Auto-adjusting agent weights based on performance...")
        
        for agent_name in self.agents.keys():
            # Get recent accuracy
            recent_acc = self.performance_tracker.get_agent_accuracy(
                agent_name=agent_name,
                recent_n=20
            )
            
            # Calculate target weight based on accuracy
            # 50% accuracy = 0.8x weight
            # 75% accuracy = 1.0x weight (neutral)
            # 100% accuracy = 1.2x weight
            target_multiplier = 0.8 + (recent_acc - 0.5) * 0.8
            target_multiplier = max(0.8, min(1.2, target_multiplier))
            
            # Get current weight
            current = self.consensus_engine.base_weights.get(agent_name, 1.0)
            
            # Gradual adjustment (10% per adjustment)
            adjustment_rate = 0.1
            new_weight = current + (target_multiplier - current) * adjustment_rate
            
            # Apply adjustment
            self.consensus_engine.set_base_weight(agent_name, new_weight)
            
            logger.info(
                f"  {agent_name}: {current:.2f} → {new_weight:.2f} "
                f"(accuracy: {recent_acc:.1%})"
            )
    
    def get_agent_weights(self) -> Dict[str, float]:
        """Get current weights for all agents"""
        return self.consensus_engine.get_base_weights()
    
    def reset_performance(self):
        """Reset all performance data (use with caution)"""
        logger.warning("Resetting all agent performance data!")
        self.performance_tracker = AgentPerformanceTracker()
        self.consensus_engine.performance_tracker = self.performance_tracker
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the coordination system.
        
        Returns:
            Dictionary with system statistics
        """
        summary = self.get_performance_summary()
        weights = self.get_agent_weights()
        
        stats = {
            'total_trades': self.performance_tracker.total_trades,
            'agents': {}
        }
        
        for agent_name in self.agents.keys():
            agent_summary = summary.get(agent_name, {})
            stats['agents'][agent_name] = {
                'accuracy': agent_summary.get('accuracy', 0.5),
                'recent_accuracy': agent_summary.get('recent_accuracy', 0.5),
                'total_trades': agent_summary.get('total_trades', 0),
                'current_weight': weights.get(agent_name, 1.0)
            }
        
        return stats
