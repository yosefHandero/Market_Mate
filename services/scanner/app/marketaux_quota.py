"""Inspect/recover Marketaux coordination without making provider requests.

From services/scanner: python -m app.marketaux_quota --help
Recovery requires the operator to verify availability or reset timing first.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from app.clients.marketaux import marketaux_account
from app.config import get_settings
from app.services.provider_coordination import ProviderCoordination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("status")
    recover = subcommands.add_parser("recover", help="After verifying account availability/reset with Marketaux")
    recover.add_argument("--reason", required=True)
    recover.add_argument("--verified-reset-at", help="Verified ISO timestamp with timezone; omit only if available now")
    ceiling = subcommands.add_parser("ceiling", help="Persistent shared remaining-attempt limit (counts every retry)")
    ceiling.add_argument("remaining", type=int, help="0 blocks sends; e.g. 3 permits at most three additional attempts")
    ceiling.add_argument("--reason", required=True)
    clear = subcommands.add_parser("clear-ceiling", help="Explicitly remove the operational ceiling")
    clear.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    settings = get_settings()
    store = ProviderCoordination(settings.cache_dir_path)
    account = marketaux_account(settings.marketaux_api_token)
    try:
        if args.command == "recover":
            reset = None
            if args.verified_reset_at:
                parsed = datetime.fromisoformat(args.verified_reset_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Verified reset timestamp must include a timezone")
                reset = parsed.timestamp()
                if reset <= datetime.now(timezone.utc).timestamp():
                    raise ValueError("Use a future verified reset time, or omit it after verifying availability now")
            store.recover(account, args.reason, verified_reset_at=reset)
        elif args.command == "ceiling":
            store.set_attempt_ceiling(account, args.remaining, args.reason)
        elif args.command == "clear-ceiling":
            store.set_attempt_ceiling(account, None, args.reason)
    except ValueError as exc:
        parser.error(str(exc))
    status = store.status(account)
    status["configured_daily_attempt_budget"] = settings.marketaux_daily_attempt_budget
    status["account_daily_allowance"] = "unknown (verify with Marketaux; local cap is not account usage)"
    status["cache_directory"] = str(settings.cache_dir_path)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
