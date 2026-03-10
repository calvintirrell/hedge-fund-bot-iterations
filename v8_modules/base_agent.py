"""
Base Agent Class - Agent Memory & State
Implements Week 2, Day 3-4 of pre-phase1-action-plan.md

Provides memory, learning, and performance tracking for all agents.
"""

from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Base class for all agents with memory and learning capabilities.
    
    Features:
    - Analysis history tracking (last N analyses)
    - Performance metrics per symbol
    - Overall accuracy tracking
    - Recent analysis retrieval
    """
    
    def __init__(self, memory_size: int = 100):
        """
        Initialize base agent with memory.
        
        Args:
            memory_size: Maximum number of analyses to remember
        """
        self.analysis_history = deque(maxlen=memory_size)
        self.performance_metrics: Dict[str, Dict[str, Any]] = {}
        self.overall_metrics = {
            'total_analyses': 0,
            'correct_predictions': 0,
            'incorrect_predictions': 0,
            'overall_accuracy': 0.0
        }
        logger.info(f"{self.__class__.__name__} initialized with memory_size={memory_size}")
    
    @abstractmethod
    def analyze(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze a symbol and return results.
        
        Each agent must implement this method.
        
        Args:
            symbol: Stock symbol to analyze
            
        Returns:
            Dictionary with analysis results including:
            - signal: 'BUY' or 'WAIT'
            - confidence: float (0.0-1.0)
            - reasoning: str
        """
        pass
    
    def record_analysis(self, symbol: str, result: Dict[str, Any]) -> None:
        """
        Track analysis in history.
        
        Args:
            symbol: Stock symbol analyzed
            result: Analysis result dictionary
        """
        self.analysis_history.append({
            'symbol': symbol,
            'timestamp': datetime.now(),
            'result': result.copy()
        })
        
        self.overall_metrics['total_analyses'] += 1
        
        logger.debug(f"{self.__class__.__name__}: Recorded analysis for {symbol}")
    
    def get_recent_analyses(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent analyses for a specific symbol.
        
        Args:
            symbol: Stock symbol to filter by
            limit: Maximum number of analyses to return
            
        Returns:
            List of recent analyses (most recent last)
        """
        symbol_analyses = [
            a for a in self.analysis_history 
            if a['symbol'] == symbol
        ]
        
        return symbol_analyses[-limit:]
    
    def get_last_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent analysis for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Most recent analysis or None if no history
        """
        recent = self.get_recent_analyses(symbol, limit=1)
        return recent[0] if recent else None
    
    def update_performance(self, symbol: str, outcome: str) -> None:
        """
        Track how well this agent's signals performed.
        
        Args:
            symbol: Stock symbol
            outcome: 'correct' or 'incorrect'
        """
        # Initialize metrics for symbol if needed
        if symbol not in self.performance_metrics:
            self.performance_metrics[symbol] = {
                'correct': 0,
                'incorrect': 0,
                'accuracy': 0.0,
                'total': 0
            }
        
        # Update symbol-specific metrics
        if outcome == 'correct':
            self.performance_metrics[symbol]['correct'] += 1
            self.overall_metrics['correct_predictions'] += 1
        else:
            self.performance_metrics[symbol]['incorrect'] += 1
            self.overall_metrics['incorrect_predictions'] += 1
        
        self.performance_metrics[symbol]['total'] += 1
        
        # Calculate accuracy
        total = self.performance_metrics[symbol]['total']
        correct = self.performance_metrics[symbol]['correct']
        self.performance_metrics[symbol]['accuracy'] = correct / total if total > 0 else 0.0
        
        # Update overall accuracy
        overall_total = (self.overall_metrics['correct_predictions'] + 
                        self.overall_metrics['incorrect_predictions'])
        if overall_total > 0:
            self.overall_metrics['overall_accuracy'] = (
                self.overall_metrics['correct_predictions'] / overall_total
            )
        
        logger.info(
            f"{self.__class__.__name__}: {symbol} accuracy: "
            f"{self.performance_metrics[symbol]['accuracy']:.2%} "
            f"({correct}/{total})"
        )
    
    def get_symbol_accuracy(self, symbol: str) -> float:
        """
        Get accuracy for a specific symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Accuracy (0.0-1.0) or 0.5 if no data
        """
        if symbol in self.performance_metrics:
            return self.performance_metrics[symbol]['accuracy']
        return 0.5  # Neutral if no history
    
    def get_overall_accuracy(self) -> float:
        """
        Get overall accuracy across all symbols.
        
        Returns:
            Overall accuracy (0.0-1.0) or 0.5 if no data
        """
        return self.overall_metrics.get('overall_accuracy', 0.5)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance summary.
        
        Returns:
            Dictionary with overall and per-symbol metrics
        """
        return {
            'overall': self.overall_metrics.copy(),
            'by_symbol': {
                symbol: metrics.copy()
                for symbol, metrics in self.performance_metrics.items()
            },
            'total_symbols_tracked': len(self.performance_metrics),
            'memory_usage': len(self.analysis_history)
        }
    
    def clear_history(self) -> None:
        """Clear analysis history (keeps performance metrics)."""
        self.analysis_history.clear()
        logger.info(f"{self.__class__.__name__}: Cleared analysis history")
    
    def reset_performance(self) -> None:
        """Reset all performance metrics."""
        self.performance_metrics.clear()
        self.overall_metrics = {
            'total_analyses': 0,
            'correct_predictions': 0,
            'incorrect_predictions': 0,
            'overall_accuracy': 0.0
        }
        logger.info(f"{self.__class__.__name__}: Reset performance metrics")
