"""The decision brain: contracts, evaluation ruler, and decision policies.

This package is the protected decision-making core of the scanner. It contains
pure functions over passed-in data only. It must never import from
``app.services``, ``app.api``, ``app.models``, ``app.clients``, ``app.db``, or
any I/O framework (SQLAlchemy, FastAPI, HTTP clients). The host shell adapts
providers/ORM rows into brain inputs and persists brain outputs.

See ``BRAIN.md`` in this package for the full contract, including the
champion/challenger policy model, the two-identity rule (decision fingerprint
vs ruler version), and the production rule that the champion may only consume
ruler-validated inputs.
"""

from app.brain.identity import (
    BRAIN_PACKAGE_VERSION,
    RULER_VERSION,
    decision_fingerprint,
    ruler_fingerprint,
)

__all__ = [
    "BRAIN_PACKAGE_VERSION",
    "RULER_VERSION",
    "decision_fingerprint",
    "ruler_fingerprint",
]
