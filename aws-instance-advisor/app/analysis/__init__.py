"""
Deterministic analysis helpers.

Everything in this package is plain Python over data the pipeline has
already produced.  Nothing here makes an LLM call, fetches live data, or
depends on wall-clock/random state — the same inputs always yield the same
output, which makes every rule exhaustively unit-testable.
"""

from app.analysis.well_architected import build_well_architected_review

__all__ = ["build_well_architected_review"]
