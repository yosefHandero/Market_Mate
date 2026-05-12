from __future__ import annotations

import argparse
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


SCANNER_ROOT = Path(__file__).resolve().parents[1]
if str(SCANNER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCANNER_ROOT))


class RepairRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class RepairResult:
    target_path: Path
    backup_path: Path | None
    alembic_ran: bool
    residual_patches: list[str]
    schema_before_ok: bool
    schema_before_missing: list[str]
    schema_after_ok: bool
    schema_after_missing: list[str]
    dry_run: bool


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually repair a local SQLite scanner schema after creating a backup.",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLite URL for the database to repair, for example sqlite:///path/to/scanner.db.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup, run Alembic upgrade head, then run residual schema repair.",
    )
    parser.add_argument(
        "--yes-repair",
        action="store_true",
        help="Alias for --apply. Required for any mutating repair.",
    )
    parser.add_argument(
        "--allow-production-sqlite-repair",
        action="store_true",
        help="Explicitly allow this local SQLite repair when APP_ENV=production.",
    )
    return parser.parse_args(argv)


def _sqlite_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise RepairRefused("Refusing repair: only sqlite:/// database URLs are supported.")

    try:
        url = make_url(database_url)
    except Exception as exc:
        raise RepairRefused(f"Refusing repair: invalid SQLite database URL: {exc}") from exc

    database = url.database
    if not database or database == ":memory:":
        raise RepairRefused("Refusing repair: a file-backed SQLite database is required.")

    return Path(database).expanduser().resolve()


def _sqlite_url_for_path(database_path: Path) -> str:
    return f"sqlite:///{database_path.as_posix()}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _create_backup(database_path: Path) -> Path:
    backup_path = database_path.with_name(f"{database_path.name}.{_timestamp()}.bak")
    shutil.copy2(database_path, backup_path)
    return backup_path


def _alembic_config(database_url: str) -> Config:
    config = Config(str(SCANNER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SCANNER_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@contextmanager
def _temporary_env_var(name: str, value: str | None) -> Iterator[None]:
    previous = os.environ.get(name)
    had_previous = name in os.environ
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if had_previous:
            os.environ[name] = previous or ""
        else:
            os.environ.pop(name, None)


@contextmanager
def _db_module_bound_to(database_url: str) -> Iterator[object]:
    import app.db as db_module
    import app.models.system  # noqa: F401

    target_engine = create_engine(
        database_url,
        future=True,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    previous_engine: Engine = db_module.engine
    db_module.engine = target_engine
    try:
        yield db_module
    finally:
        db_module.engine = previous_engine
        target_engine.dispose()


@contextmanager
def _settings_import_env(production_override: bool) -> Iterator[None]:
    if production_override:
        with _temporary_env_var("APP_ENV", "development"):
            yield
        return
    yield


def _status_payload(status: object) -> tuple[bool, list[str]]:
    return bool(status.ok), list(status.missing_items)


def _run_repair(database_url: str, *, apply: bool, production_override: bool) -> RepairResult:
    database_path = _sqlite_path_from_url(database_url)
    normalized_database_url = _sqlite_url_for_path(database_path)

    if not database_path.exists():
        raise RepairRefused(f"Refusing repair: SQLite database file does not exist: {database_path}")
    if not database_path.is_file():
        raise RepairRefused(f"Refusing repair: SQLite database path is not a file: {database_path}")

    with _settings_import_env(production_override):
        with _db_module_bound_to(normalized_database_url) as db_module:
            before_ok, before_missing = _status_payload(db_module.get_schema_status())

            if not apply:
                return RepairResult(
                    target_path=database_path,
                    backup_path=None,
                    alembic_ran=False,
                    residual_patches=[],
                    schema_before_ok=before_ok,
                    schema_before_missing=before_missing,
                    schema_after_ok=before_ok,
                    schema_after_missing=before_missing,
                    dry_run=True,
                )

            backup_path = _create_backup(database_path)
            command.upgrade(_alembic_config(normalized_database_url), "head")

            repair_env_name = db_module.SCANNER_SCHEMA_REPAIR_ALLOW_ENV
            with _temporary_env_var(repair_env_name, "1"):
                residual_patches = db_module.apply_required_schema_patches()

            after_status = db_module.get_schema_status(applied_changes=residual_patches)
            after_ok, after_missing = _status_payload(after_status)

            return RepairResult(
                target_path=database_path,
                backup_path=backup_path,
                alembic_ran=True,
                residual_patches=residual_patches,
                schema_before_ok=before_ok,
                schema_before_missing=before_missing,
                schema_after_ok=after_ok,
                schema_after_missing=after_missing,
                dry_run=False,
            )


def _format_missing(missing_items: list[str]) -> str:
    if not missing_items:
        return "none"
    return ", ".join(missing_items)


def _print_summary(result: RepairResult) -> None:
    mode = "dry-run" if result.dry_run else "apply"
    print("Schema repair summary")
    print(f"Mode: {mode}")
    print(f"Target DB path: {result.target_path}")
    if result.backup_path is None:
        print("Backup path: not created")
    else:
        print(f"Backup path: {result.backup_path}")
    print(f"Alembic upgrade head run: {'yes' if result.alembic_ran else 'no'}")
    if result.residual_patches:
        print(f"Residual patches applied: {', '.join(result.residual_patches)}")
    else:
        print("Residual patches applied: none")
    print(
        "Schema before: "
        f"{'OK' if result.schema_before_ok else 'MISSING'} "
        f"({ _format_missing(result.schema_before_missing) })"
    )
    print(
        "Schema after: "
        f"{'OK' if result.schema_after_ok else 'MISSING'} "
        f"({ _format_missing(result.schema_after_missing) })"
    )
    if result.dry_run:
        print("Dry run only: no backup, Alembic upgrade, or residual repair was run.")
        print("Would repair with --apply or --yes-repair: create backup, run Alembic upgrade head, then run residual patches.")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    apply = bool(args.apply or args.yes_repair)
    app_env = os.environ.get("APP_ENV", "")

    try:
        if app_env.lower() == "production" and not args.allow_production_sqlite_repair:
            raise RepairRefused(
                "Refusing repair: APP_ENV=production. Pass "
                "--allow-production-sqlite-repair only for an explicit local SQLite repair."
            )

        result = _run_repair(
            args.database_url,
            apply=apply,
            production_override=app_env.lower() == "production",
        )
        _print_summary(result)

        if result.dry_run:
            return 0
        if not result.schema_after_ok:
            print("Repair failed: final schema status is not OK.", file=sys.stderr)
            return 1
        return 0
    except RepairRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Repair failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
