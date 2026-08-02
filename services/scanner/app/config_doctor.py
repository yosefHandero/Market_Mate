from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import SCANNER_ROOT, Settings


PLACEHOLDER_PATTERNS = (
    re.compile(r"your[-_ ]?email", re.I),
    re.compile(r"example\.com", re.I),
    re.compile(r"changeme", re.I),
    re.compile(r"placeholder", re.I),
    re.compile(r"^xxx+$", re.I),
)

def _settings_env_keys() -> set[str]:
    keys: set[str] = set()
    for name, field in Settings.model_fields.items():
        keys.add(name)
        keys.add(name.upper())
        validation_alias = field.validation_alias
        if isinstance(validation_alias, str):
            keys.add(validation_alias)
        for choice in getattr(validation_alias, "choices", []) or []:
            if isinstance(choice, str):
                keys.add(choice)
    return keys


KNOWN_LEGACY_ENV_KEYS = {
    "LIVE_TRADING_MAX_NOTIONAL",
    "LIVE_TRADING_MAX_QTY",
    "NEWS_CHECK_SCORE_THRESHOLD",
}

KNOWN_SETTINGS_KEYS = _settings_env_keys() | KNOWN_LEGACY_ENV_KEYS | {
    "MARKETDATA_API_TOKEN",
    "MarketData_API_token",
    "READ_API_TOKEN",
    "ADMIN_API_TOKEN",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "POLYGON_API_KEY",
    "DATABASE_URL",
}

UNUSED_ENV_KEYS = {
    "GEMMA_API_KEY",
    "LIVE_TRADING_MAX_NOTIONAL",
    "LIVE_TRADING_MAX_QTY",
    "NEWS_CHECK_SCORE_THRESHOLD",
}


@dataclass(frozen=True)
class EnvKeyReport:
    key: str
    status: str
    occurrences: int
    note: str = ""


@dataclass(frozen=True)
class ConfigDoctorReport:
    files_checked: list[str]
    keys: list[EnvKeyReport]
    duplicate_keys: list[str]
    unused_keys: list[str]
    likely_misconfigured: list[str]


def _mask_value(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "blank"
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(stripped):
            return "placeholder"
    return "present"


def _parse_env_file(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        entries.append((key.strip(), value.strip()))
    return entries


def diagnose_env_file(path: Path) -> ConfigDoctorReport:
    entries = _parse_env_file(path)
    by_key: dict[str, list[str]] = {}
    for key, value in entries:
        by_key.setdefault(key, []).append(value)

    keys: list[EnvKeyReport] = []
    duplicate_keys: list[str] = []
    unused_keys: list[str] = []
    likely_misconfigured: list[str] = []

    for key, values in sorted(by_key.items()):
        statuses = {_mask_value(value) for value in values}
        if len(values) > 1:
            duplicate_keys.append(key)
            status = "duplicate"
            if "present" in statuses and "blank" in statuses:
                status = "duplicate / likely misconfigured"
                likely_misconfigured.append(key)
        elif "blank" in statuses:
            status = "blank"
        elif "placeholder" in statuses:
            status = "placeholder"
            likely_misconfigured.append(key)
        else:
            status = "present"
        if key in UNUSED_ENV_KEYS:
            unused_keys.append(key)
            status = f"{status} / unused"
        if key not in KNOWN_SETTINGS_KEYS and not key.startswith("NEXT_PUBLIC_"):
            status = f"{status} / unknown_to_scanner"
        keys.append(EnvKeyReport(key=key, status=status, occurrences=len(values)))

    return ConfigDoctorReport(
        files_checked=[str(path)],
        keys=keys,
        duplicate_keys=duplicate_keys,
        unused_keys=unused_keys,
        likely_misconfigured=likely_misconfigured,
    )


def diagnose_scanner_env() -> ConfigDoctorReport:
    return diagnose_env_file(SCANNER_ROOT / ".env")


def format_report(report: ConfigDoctorReport) -> str:
    lines = ["Config doctor report (masked; no secret values)", ""]
    lines.append("Files checked:")
    for path in report.files_checked:
        lines.append(f"- {path}")
    lines.append("")
    lines.append("Keys:")
    for item in report.keys:
        suffix = f" ({item.note})" if item.note else ""
        lines.append(f"- {item.key}: {item.status} x{item.occurrences}{suffix}")
    if report.duplicate_keys:
        lines.append("")
        lines.append("Duplicate keys:")
        for key in report.duplicate_keys:
            lines.append(f"- {key}")
    if report.unused_keys:
        lines.append("")
        lines.append("Unused keys:")
        for key in report.unused_keys:
            lines.append(f"- {key}")
    if report.likely_misconfigured:
        lines.append("")
        lines.append("Likely misconfigured:")
        for key in report.likely_misconfigured:
            lines.append(f"- {key}")
    return "\n".join(lines)


def main() -> None:
    report = diagnose_scanner_env()
    print(format_report(report))


if __name__ == "__main__":
    main()
