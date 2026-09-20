"""Enforce the brain's import boundary.

The brain package must stay a pure decision core: no imports of the host
shell (services, api, models, clients, db, worker) and no I/O frameworks.
If this test fails, decision logic has grown a side-effect dependency and
must be refactored so the host adapts data in and results out.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

BRAIN_DIR = Path(__file__).resolve().parent.parent / "app" / "brain"

FORBIDDEN_PREFIXES = (
    "app.services",
    "app.api",
    "app.models",
    "app.clients",
    "app.db",
    "app.worker",
    "app.main",
    "app.core",  # host shell; the brain must not reach back into it
    "sqlalchemy",
    "alembic",
    "fastapi",
    "pydantic_settings",
    "httpx",
    "requests",
    "aiohttp",
)

# The brain may import these host modules: pure typed contracts and settings
# values (no I/O). Everything else under app.* is forbidden.
ALLOWED_APP_PREFIXES = ("app.brain", "app.schemas", "app.config")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


class BrainImportBoundaryTest(unittest.TestCase):
    def test_brain_package_exists(self) -> None:
        self.assertTrue(BRAIN_DIR.is_dir(), f"missing brain package at {BRAIN_DIR}")
        self.assertTrue((BRAIN_DIR / "__init__.py").is_file())

    def test_no_forbidden_imports(self) -> None:
        violations: list[str] = []
        for path in sorted(BRAIN_DIR.rglob("*.py")):
            for module in sorted(_imported_modules(path)):
                if any(
                    module == prefix or module.startswith(prefix + ".")
                    for prefix in FORBIDDEN_PREFIXES
                ):
                    violations.append(f"{path.relative_to(BRAIN_DIR)}: {module}")
                elif module == "app" or (
                    module.startswith("app.")
                    and not any(
                        module == prefix or module.startswith(prefix + ".")
                        for prefix in ALLOWED_APP_PREFIXES
                    )
                ):
                    violations.append(f"{path.relative_to(BRAIN_DIR)}: {module}")
        self.assertEqual(
            violations,
            [],
            "brain package imports host/I-O modules:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
