import time
import concurrent.futures
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

# Simulation Constants
SYMBOLS = ["AAPL", "GOOGL", "AMZN", "MSFT", "TSLA", "META", "NVDA", "NFLX", "AMD", "MDB"] # 10 Symbols
SIMULATED_LATENCY = 1.0 # 1 second per symbol (simulating API calls)

def mock_execute_strategy(symbol):
    """Simulates the bot analyzing a symbol (Network I/O)"""
    # logger.info(f"Analyzing {symbol}...")
    time.sleep(SIMULATED_LATENCY)
    # logger.info(f"Finished {symbol}.")

def run_sequential_test():
    logger.info(f"--- STARTING SEQUENTIAL TEST (Old Way) ---")
    logger.info(f"Processing {len(SYMBOLS)} symbols (Latency: {SIMULATED_LATENCY}s each)...")
    
    start_time = time.time()
    
    for symbol in SYMBOLS:
        mock_execute_strategy(symbol)
        
    end_time = time.time()
    duration = end_time - start_time
    logger.info(f"✅ Sequential Finished in: {duration:.4f} seconds")
    return duration

def run_parallel_test():
    logger.info(f"\n--- STARTING PARALLEL TEST (New Way) ---")
    logger.info(f"Processing {len(SYMBOLS)} symbols with 5 Workers...")
    
    start_time = time.time()
    
    # EXACT LOGIC ADDED TO V6/V7
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(mock_execute_strategy, symbol): symbol for symbol in SYMBOLS}
        for future in concurrent.futures.as_completed(futures):
            future.result()
            
    end_time = time.time()
    duration = end_time - start_time
    logger.info(f"✅ Parallel Finished in: {duration:.4f} seconds")
    return duration

if __name__ == "__main__":
    print(f"⏱️  BENCHMARKING BOT EFFICIENCY ⏱️\n")
    
    seq_time = run_sequential_test()
    par_time = run_parallel_test()
    
    speedup = seq_time / par_time
    
    print(f"\n📊 RESULTS:")
    print(f"Sequential Time: {seq_time:.2f}s")
    print(f"Parallel Time:   {par_time:.2f}s")
    print(f"🚀 Speed Improvement: {speedup:.1f}x FASTER")
