"""The API's promise to its clients (the dashboard and the phone app).

    python scripts/api_contract.py save      after a release: keep its copy
    python scripts/api_contract.py check     what tests/test_api_contract.py runs

``save`` writes ``docs/api/openapi-<version>.json``, the schema of the
version just released, and points ``docs/api/released.txt`` at it.
``check`` compares the current schema with that copy and lists what a
client would lose: a route (path and method) or a field of an answer that
is gone, unless the released copy had already marked it deprecated
(``deprecated: true``). Adding routes and fields is always fine.

To retire something: mark it deprecated (FastAPI's ``deprecated=True`` on a
route, ``Field(deprecated=True)`` on a field), release that, and remove it
in a later release. Note it under "API" in CHANGELOG.md either way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FOLDER = ROOT / "docs" / "api"
POINTER = FOLDER / "released.txt"
METHODS = ("get", "post", "put", "patch", "delete")


def current_schema() -> dict[str, Any]:
    from fastapi import FastAPI

    from agent import __version__
    from agent.api.routes import router

    app = FastAPI(title="Minecraft Server Control", version=__version__)
    app.include_router(router)
    return app.openapi()


def released_schema() -> tuple[str, dict[str, Any]] | None:
    if not POINTER.is_file():
        return None
    name = POINTER.read_text(encoding="utf-8").strip()
    return name, json.loads((FOLDER / name).read_text(encoding="utf-8"))


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    seen = 0
    while "$ref" in node and seen < 20:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = schema.get("components", {}).get("schemas", {}).get(name, {})
        seen += 1
    for key in ("anyOf", "oneOf", "allOf"):
        for option in node.get(key, []):
            resolved = _resolve(schema, option)
            if resolved.get("properties"):
                return resolved
    return node


def _fields(
    schema: dict[str, Any], node: dict[str, Any], prefix: str = "", depth: int = 0
) -> dict[str, bool]:
    """Every field path in an answer, with whether it is deprecated."""
    node = _resolve(schema, node)
    found: dict[str, bool] = {}
    if depth > 6:
        return found
    if node.get("type") == "array" and "items" in node:
        return _fields(schema, node["items"], prefix + "[]", depth + 1)
    for name, child in (node.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        found[path] = bool(child.get("deprecated"))
        found.update(_fields(schema, child, path, depth + 1))
    return found


def answers(schema: dict[str, Any]) -> dict[str, tuple[bool, dict[str, bool]]]:
    """{"GET /api/x": (deprecated, {field: deprecated})}"""
    out = {}
    for path, item in (schema.get("paths") or {}).items():
        for method in METHODS:
            operation = item.get(method)
            if not operation:
                continue
            content = (operation.get("responses", {}).get("200", {}).get("content") or {}).get(
                "application/json", {}
            )
            fields = _fields(schema, content.get("schema") or {})
            out[f"{method.upper()} {path}"] = (bool(operation.get("deprecated")), fields)
    return out


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What a client of ``old`` would lose with ``new``."""
    problems = []
    before, after = answers(old), answers(new)
    for route, (deprecated, fields) in sorted(before.items()):
        if route not in after:
            if not deprecated:
                problems.append(f"{route} was removed without being deprecated first")
            continue
        now = after[route][1]
        for field, field_deprecated in sorted(fields.items()):
            if field not in now and not field_deprecated and not deprecated:
                problems.append(f"{route}: the answer lost '{field}' without it being deprecated")
    return problems


def save() -> Path:
    from agent import __version__

    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / f"openapi-{__version__}.json"
    path.write_text(json.dumps(current_schema(), indent=1, sort_keys=True) + "\n", "utf-8")
    POINTER.write_text(path.name + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["save"]:
        print(f"saved {save().relative_to(ROOT)}")
        return 0
    if args == ["check"]:
        released = released_schema()
        if released is None:
            print("No released copy yet (docs/api/released.txt).")
            return 0
        problems = compare(released[1], current_schema())
        for problem in problems:
            print(problem)
        print(f"{len(problems)} problem(s) against {released[0]}")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
