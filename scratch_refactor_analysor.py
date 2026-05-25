import os
import re

logic_path = r"c:\Users\ShreejaManandhar\Desktop\Nepse_scrape\NepseAPI-Unofficial_Vscode\analysor\logic.py"

with open(logic_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add multiprocessing import at the top
if "import multiprocessing" not in content:
    import_idx = content.find("import ")
    content = content[:import_idx] + "import concurrent.futures\nimport multiprocessing\n" + content[import_idx:]

# 2. Add top-level worker initialization
worker_init_code = """
_worker_state = {}

def _init_worker(corps, divs, details, securities, snapshots, broker_scores, sell_dist, regime, live_ltp):
    global _worker_state
    _worker_state['corps'] = corps
    _worker_state['divs'] = divs
    _worker_state['details'] = details
    _worker_state['securities'] = securities
    _worker_state['snapshots'] = snapshots
    _worker_state['broker_scores'] = broker_scores
    _worker_state['sell_dist'] = sell_dist
    _worker_state['regime'] = regime
    _worker_state['live_ltp'] = live_ltp

def _process_single_symbol(sym, raw_candles):
    global _worker_state
    all_corps = _worker_state['corps']
    all_divs = _worker_state['divs']
    all_details = _worker_state['details']
    all_securities = _worker_state['securities']
    all_52w_snapshots = _worker_state['snapshots']
    broker_scores = _worker_state['broker_scores']
    sell_distribution = _worker_state['sell_dist']
    market_regime = _worker_state['regime']
    all_live_ltp = _worker_state['live_ltp']
    
    skip_stats = {"short_history": 0, "bad_price": 0, "stale_forward_fill": 0}
"""

# Extract the body of analyze_all_symbols
# It starts around def analyze_all_symbols(...) and ends at return results
# Let's find the loop `for sym, raw_candles in all_ohlcv.items():`
loop_match = re.search(r"(\s*)for sym, raw_candles in all_ohlcv\.items\(\):\n", content)
if not loop_match:
    print("Loop not found")
    exit(1)

indent = loop_match.group(1)
loop_start = loop_match.end()

# Find the end of the loop (the 'if error_count:' line after the loop)
end_match = re.search(r"\n" + indent + r"if error_count:\n", content[loop_start:])
loop_end = loop_start + end_match.start()

loop_body = content[loop_start:loop_end]

# Dedent the loop body by one level (4 spaces)
dedented_body = ""
for line in loop_body.splitlines(True):
    if line.startswith(indent + "    "):
        dedented_body += line[len(indent)+4:]
    else:
        dedented_body += line

# Add return statement to the body
dedented_body = dedented_body.replace("continue", "return None, skip_stats")
# Instead of storing in `results[sym] = ...`, we return the result
dedented_body = re.sub(r"results\[sym\] = \{(.*?)\n\s*\}", r"return {\1\n    }, skip_stats", dedented_body, flags=re.DOTALL)
# Actually it's easier to just append a return at the end of the try block if it reaches it
# Wait, replacing `results[sym] = ` is safer
dedented_body = dedented_body.replace("results[sym] =", "return")
# But we need to return `skip_stats` too if we want to keep tracking skips?
# Skip stats are just printed, maybe we can just ignore them for the parallel version or return them
# Let's just return the result and skip_stats

# Let's modify the dedented body to just return the dict, and in the except block return None
except_pattern = re.search(r"except Exception as e:.*?(?=\n\S)", dedented_body, re.DOTALL)
if except_pattern:
    dedented_body = dedented_body[:except_pattern.start()] + "except Exception as e:\n        return None, {'error': f'{sym}:{type(e).__name__}'}"
else:
    # Just in case
    pass

# We also need to fix `continue` to `return None, skip_stats`
dedented_body = dedented_body.replace("continue", "return None, skip_stats")

# Replace `return { ... }` with `return { ... }, skip_stats`
dedented_body = re.sub(r"(return \{[^}]+\})", r"\1, skip_stats", dedented_body)


# Construct the new process_single_symbol function
process_fn = worker_init_code + "\n" + dedented_body + "\n"

# Rewrite analyze_all_symbols
new_analyze = """
def analyze_all_symbols(all_ohlcv, all_corps, all_divs, all_details, all_securities,
                        all_52w_snapshots, broker_scores,
                        sell_distribution, market_regime, all_live_ltp=None):
    print("  [2] Analyzing all symbols (indicators, patterns, flags)...")

    if all_live_ltp is None:
        all_live_ltp = {}

    results = {}
    error_count = 0
    error_samples = []
    skip_stats_total = {
        "short_history": 0,
        "bad_price": 0,
        "stale_forward_fill": 0,
    }

    max_workers = multiprocessing.cpu_count()
    init_args = (all_corps, all_divs, all_details, all_securities, all_52w_snapshots, broker_scores, sell_distribution, market_regime, all_live_ltp)
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker, initargs=init_args) as executor:
        futures = {
            executor.submit(_process_single_symbol, sym, raw_candles): sym
            for sym, raw_candles in all_ohlcv.items()
        }
        
        for future in concurrent.futures.as_completed(futures):
            sym = futures[future]
            try:
                res, skips = future.result()
                if skips:
                    if 'error' in skips:
                        error_count += 1
                        if len(error_samples) < 5:
                            error_samples.append(skips['error'])
                    else:
                        for k, v in skips.items():
                            skip_stats_total[k] += v
                if res:
                    results[sym] = res
            except Exception as e:
                error_count += 1
                if len(error_samples) < 5:
                    error_samples.append(f"{sym}:{type(e).__name__}")

    if error_count:
        sample_text = ", ".join(error_samples)
        print(f"  ⚠ symbol analysis errors: {error_count} ({sample_text})")

    skipped_total = sum(v for k,v in skip_stats_total.items() if k != 'error')
    if skipped_total:
        print(
            "  ⚠ symbol skip summary: "
            f"short_history={skip_stats_total['short_history']}, "
            f"stale_forward_fill={skip_stats_total['stale_forward_fill']}, "
            f"bad_price={skip_stats_total['bad_price']}"
        )

    return results
"""

# Replace in content
start_idx = content.find("def analyze_all_symbols(")
end_idx = content.find("def _build_reasons(", start_idx)

# Find where to put the new functions (before analyze_all_symbols)
content = content[:start_idx] + process_fn + "\n" + new_analyze + "\n\n" + content[end_idx:]

with open(logic_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Refactoring complete.")
