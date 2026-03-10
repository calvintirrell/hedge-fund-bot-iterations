"""
Agent Performance Tracking Module
Tracks agent predictions vs actual outcomes for adaptive learning
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AgentPrediction:
    """Single agent prediction record"""
    symbol: str
    timestamp: datetime
    signal: str  # 'BUY' or 'WAIT'
    confidence: float
    trade_id: str
    outcome: Optional[str] = None  # 'correct' or 'incorrect', set when trade closes
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'signal': self.signal,
            'confidence': self.confidence,
            'trade_id': self.trade_id,
            'outcome': self.outcome
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class AgentPerformanceTracker:
    """
    Tracks agent predictions and calculates performance metrics.
    
    Features:
    - Records predictions when trades open
    - Updates outcomes when trades close
    - Calculates various accuracy metrics
    - Persists data across restarts
    """
    
    def __init__(self):
        # Store predictions by agent
        self.predictions: Dict[str, List[AgentPrediction]] = defaultdict(list)
        
        # Cache for quick metric access
        self._metrics_cache: Dict[str, Dict] = {}
        self._cache_dirty = True
        
        logger.info("AgentPerformanceTracker initialized")
    
    def record_prediction(
        self,
        agent_name: str,
        symbol: str,
        signal: str,
        confidence: float,
        trade_id: str
    ):
        """
        Record an agent's prediction when a trade is opened.
        
        Args:
            agent_name: Name of the agent ('sentiment', 'fundamental', 'technical')
            symbol: Stock symbol
            signal: 'BUY' or 'WAIT'
            confidence: Confidence score (0.0-1.0)
            trade_id: Unique trade identifier
        """
        prediction = AgentPrediction(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=signal,
            confidence=confidence,
            trade_id=trade_id,
            outcome=None
        )
        
        self.predictions[agent_name].append(prediction)
        self._cache_dirty = True
        
        logger.debug(f"Recorded prediction: {agent_name} → {signal} for {symbol} (trade: {trade_id})")
    
    def update_outcome(self, trade_id: str, outcome: str):
        """
        Update prediction outcomes when a trade closes.
        
        Args:
            trade_id: Trade identifier
            outcome: 'correct' (profitable) or 'incorrect' (loss)
        """
        updated_count = 0
        
        for agent_name, predictions in self.predictions.items():
            for pred in predictions:
                if pred.trade_id == trade_id and pred.outcome is None:
                    # Determine if agent was correct
                    # If agent said BUY and trade was profitable → correct
                    # If agent said BUY and trade was loss → incorrect
                    # If agent said WAIT, outcome is inverted
                    if pred.signal == 'BUY':
                        pred.outcome = outcome
                    else:  # WAIT
                        pred.outcome = 'correct' if outcome == 'incorrect' else 'incorrect'
                    
                    updated_count += 1
                    logger.debug(f"Updated {agent_name} prediction for {trade_id}: {pred.outcome}")
        
        if updated_count > 0:
            self._cache_dirty = True
            logger.info(f"Updated {updated_count} predictions for trade {trade_id}")
        else:
            logger.warning(f"No predictions found for trade {trade_id}")
    
    def get_agent_accuracy(
        self,
        agent_name: str,
        symbol: Optional[str] = None,
        recent_n: Optional[int] = None
    ) -> float:
        """
        Get accuracy for an agent.
        
        Args:
            agent_name: Agent to query
            symbol: Optional symbol filter
            recent_n: Optional limit to recent N predictions
            
        Returns:
            Accuracy as float (0.0-1.0), or 0.5 if insufficient data
        """
        if agent_name not in self.predictions:
            return 0.5  # Default neutral accuracy
        
        predictions = self.predictions[agent_name]
        
        # Filter by symbol if specified
        if symbol:
            predictions = [p for p in predictions if p.symbol == symbol]
        
        # Filter to recent N if specified
        if recent_n:
            predictions = predictions[-recent_n:]
        
        # Only count predictions with outcomes
        completed = [p for p in predictions if p.outcome is not None]
        
        if len(completed) < 3:  # Need at least 3 trades for meaningful accuracy
            return 0.5
        
        correct = sum(1 for p in completed if p.outcome == 'correct')
        return correct / len(completed)
    
    def get_weighted_accuracy(self, agent_name: str) -> float:
        """
        Get confidence-weighted accuracy.
        
        High-confidence predictions are weighted more heavily.
        
        Returns:
            Weighted accuracy (0.0-1.0), or 0.5 if insufficient data
        """
        if agent_name not in self.predictions:
            return 0.5
        
        predictions = self.predictions[agent_name]
        completed = [p for p in predictions if p.outcome is not None]
        
        if len(completed) < 3:
            return 0.5
        
        total_weight = 0.0
        weighted_correct = 0.0
        
        for pred in completed:
            weight = pred.confidence
            total_weight += weight
            
            if pred.outcome == 'correct':
                weighted_correct += weight
        
        if total_weight == 0:
            return 0.5
        
        return weighted_correct / total_weight
    
    def get_metrics(self, agent_name: str) -> Dict[str, Any]:
        """
        Get comprehensive metrics for an agent.
        
        Returns:
            Dictionary with all performance metrics
        """
        if self._cache_dirty:
            self._rebuild_metrics_cache()
        
        return self._metrics_cache.get(agent_name, self._empty_metrics())
    
    def _rebuild_metrics_cache(self):
        """Rebuild the metrics cache for all agents"""
        self._metrics_cache = {}
        
        for agent_name in self.predictions.keys():
            self._metrics_cache[agent_name] = self._calculate_metrics(agent_name)
        
        self._cache_dirty = False
    
    def _calculate_metrics(self, agent_name: str) -> Dict[str, Any]:
        """Calculate all metrics for an agent"""
        predictions = self.predictions[agent_name]
        completed = [p for p in predictions if p.outcome is not None]
        
        if not completed:
            return self._empty_metrics()
        
        # Overall metrics
        total = len(completed)
        correct = sum(1 for p in completed if p.outcome == 'correct')
        accuracy = correct / total if total > 0 else 0.5
        
        # Recent accuracy (last 20 trades)
        recent = completed[-20:]
        recent_correct = sum(1 for p in recent if p.outcome == 'correct')
        recent_accuracy = recent_correct / len(recent) if recent else 0.5
        
        # Weighted accuracy
        weighted_acc = self.get_weighted_accuracy(agent_name)
        
        # Per-symbol breakdown
        by_symbol = defaultdict(lambda: {'correct': 0, 'total': 0})
        for pred in completed:
            by_symbol[pred.symbol]['total'] += 1
            if pred.outcome == 'correct':
                by_symbol[pred.symbol]['correct'] += 1
        
        symbol_metrics = {}
        for symbol, counts in by_symbol.items():
            symbol_metrics[symbol] = {
                'accuracy': counts['correct'] / counts['total'],
                'count': counts['total']
            }
        
        # Confidence calibration (are high-confidence predictions more accurate?)
        high_conf = [p for p in completed if p.confidence > 0.7]
        low_conf = [p for p in completed if p.confidence <= 0.7]
        
        high_conf_acc = (sum(1 for p in high_conf if p.outcome == 'correct') / len(high_conf)) if high_conf else 0.5
        low_conf_acc = (sum(1 for p in low_conf if p.outcome == 'correct') / len(low_conf)) if low_conf else 0.5
        
        return {
            'total_predictions': len(predictions),
            'completed_predictions': total,
            'correct': correct,
            'incorrect': total - correct,
            'accuracy': accuracy,
            'weighted_accuracy': weighted_acc,
            'recent_accuracy': recent_accuracy,
            'by_symbol': symbol_metrics,
            'confidence_calibration': {
                'high_confidence_accuracy': high_conf_acc,
                'low_confidence_accuracy': low_conf_acc,
                'is_calibrated': high_conf_acc > low_conf_acc
            }
        }
    
    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics structure"""
        return {
            'total_predictions': 0,
            'completed_predictions': 0,
            'correct': 0,
            'incorrect': 0,
            'accuracy': 0.5,
            'weighted_accuracy': 0.5,
            'recent_accuracy': 0.5,
            'by_symbol': {},
            'confidence_calibration': {
                'high_confidence_accuracy': 0.5,
                'low_confidence_accuracy': 0.5,
                'is_calibrated': False
            }
        }
    
    def get_summary(self) -> Dict[str, Dict]:
        """Get summary of all agent performance"""
        if self._cache_dirty:
            self._rebuild_metrics_cache()
        
        return {
            agent: {
                'accuracy': metrics['accuracy'],
                'recent_accuracy': metrics['recent_accuracy'],
                'total_trades': metrics['completed_predictions']
            }
            for agent, metrics in self._metrics_cache.items()
        }
    
    def save_to_file(self, filepath: str):
        """
        Save performance data to JSON file.
        
        Args:
            filepath: Path to save file
        """
        try:
            data = {
                'predictions': {
                    agent: [pred.to_dict() for pred in preds]
                    for agent, preds in self.predictions.items()
                },
                'saved_at': datetime.now().isoformat()
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Saved agent performance data to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save performance data: {e}")
    
    def load_from_file(self, filepath: str):
        """
        Load performance data from JSON file.
        
        Args:
            filepath: Path to load file
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.predictions = defaultdict(list)
            for agent, preds in data.get('predictions', {}).items():
                self.predictions[agent] = [AgentPrediction.from_dict(p) for p in preds]
            
            self._cache_dirty = True
            logger.info(f"Loaded agent performance data from {filepath}")
            
            # Log summary
            summary = self.get_summary()
            for agent, metrics in summary.items():
                logger.info(f"  {agent}: {metrics['accuracy']:.1%} accuracy ({metrics['total_trades']} trades)")
        
        except FileNotFoundError:
            logger.info(f"No existing performance data found at {filepath}")
        except Exception as e:
            logger.error(f"Failed to load performance data: {e}")
    
    @property
    def total_trades(self) -> int:
        """Get total number of completed trades across all agents"""
        total = 0
        for predictions in self.predictions.values():
            total += sum(1 for p in predictions if p.outcome is not None)
        return total // 3  # Divide by 3 since each trade has 3 agent predictions
