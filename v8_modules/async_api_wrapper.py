"""
Async API Wrapper Module
Wraps synchronous Alpaca API calls in async executors for concurrent execution
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Callable, Any
from functools import wraps

logger = logging.getLogger(__name__)


class AsyncAPIWrapper:
    """
    Wraps synchronous API calls to run concurrently using asyncio.
    
    Since alpaca-py's TradingClient REST methods are synchronous (blocking),
    this wrapper uses ThreadPoolExecutor to run them concurrently without
    blocking the event loop.
    
    Benefits:
    - Multiple API calls execute in parallel
    - 2-3x faster for batch operations
    - Non-blocking execution
    - Easy integration with existing sync code
    """
    
    def __init__(self, max_workers: int = 5):
        """
        Initialize AsyncAPIWrapper.
        
        Args:
            max_workers: Maximum number of concurrent API calls
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.loop = None
        logger.info(f"AsyncAPIWrapper initialized (max_workers: {max_workers})")
    
    async def run_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Run a synchronous function asynchronously.
        
        Args:
            func: Synchronous function to run
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))
    
    async def gather_api_calls(self, calls: List[tuple]) -> List[Any]:
        """
        Execute multiple API calls concurrently.
        
        Args:
            calls: List of (func, args, kwargs) tuples
            
        Returns:
            List of results in same order as calls
            
        Example:
            calls = [
                (client.get_account, (), {}),
                (client.get_all_positions, (), {}),
                (client.get_orders, (), {'filter': filter_req})
            ]
            results = await wrapper.gather_api_calls(calls)
        """
        tasks = []
        for call in calls:
            if len(call) == 3:
                func, args, kwargs = call
            elif len(call) == 2:
                func, args = call
                kwargs = {}
            else:
                func = call[0]
                args = ()
                kwargs = {}
            
            tasks.append(self.run_async(func, *args, **kwargs))
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    def run_concurrent(self, calls: List[tuple]) -> List[Any]:
        """
        Synchronous wrapper for gather_api_calls.
        
        Use this when you want concurrent execution but are in sync context.
        
        Args:
            calls: List of (func, args, kwargs) tuples
            
        Returns:
            List of results in same order as calls
        """
        return asyncio.run(self.gather_api_calls(calls))
    
    def shutdown(self):
        """Shutdown the executor"""
        self.executor.shutdown(wait=True)
        logger.info("AsyncAPIWrapper executor shutdown")


# Convenience functions for common patterns

async def fetch_multiple_positions(client, symbols: List[str]) -> List[Any]:
    """
    Fetch positions for multiple symbols concurrently.
    
    Args:
        client: TradingClient instance
        symbols: List of symbols to fetch
        
    Returns:
        List of position objects (or None if not found)
    """
    wrapper = AsyncAPIWrapper(max_workers=len(symbols))
    
    calls = []
    for symbol in symbols:
        calls.append((client.get_open_position, (symbol,), {}))
    
    results = await wrapper.gather_api_calls(calls)
    wrapper.shutdown()
    
    # Convert exceptions to None
    return [r if not isinstance(r, Exception) else None for r in results]


async def fetch_account_and_positions(client) -> tuple:
    """
    Fetch account info and all positions concurrently.
    
    Args:
        client: TradingClient instance
        
    Returns:
        Tuple of (account, positions)
    """
    wrapper = AsyncAPIWrapper(max_workers=2)
    
    calls = [
        (client.get_account, (), {}),
        (client.get_all_positions, (), {})
    ]
    
    results = await wrapper.gather_api_calls(calls)
    wrapper.shutdown()
    
    return results[0], results[1]


def run_concurrent_api_calls(calls: List[tuple]) -> List[Any]:
    """
    Convenience function to run multiple API calls concurrently from sync context.
    
    Args:
        calls: List of (func, args, kwargs) tuples
        
    Returns:
        List of results
        
    Example:
        results = run_concurrent_api_calls([
            (client.get_account, (), {}),
            (client.get_all_positions, (), {}),
        ])
        account, positions = results
    """
    wrapper = AsyncAPIWrapper()
    results = wrapper.run_concurrent(calls)
    wrapper.shutdown()
    return results
