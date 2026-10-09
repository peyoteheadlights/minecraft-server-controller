"""Passwords are hashed with OWASP's round count, and a hash made with fewer
rounds keeps working and is re-made the next time that person signs in."""

from agent.security import auth

from .conftest import PASSWORD

HELPER_PASSWORD = "helper password 123"


def rounds_of(encoded: str) -> int:
    return int(encoded.split("$")[1])


def test_the_round_count_is_owasps_figure():
    assert auth.OWASP_PBKDF2_SHA256_ROUNDS == 600_000
    encoded = auth.hash_password("long enough password", rounds=auth.OWASP_PBKDF2_SHA256_ROUNDS)
    assert rounds_of(encoded) == 600_000
    assert auth.verify_password("long enough password", encoded)


def test_needs_rehash(monkeypatch):
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 2000)
    assert auth.needs_rehash(auth.hash_password(PASSWORD, rounds=1000))
    assert not auth.needs_rehash(auth.hash_password(PASSWORD, rounds=2000))
    assert not auth.needs_rehash("not a hash")
    assert not auth.needs_rehash("")


def test_old_owner_hash_signs_in_and_is_rehashed(client, config, tmp_path, monkeypatch):
    old = auth.hash_password(PASSWORD, rounds=1000)
    env = tmp_path / ".env"
    env.write_text(f"MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH={old}\nOTHER=kept\n")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", old)
    config.env_path = env
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 2000)

    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200, response.text

    text = env.read_text()
    assert "OTHER=kept" in text
    line = next(x for x in text.splitlines() if x.startswith("MCSC_ADMIN_PASSWORD_HASH="))
    saved = line.partition("=")[2]
    assert rounds_of(saved) == 2000
    assert auth.verify_password(PASSWORD, saved)
    # and the new hash is the one in use: signing in again still works
    again = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert again.status_code == 200


def test_wrong_password_never_rehashes(client, config, tmp_path, monkeypatch):
    old = auth.hash_password(PASSWORD, rounds=1000)
    env = tmp_path / ".env"
    env.write_text(f"MCSC_ADMIN_PASSWORD_HASH={old}\n")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", old)
    config.env_path = env
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 2000)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong one!!"})
    assert response.status_code == 401
    assert env.read_text() == f"MCSC_ADMIN_PASSWORD_HASH={old}\n"


def test_old_helper_hash_is_rehashed(multi_client, monkeypatch):
    client = multi_client
    owner = dict(client.headers)
    made = client.post(
        "/api/accounts", json={"username": "sam", "password": HELPER_PASSWORD}, headers=owner
    )
    assert made.status_code == 200, made.text
    db = client.app.state.core.db
    before = db.query_one("SELECT password_hash FROM accounts WHERE username = 'sam'")
    assert rounds_of(before["password_hash"]) == 1000

    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 2000)
    response = client.post("/api/auth/login", json={"username": "sam", "password": HELPER_PASSWORD})
    assert response.status_code == 200, response.text
    after = db.query_one("SELECT password_hash FROM accounts WHERE username = 'sam'")
    assert rounds_of(after["password_hash"]) == 2000
    assert auth.verify_password(HELPER_PASSWORD, after["password_hash"])
