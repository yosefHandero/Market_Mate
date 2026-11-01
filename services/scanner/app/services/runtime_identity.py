"""Local startup diagnostics. Reads the saved pin without creating campaigns."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from app.config import Settings, get_settings
from app.services.brain_runtime import BrainRuntime
from app.services.evidence_campaign import EvidenceCampaignService


def build_runtime_identity(
    role: str, *, settings: Settings, runtime: BrainRuntime, campaign: Any,
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "role": role,
        "pid": os.getpid(),
        "executable": sys.executable,
        "python_prefix": sys.prefix,
        "working_directory": str(Path.cwd()),
        # Never log a connection URL that could contain credentials.
        "database": settings.database_path if settings.database_url.startswith("sqlite:///") else "non-sqlite",
        "verification_mode": settings.runtime_verification_mode,
        "execution_enabled": settings.execution_enabled,
        "allow_live_trading": settings.allow_live_trading,
        "runtime_policy_id": None,
        "runtime_policy_version": None,
        "runtime_decision_fingerprint": None,
        "learned_artifacts_fingerprint": None,
        "identity_matches_saved_campaign": None,
        "campaign_id": getattr(campaign, "campaign_id", None),
        "saved_policy_id": getattr(campaign, "effective_policy_id", None),
        "saved_policy_version": getattr(campaign, "effective_policy_version", None),
        "saved_decision_fingerprint": getattr(campaign, "effective_decision_fingerprint", None),
        "saved_learned_artifacts_fingerprint": getattr(campaign, "learned_artifacts_fingerprint", None),
    }
    # A diagnostic must not refresh learned state or fall back to latest inputs.
    pin = runtime.learned_inputs_service.load_active_campaign_pin()
    if pin is None:
        identity["learned_artifact_status"] = "no_saved_pin"
        identity["loaded_hybrid_version"] = runtime.hybrid.policy_version
        return identity
    runtime.refresh_weekly_inputs(pin)
    policy = runtime.registry.get(runtime.effective_champion_id())
    module = sys.modules.get(type(policy).__module__)
    identity.update(
        requested_policy_id=runtime.requested_champion_id(),
        runtime_policy_id=policy.policy_id,
        runtime_policy_version=policy.policy_version,
        runtime_decision_fingerprint=policy.fingerprint(),
        policy_module=type(policy).__module__,
        policy_module_path=getattr(module, "__file__", None),
        learned_artifact_status="saved_pin_verified",
        learned_artifacts_fingerprint=pin.fingerprint,
    )
    if all(identity[key] for key in ("saved_policy_id", "saved_policy_version", "saved_decision_fingerprint")):
        identity["identity_matches_saved_campaign"] = (
            identity["saved_policy_id"] == policy.policy_id
            and identity["saved_policy_version"] == policy.policy_version
            and identity["saved_decision_fingerprint"] == policy.fingerprint()
            and identity["saved_learned_artifacts_fingerprint"] == pin.fingerprint
        )
    return identity


def log_runtime_identity(role: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        identity = build_runtime_identity(
            role, settings=settings, runtime=BrainRuntime(settings=settings),
            campaign=EvidenceCampaignService(settings=settings).get_active_campaign(),
        )
    except Exception as exc:
        # Schema or corrupt-pin failures remain visible without leaking URL/token
        # values through exception messages. Startup/schema guards still apply.
        identity = {"role": role, "pid": os.getpid(), "identity_status": "unavailable", "error_type": type(exc).__name__}
    logging.getLogger(__name__).info(
        "startup runtime identity %s", json.dumps(identity, sort_keys=True),
        extra={"event": "startup_runtime_identity"},
    )
    return identity
