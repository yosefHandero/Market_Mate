"""Two separate identities: decision fingerprints and the ruler version.

Decision identity
    A per-policy fingerprint over everything that can affect *produced
    decisions*: policy id, policy code version, and the full policy config
    payload (which includes feature versions and decision-relevant data-source
    semantics). Stamped on every prediction. Only a decision-identity change
    may rotate prediction evidence campaigns.

Ruler identity
    ``RULER_VERSION`` plus the ruler config payload describes *how stored
    evidence is judged* (outcome derivations, win/Brier/metric definitions,
    benchmark construction, verdict and promotion gates). It is stamped on
    evaluation outputs (walk-forward runs, promotion reports, proof summaries)
    alongside the decision fingerprints of the evidence being judged. Ruler
    changes never rotate prediction campaigns: raw outcomes are canonical, so
    re-judging is reinterpretation, not a new brain.

Classification rule: a constant that flows into decision production belongs to
decision identity; a constant that only judges stored evidence belongs to
ruler identity.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

# Bump on structural changes to the brain package/contracts themselves.
BRAIN_PACKAGE_VERSION = "brain-v1"

# Bump whenever how evidence is judged changes in a way that makes previously
# computed evaluation reports incomparable (not the evidence itself).
RULER_VERSION = "ruler-v2"


def _canonical_payload(value: Any) -> Any:
    if is_dataclass(value):
        return _canonical_payload(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(_canonical_payload(payload), sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable_content_hash(payload: Any) -> str:
    """Deterministic content identity for learned artifacts."""
    return _stable_hash({"kind": "content", "content": payload})


def learned_artifact_identity(
    *,
    artifact_type: str,
    content_payload: Any,
    reference_payload: Any | None = None,
) -> dict[str, Any]:
    """Content identity plus an auditable, non-identity source reference."""
    content = _canonical_payload(content_payload)
    return {
        "artifact_type": artifact_type,
        "content_hash": stable_content_hash(
            {"artifact_type": artifact_type, "content": content}
        ),
        "content": content,
        "reference": _canonical_payload(reference_payload or {}),
    }


def decision_fingerprint(
    *,
    policy_id: str,
    policy_version: str,
    config_payload: dict[str, Any],
    learned_artifacts: dict[str, Any] | None = None,
) -> str:
    """Stable identity of a decision policy: what produced the predictions."""
    payload: dict[str, Any] = {
        "kind": "decision",
        "brain_package_version": BRAIN_PACKAGE_VERSION,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "config": config_payload,
    }
    if learned_artifacts is not None:
        payload["learned_artifacts"] = learned_artifacts
    return _stable_hash(payload)


def ruler_fingerprint(
    *,
    config_payload: dict[str, Any],
    ruler_version: str = RULER_VERSION,
) -> str:
    """Stable identity of the evaluation ruler: how evidence is judged."""
    return _stable_hash(
        {
            "kind": "ruler",
            "ruler_version": ruler_version,
            "config": config_payload,
        }
    )
