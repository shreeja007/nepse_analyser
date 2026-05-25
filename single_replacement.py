import concurrent.futures
import multiprocessing

def _process_single(symbol):
    try:
        from single_analyser.logic import analyze_single_stock
        data = analyze_single_stock(symbol, quiet=True)
        return symbol, data, None
    except Exception as e:
        return symbol, None, str(e)
