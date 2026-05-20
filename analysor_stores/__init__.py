"""
analysor_stores — Analysis result persistence & accuracy tracking.

Public API:
    from analysor_stores import save_full_analysis
    from analysor_stores import save_single_analysis
    from analysor_stores import save_batch_single_analysis

Run evaluator:
    python -m analysor_stores.evaluator

Run accuracy reporter:
    python -m analysor_stores.reporter
"""

from analysor_stores.store import (
    save_full_analysis,
    save_single_analysis,
    save_batch_single_analysis,
)

__all__ = [
    "save_full_analysis",
    "save_single_analysis",
    "save_batch_single_analysis",
]
