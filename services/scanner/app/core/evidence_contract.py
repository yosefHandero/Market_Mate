"""One shared evidence contract for the whole application.

Every number the backend serves and the frontend renders about strategy
performance belongs to exactly one of these six canonical evidence tracks.
This module is the single source of truth for the track vocabulary and for the
mapping from the older stored ``sample_source`` / walk-forward ``track`` strings
onto that vocabulary. It is a pure mapping layer: it changes no stored data and
runs no migration, so historical rows keep their original strings and are simply
re-labelled on read.

Honesty rule: only ``live_forward`` and ``real_money_pilot`` are forward,
untouched evidence that can graduate toward a real-money pilot. Everything else
is historical or execution-path evidence and must never be presented as proof of
real-money readiness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


# Canonical, ordered track keys. The order is the display order.
WALK_FORWARD_RESEARCH = "walk_forward_research"
WALK_FORWARD_HOLDOUT = "walk_forward_holdout"
HISTORICAL_REPLAY = "historical_replay"
PAPER_EXECUTION = "paper_execution"
LIVE_FORWARD = "live_forward"
REAL_MONEY_PILOT = "real_money_pilot"

EVIDENCE_TRACK_KEYS: tuple[str, ...] = (
    WALK_FORWARD_RESEARCH,
    WALK_FORWARD_HOLDOUT,
    HISTORICAL_REPLAY,
    PAPER_EXECUTION,
    LIVE_FORWARD,
    REAL_MONEY_PILOT,
)


@dataclass(frozen=True)
class EvidenceTrackDescriptor:
    key: str
    label: str
    description: str
    # is_forward: collected forward in real time with no hindsight.
    is_forward: bool
    # counts_toward_real_money: may be used as graduation evidence for a pilot.
    counts_toward_real_money: bool


EVIDENCE_TRACKS: tuple[EvidenceTrackDescriptor, ...] = (
    EvidenceTrackDescriptor(
        key=WALK_FORWARD_RESEARCH,
        label="Walk-forward research",
        description=(
            "Historical walk-forward predictions in the research segment used to "
            "design, tune, and calibrate the strategy. In-sample for tuning; not "
            "real-money evidence."
        ),
        is_forward=False,
        counts_toward_real_money=False,
    ),
    EvidenceTrackDescriptor(
        key=WALK_FORWARD_HOLDOUT,
        label="Walk-forward holdout",
        description=(
            "Historical walk-forward predictions in the final held-out segment "
            "that was never used for tuning. The strongest historical evidence, "
            "but still not forward-collected."
        ),
        is_forward=False,
        counts_toward_real_money=False,
    ),
    EvidenceTrackDescriptor(
        key=HISTORICAL_REPLAY,
        label="Historical replay",
        description=(
            "Backfilled replay of the strategy over past bars. Historical; not "
            "collected forward in real time."
        ),
        is_forward=False,
        counts_toward_real_money=False,
    ),
    EvidenceTrackDescriptor(
        key=PAPER_EXECUTION,
        label="Paper execution",
        description=(
            "Dry-run paper orders and the simulated paper ledger. Confirms the "
            "execution and tracking path works; not evidence of predictive edge."
        ),
        is_forward=True,
        counts_toward_real_money=False,
    ),
    EvidenceTrackDescriptor(
        key=LIVE_FORWARD,
        label="Live-forward",
        description=(
            "Predictions recorded live at scan time and resolved later with no "
            "hindsight. The only track that can accumulate toward a real-money "
            "pilot decision."
        ),
        is_forward=True,
        counts_toward_real_money=True,
    ),
    EvidenceTrackDescriptor(
        key=REAL_MONEY_PILOT,
        label="Real-money pilot",
        description=(
            "Future, manually placed real-money pilot trades. None exist: this "
            "build is paper-only and places no broker orders."
        ),
        is_forward=True,
        counts_toward_real_money=True,
    ),
)


# Mapping from the legacy stored sample_source taxonomy onto canonical tracks.
# out_of_sample is a held-out subset of live-forward data, so it maps to
# live_forward (the UI may still show its sub-count separately).
_SAMPLE_SOURCE_TRACK = {
    "historical": WALK_FORWARD_RESEARCH,
    "backfilled_replay": HISTORICAL_REPLAY,
    "live_paper_forward": LIVE_FORWARD,
    "out_of_sample": LIVE_FORWARD,
}

# Mapping from the walk-forward metric track strings onto canonical tracks.
# "validation" is the tuning-side segment between research and holdout; it
# shares the research contract track (not forward-collected, not holdout).
_WALK_FORWARD_TRACK = {
    "research": WALK_FORWARD_RESEARCH,
    "validation": WALK_FORWARD_RESEARCH,
    "holdout": WALK_FORWARD_HOLDOUT,
}


def track_for_sample_source(sample_source: str | None) -> str | None:
    """Return the canonical evidence track for a stored sample_source string."""
    return _SAMPLE_SOURCE_TRACK.get(str(sample_source or "").strip())


def track_for_walk_forward_track(track: str | None) -> str | None:
    """Return the canonical evidence track for a walk-forward metric track string."""
    return _WALK_FORWARD_TRACK.get(str(track or "").strip())


def evidence_track_manifest() -> list[dict[str, object]]:
    """Serialisable list of every canonical track descriptor, in display order."""
    return [asdict(track) for track in EVIDENCE_TRACKS]
