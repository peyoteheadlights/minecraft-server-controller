"""The API's promise to clients: nothing a released version answered
disappears without being deprecated first, and every new route says what it
answers (scripts/api_contract.py, agent/api/responses.py)."""

from __future__ import annotations

from pathlib import Path

from agent.api.routes import api_routes
from scripts import api_contract

UNTYPED = Path(__file__).with_name("api_untyped_routes.txt")
PHONE_ROUTES = (
    "GET /api/servers",
    "GET /api/servers/{server_id}/status",
    "GET /api/servers/{server_id}/players",
    "POST /api/servers/{server_id}/server/start",
    "POST /api/servers/{server_id}/server/stop",
    "POST /api/servers/{server_id}/server/restart",
    "GET /api/servers/{server_id}/backups",
    "GET /api/servers/{server_id}/recommendations",
    "GET /api/notifications/history",
    "GET /api/jobs",
    "GET /api/jobs/{job_id}",
    "GET /api/health",
    "GET /api/version",
    "GET /api/pairing",
    "GET /api/sessions",
)


def routes() -> dict[str, object]:
    return {
        f"{sorted(route.methods)[0]} {path}": route
        for path, route, scope in api_routes()
        if scope != "alias"
    }


def listed_untyped() -> set[str]:
    lines = UNTYPED.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_nothing_released_was_removed_without_a_deprecation():
    released = api_contract.released_schema()
    assert released is not None, "docs/api/released.txt names the last release's copy"
    problems = api_contract.compare(released[1], api_contract.current_schema())
    assert not problems, "\n".join(problems)


def test_every_new_route_says_what_it_answers():
    untyped = listed_untyped()
    missing = sorted(name for name, route in routes().items() if route.response_model is None)
    new = [name for name in missing if name not in untyped]
    assert not new, (
        "these routes answer without a response model; add one in agent/api/responses.py: "
        + ", ".join(new)
    )


def test_the_untyped_list_only_shrinks():
    current = routes()
    stale = sorted(
        name for name in listed_untyped() if name not in current or current[name].response_model
    )
    assert not stale, "remove these lines from tests/api_untyped_routes.txt: " + ", ".join(stale)


def test_the_routes_a_phone_uses_are_typed():
    current = routes()
    for name in PHONE_ROUTES:
        assert name in current, name
        assert current[name].response_model is not None, name


def test_the_check_catches_a_removed_route_and_field():
    old = {
        "paths": {
            "/api/a": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "properties": {
                                            "kept": {},
                                            "gone": {},
                                            "old": {"deprecated": True},
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/b": {"get": {"responses": {}}},
            "/api/c": {"get": {"deprecated": True, "responses": {}}},
        }
    }
    new = {
        "paths": {
            "/api/a": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"properties": {"kept": {}, "added": {}}}
                                }
                            }
                        }
                    }
                }
            },
        }
    }
    problems = api_contract.compare(old, new)
    assert problems == [
        "GET /api/a: the answer lost 'gone' without it being deprecated",
        "GET /api/b was removed without being deprecated first",
    ]


def test_answers_keep_fields_their_model_doesnt_list(multi_client):
    """Response models are open: a route's extra fields still arrive."""
    status = multi_client.get("/api/servers/survival/status").json()
    assert "game_port" in status and "agent" in status  # not listed in ServerStatus
