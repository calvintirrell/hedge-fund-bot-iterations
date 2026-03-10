"""
Consensus Engine Module
Weighted voting algorithm for agent coordination with explainability
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """
    Calculates weighted consensus from multiple agent votes.
    
    Features:
    - Weighted voting based on confidence and historical accuracy
    - Market regime awareness
    - Full explainability with detailed reasoning
    - Configurable consensus thresholds
    """
    
    def __init__(self, performance_tracker, consensus_threshold: float = 0.6):
        """
        Initialize ConsensusEngine.
        
        Args:
            performance_tracker: AgentPerformanceTracker instance
            consensus_threshold: Minimum score to trigger BUY (default: 0.6)
        """
        self.performance_tracker = performance_tracker
        self.threshold = consensus_threshold
        
        # Base weights for each agent (can be adjusted)
        self.base_weights = {
            'sentiment': 1.0,
            'fundamental': 1.0,
            'technical': 1.0
        }
        
        logger.info(f"ConsensusEngine initialized (threshold: {consensus_threshold})")
    
    def calculate_consensus(
        self,
        votes: Dict[str, Dict[str, Any]],
        symbol: str,
        market_conditions: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Calculate weighted consensus from agent votes.
        
        Args:
            votes: Dictionary of agent votes
                {
                    'sentiment': {'signal': 'BUY', 'confidence': 0.7, 'reasoning': '...'},
                    'fundamental': {'signal': 'BUY', 'confidence': 0.8, 'reasoning': '...'},
                    'technical': {'signal': 'WAIT', 'confidence': 0.6, 'reasoning': '...'}
                }
            symbol: Stock symbol being analyzed
            market_conditions: Optional MarketConditions from MarketRegimeDetector
        
        Returns:
            {
                'signal': 'BUY' or 'WAIT',
                'consensus_score': float (0.0-1.0),
                'confidence': float (0.0-1.0),
                'votes': dict,
                'weights': dict,
                'reasoning': str
            }
        """
        # Calculate weights for each vote
        weights = {}
        buy_weight = 0.0
        wait_weight = 0.0
        total_weight = 0.0
        
        for agent_name, vote in votes.items():
            if vote.get('signal') == 'ERROR':
                weights[agent_name] = 0.0
                continue
            
            # Calculate weight for this vote
            weight = self._calculate_vote_weight(
                agent_name=agent_name,
                vote=vote,
                symbol=symbol,
                market_conditions=market_conditions
            )
            
            weights[agent_name] = weight
            total_weight += weight
            
            # Accumulate weights by signal
            if vote['signal'] == 'BUY':
                buy_weight += weight
            else:  # WAIT
                wait_weight += weight
        
        # Calculate consensus score
        if total_weight == 0:
            consensus_score = 0.0
            signal = 'WAIT'
            confidence = 0.0
        else:
            consensus_score = buy_weight / total_weight
            signal = 'BUY' if consensus_score >= self.threshold else 'WAIT'
            
            # Confidence is based on how decisive the vote is
            # High confidence if score is far from threshold (0.6)
            distance_from_threshold = abs(consensus_score - self.threshold)
            confidence = min(1.0, distance_from_threshold * 2.5 + 0.5)
        
        # Build detailed reasoning
        reasoning = self._build_reasoning(
            votes=votes,
            weights=weights,
            consensus_score=consensus_score,
            signal=signal,
            confidence=confidence,
            buy_weight=buy_weight,
            wait_weight=wait_weight
        )
        
        return {
            'signal': signal,
            'consensus_score': consensus_score,
            'confidence': confidence,
            'votes': votes,
            'weights': weights,
            'reasoning': reasoning
        }
    
    def _calculate_vote_weight(
        self,
        agent_name: str,
        vote: Dict[str, Any],
        symbol: str,
        market_conditions: Optional[Any]
    ) -> float:
        """
        Calculate weight for a single agent vote.
        
        Components:
        1. Base weight (configurable per agent)
        2. Confidence (from agent's analysis)
        3. Historical accuracy (from performance tracker)
        4. Market regime modifier (optional)
        
        Returns:
            Weight as float
        """
        # 1. Base weight
        base = self.base_weights.get(agent_name, 1.0)
        
        # 2. Confidence from agent
        confidence = vote.get('confidence', 0.5)
        
        # 3. Historical accuracy (recent 20 trades)
        accuracy = self.performance_tracker.get_agent_accuracy(
            agent_name=agent_name,
            symbol=symbol,
            recent_n=20
        )
        
        # 4. Market regime modifier
        regime_mod = 1.0
        if market_conditions:
            regime_mod = self._get_regime_modifier(
                vote['signal'],
                market_conditions
            )
        
        # Calculate final weight
        weight = base * confidence * accuracy * regime_mod
        
        logger.debug(
            f"{agent_name} weight: {weight:.3f} "
            f"(base: {base}, conf: {confidence:.2f}, acc: {accuracy:.2f}, regime: {regime_mod:.2f})"
        )
        
        return weight
    
    def _get_regime_modifier(self, signal: str, market_conditions: Any) -> float:
        """
        Get market regime modifier for a signal.
        
        Logic:
        - In bull markets: Boost BUY signals, reduce WAIT signals
        - In bear markets: Reduce BUY signals, boost WAIT signals
        - In neutral markets: No modification
        
        Returns:
            Modifier (0.8-1.2)
        """
        from v8_modules.market_regime import MarketRegime
        
        regime = market_conditions.regime
        
        if signal == 'BUY':
            if regime in [MarketRegime.STRONG_BULL, MarketRegime.BULL]:
                return 1.2  # Boost bullish signals in bull market
            elif regime in [MarketRegime.BEAR, MarketRegime.STRONG_BEAR]:
                return 0.8  # Reduce bullish signals in bear market
        else:  # WAIT
            if regime in [MarketRegime.STRONG_BULL, MarketRegime.BULL]:
                return 0.8  # Reduce cautious signals in bull market
            elif regime in [MarketRegime.BEAR, MarketRegime.STRONG_BEAR]:
                return 1.2  # Boost cautious signals in bear market
        
        return 1.0  # Neutral market or no modification
    
    def _build_reasoning(
        self,
        votes: Dict[str, Dict],
        weights: Dict[str, float],
        consensus_score: float,
        signal: str,
        confidence: float,
        buy_weight: float,
        wait_weight: float
    ) -> str:
        """
        Generate human-readable explanation of decision.
        
        Returns:
            Detailed reasoning string
        """
        # Determine consensus strength
        if consensus_score >= 0.8:
            strength = "STRONG"
        elif consensus_score >= 0.6:
            strength = "MODERATE"
        elif consensus_score >= 0.4:
            strength = "WEAK"
        else:
            strength = "STRONG"  # Strong WAIT
        
        # Confidence level
        if confidence >= 0.8:
            conf_level = "HIGH"
        elif confidence >= 0.6:
            conf_level = "MEDIUM"
        else:
            conf_level = "LOW"
        
        # Build header
        reasoning = f"\n{'='*60}\n"
        reasoning += f"CONSENSUS: {signal} (score: {consensus_score:.2f}, confidence: {conf_level})\n"
        reasoning += f"Strength: {strength}\n"
        reasoning += f"{'='*60}\n\n"
        
        # Voting breakdown
        reasoning += "Voting Breakdown:\n"
        
        for agent_name, vote in votes.items():
            if vote.get('signal') == 'ERROR':
                reasoning += f"✗ {agent_name.capitalize()}: ERROR\n"
                continue
            
            weight = weights.get(agent_name, 0.0)
            vote_signal = vote['signal']
            vote_conf = vote.get('confidence', 0.0)
            
            # Get accuracy for display
            accuracy = self.performance_tracker.get_agent_accuracy(agent_name, recent_n=20)
            
            # Symbol for vote alignment
            symbol = "✓" if vote_signal == signal else "✗"
            
            reasoning += f"{symbol} {agent_name.capitalize()}: {vote_signal} "
            reasoning += f"(conf: {vote_conf:.2f}, weight: {weight:.2f}, acc: {accuracy:.0%})\n"
            
            # Add agent's reasoning (indented)
            agent_reasoning = vote.get('reasoning', 'No reasoning provided')
            reasoning += f"  → {agent_reasoning}\n\n"
        
        # Decision explanation
        reasoning += f"{'='*60}\n"
        reasoning += "Decision Logic:\n"
        reasoning += f"• Total BUY weight: {buy_weight:.2f}\n"
        reasoning += f"• Total WAIT weight: {wait_weight:.2f}\n"
        reasoning += f"• Consensus score: {buy_weight:.2f} / {buy_weight + wait_weight:.2f} = {consensus_score:.2f}\n"
        reasoning += f"• Threshold: {self.threshold:.2f}\n"
        reasoning += f"• Result: {signal} ({'score >= threshold' if signal == 'BUY' else 'score < threshold'})\n"
        reasoning += f"{'='*60}\n"
        
        return reasoning
    
    def set_base_weight(self, agent_name: str, weight: float):
        """
        Set base weight for an agent.
        
        Args:
            agent_name: Agent to modify
            weight: New base weight (typically 0.5-1.5)
        """
        # Clamp weight to reasonable range
        weight = max(0.5, min(1.5, weight))
        self.base_weights[agent_name] = weight
        logger.info(f"Set {agent_name} base weight to {weight:.2f}")
    
    def get_base_weights(self) -> Dict[str, float]:
        """Get current base weights for all agents"""
        return self.base_weights.copy()
