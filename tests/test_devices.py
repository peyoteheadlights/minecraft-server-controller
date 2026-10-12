"""Signed-in devices: each sign-in is listed with its device name and when
it was last used, can be signed out on its own, and "Keep me signed in on
this device" gives a longer sign-in that each use renews."""

from __future__ import annotations

import time

from .conftest import PASSWORD
from .test_helpers import HELPER_PASSWORD, add_helper


def sign_in(client, username="admin", password=PASSWORD, **extra):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json(), {"Authorization": f"Bearer {response.json()['token']}"}


def test_each_sign_in_is_listed_with_its_device_name(multi_client):
    _, phone = sign_in(multi_client, device="Mark's phone", remember=True)
    rows = multi_client.get("/api/sessions", headers=phone).json()["sessions"]
    mine = [r for r in rows if r["current"]]
    assert len(mine) == 1
    assert mine[0]["label"] == "Mark's phone"
    assert mine[0]["remember"] is True
    assert mine[0]["last_used"] is not None
    assert len(rows) >= 2  # the test client's own sign-in too
    for row in rows:
        assert "token" not in row and "token_hash" not in row
        assert len(row["id"]) == 16


def test_signing_out_one_device_ends_it_at_once(multi_client):
    _, phone = sign_in(multi_client, device="Phone")
    _, laptop = sign_in(multi_client, device="Laptop")
    rows = multi_client.get("/api/sessions", headers=laptop).json()["sessions"]
    phone_id = next(r["id"] for r in rows if r["label"] == "Phone")
    assert multi_client.delete(f"/api/sessions/{phone_id}", headers=laptop).status_code == 200
    assert multi_client.get("/api/servers", headers=phone).status_code == 401
    assert multi_client.get("/api/servers", headers=laptop).status_code == 200
    assert multi_client.delete(f"/api/sessions/{phone_id}", headers=laptop).status_code == 404


def test_keep_me_signed_in_lasts_longer_and_renews(multi_client):
    core = multi_client.app.state.core
    short, _ = sign_in(multi_client)
    kept, kept_headers = sign_in(multi_client, remember=True)
    hours = core.config.security.session_hours
    days = core.config.security.remember_days
    assert short["expires_at"] - time.time() <= hours * 3600 + 5
    assert kept["expires_at"] - time.time() > days * 86400 - 60
    # Pretend it was last used long ago: the next use starts the count again.
    from agent.security.auth import token_hash

    digest = token_hash(kept["token"])
    core.db.execute(
        "UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (time.time() + 60, digest)
    )
    assert multi_client.get("/api/servers", headers=kept_headers).status_code == 200
    row = core.db.query_one("SELECT expires_at FROM sessions WHERE token_hash = ?", (digest,))
    assert row["expires_at"] - time.time() > days * 86400 - 60


def test_a_kept_sign_in_stays_kept_when_its_key_is_renewed(multi_client):
    _, phone = sign_in(multi_client, device="Phone", remember=True)
    rotated = multi_client.post("/api/auth/rotate", headers=phone).json()
    headers = {"Authorization": f"Bearer {rotated['token']}"}
    rows = multi_client.get("/api/sessions", headers=headers).json()["sessions"]
    current = next(r for r in rows if r["current"])
    assert current["label"] == "Phone" and current["remember"] is True


def test_a_helper_sees_and_signs_out_only_their_own(multi_client):
    owner = dict(multi_client.headers)
    helper = add_helper(multi_client, owner)
    rows = multi_client.get("/api/sessions", headers=helper).json()["sessions"]
    assert {r["user"] for r in rows} == {"sam"}
    everyone = multi_client.get("/api/sessions", headers=owner).json()["sessions"]
    owner_id = next(r["id"] for r in everyone if r["user"] == "admin")
    assert multi_client.delete(f"/api/sessions/{owner_id}", headers=helper).status_code == 404
    assert multi_client.get("/api/servers", headers=owner).status_code == 200
    # The owner can sign a helper's device out.
    sam_id = next(r["id"] for r in everyone if r["user"] == "sam")
    assert multi_client.delete(f"/api/sessions/{sam_id}", headers=owner).status_code == 200
    assert multi_client.get("/api/servers", headers=helper).status_code == 401


def test_removing_a_helper_ends_their_kept_sign_ins(multi_client):
    owner = dict(multi_client.headers)
    add_helper(multi_client, owner)
    _, kept = sign_in(multi_client, "sam", HELPER_PASSWORD, remember=True)
    assert multi_client.delete("/api/accounts/sam", headers=owner).status_code == 200
    assert multi_client.get("/api/servers", headers=kept).status_code == 401


def test_a_bad_device_id_is_refused(multi_client):
    for bad in ("x", "' OR 1=1 --", "0" * 64):
        assert multi_client.delete(f"/api/sessions/{bad}").status_code in (404, 422)


# ------------------------------------------------------------ phones: sign in once
PHONE = {"device": "Server Controller on Pixel 9", "remember": True, "phone": True}


def _age(core, token: str, seconds: float) -> None:
    """Pretend a sign-in was last used `seconds` ago, as if the phone sat in a drawer."""
    from agent.security.auth import token_hash

    then = time.time() - seconds
    core.db.execute(
        "UPDATE sessions SET last_used = ?, expires_at = ? WHERE token_hash = ?",
        (then, then, token_hash(token)),
    )


def test_a_phone_stays_signed_in_until_it_is_signed_out(multi_client):
    core = multi_client.app.state.core
    signed, phone = sign_in(multi_client, **PHONE)
    assert signed["expires_at"] is None
    # Long past "keep me signed in": a phone isn't asked to sign in again.
    _age(core, signed["token"], (core.config.security.remember_days + 30) * 86400)
    core.auth.purge_expired()
    assert multi_client.get("/api/servers", headers=phone).status_code == 200
    me = multi_client.get("/api/auth/me", headers=phone).json()
    assert me["expires_at"] is None
    row = next(
        r
        for r in multi_client.get("/api/sessions", headers=phone).json()["sessions"]
        if r["current"]
    )
    assert row["expires_at"] is None and row["remember"] is True


def test_a_browsers_keep_me_signed_in_still_ends(multi_client):
    core = multi_client.app.state.core
    # The dashboard names its device too; only the phone apps say "phone".
    kept, browser = sign_in(multi_client, label="Firefox", device="Mark's PC", remember=True)
    assert kept["expires_at"] is not None
    _age(core, kept["token"], (core.config.security.remember_days + 1) * 86400)
    assert multi_client.get("/api/servers", headers=browser).status_code == 401


def test_a_phone_sign_in_still_ends_when_signed_out_or_its_account_goes(multi_client):
    owner = dict(multi_client.headers)
    # Signed out in the app.
    _, phone = sign_in(multi_client, **PHONE)
    assert multi_client.post("/api/auth/logout", headers=phone).status_code == 200
    assert multi_client.get("/api/servers", headers=phone).status_code == 401
    # Signed out on the PC.
    _, phone = sign_in(multi_client, **PHONE)
    rows = multi_client.get("/api/sessions", headers=owner).json()["sessions"]
    phone_id = next(r["id"] for r in rows if r["label"] == PHONE["device"])
    assert multi_client.delete(f"/api/sessions/{phone_id}", headers=owner).status_code == 200
    assert multi_client.get("/api/servers", headers=phone).status_code == 401
    # "Sign out everywhere" on the Security page.
    _, phone = sign_in(multi_client, **PHONE)
    assert multi_client.post("/api/security/revoke-sessions", headers=owner).status_code == 200
    assert multi_client.get("/api/servers", headers=phone).status_code == 401
    owner = sign_in(multi_client)[1]
    # A helper whose password the owner changes, then a removed helper.
    add_helper(multi_client, owner)
    _, sams = sign_in(multi_client, "sam", HELPER_PASSWORD, **PHONE)
    changed = multi_client.put(
        "/api/accounts/sam", json={"password": "a brand new password 42"}, headers=owner
    )
    assert changed.status_code == 200, changed.text
    assert multi_client.get("/api/servers", headers=sams).status_code == 401
    _, sams = sign_in(multi_client, "sam", "a brand new password 42", **PHONE)
    assert multi_client.delete("/api/accounts/sam", headers=owner).status_code == 200
    assert multi_client.get("/api/servers", headers=sams).status_code == 401


def test_a_phone_sign_in_stays_until_signed_out_when_its_key_is_renewed(multi_client):
    _, phone = sign_in(multi_client, **PHONE)
    rotated = multi_client.post("/api/auth/rotate", headers=phone).json()
    assert rotated["expires_at"] is None


def test_a_new_owner_password_on_the_pc_ends_the_owners_phone_sign_ins(
    multi_client, tmp_path, monkeypatch
):
    from agent.security import auth

    config = multi_client.app.state.core.auth.config
    old = auth.hash_password(PASSWORD)
    env = tmp_path / ".env"
    env.write_text(f"MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH={old}\n")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", old)
    config.env_path = env
    _, phone = sign_in(multi_client, **PHONE)
    add_helper(multi_client, phone)
    _, sams = sign_in(multi_client, "sam", HELPER_PASSWORD, **PHONE)
    # .env being written again with the same password changes nothing.
    env.write_text(f"MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH={old}\n# saved\n")
    assert multi_client.get("/api/servers", headers=phone).status_code == 200

    new = auth.hash_password("a brand new owner password 7")
    env.write_text(f"MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH={new}\n")
    assert multi_client.get("/api/servers", headers=phone).status_code == 401
    assert multi_client.get("/api/servers", headers=sams).status_code == 200
    sign_in(multi_client, password="a brand new owner password 7")
