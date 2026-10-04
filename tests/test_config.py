"""The typed config: one place for defaults, values checked at load."""

import pytest

from agent.config import DEFAULTS, Config, ConfigError, ServerSettings

from .conftest import PASSWORD


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path, text, monkeypatch):
    for key in ("MCSC_HOST", "MCSC_PORT", "MCSC_SERVER_DIR", "MCSC_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    return Config.load(write(tmp_path, text), env_file=tmp_path / "missing.env")


def test_an_existing_single_server_config_loads_unchanged(tmp_path, monkeypatch):
    cfg = load(
        tmp_path,
        """
server:
  directory: C:/Minecraft
  jvm_args: [-Xmx8G]
monitor:
  restart_delay: 30
""",
        monkeypatch,
    )
    assert cfg.server.directory == "C:/Minecraft"
    assert cfg.server.jvm_args == ["-Xmx8G"]
    assert cfg.monitor.restart_delay == 30
    # Everything not in the file comes from the one set of defaults.
    assert cfg.monitor.max_crashes == DEFAULTS["monitor"]["max_crashes"]
    assert cfg.notifications.email.port == 587


def test_defaults_are_built_from_the_typed_sections():
    assert DEFAULTS["server"] == ServerSettings().to_dict()
    assert DEFAULTS["notifications"]["email"]["port"] == 587


def test_values_are_converted_to_their_declared_types(tmp_path, monkeypatch):
    cfg = load(
        tmp_path,
        """
network:
  port: "9000"
monitor:
  auto_restart: "no"
  restart_delay: 5
""",
        monkeypatch,
    )
    assert cfg.network.port == 9000
    assert cfg.monitor.auto_restart is False
    assert isinstance(cfg.monitor.restart_delay, float)


def test_a_bad_value_fails_at_load_with_its_name(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="thresholds.cpu_percent"):
        load(tmp_path, "thresholds:\n  cpu_percent: lots\n", monkeypatch)


@pytest.mark.parametrize("value", ["maybe", "2", "[yes]"])
def test_an_unrecognised_on_off_value_fails_instead_of_meaning_on(tmp_path, monkeypatch, value):
    with pytest.raises(ConfigError, match="monitor.auto_restart must be true or false"):
        load(tmp_path, f"monitor:\n  auto_restart: {value}\n", monkeypatch)


@pytest.mark.parametrize(("value", "expected"), [("yes", True), ("off", False), ("1", True),
                                                 ("0", False), ("true", True)])
def test_recognised_on_off_values_still_work(tmp_path, monkeypatch, value, expected):
    cfg = load(tmp_path, f"monitor:\n  auto_restart: {value}\n", monkeypatch)
    assert cfg.monitor.auto_restart is expected


def test_empty_yaml_values_mean_empty_not_the_word_none(tmp_path, monkeypatch):
    cfg = load(
        tmp_path,
        """
server:
  directory:
  port:
tls:
  ca_certificate:
""",
        monkeypatch,
    )
    assert cfg.server.directory == ""
    assert cfg.server.port == 25565
    assert cfg.tls.ca_certificate == ""
    assert cfg.tls_ca_certificate is None


def test_set_is_seen_by_the_typed_view(config):
    assert config.monitor.restart_delay == 0.2
    config.set("monitor.restart_delay", 7)
    assert config.monitor.restart_delay == 7.0


def test_the_dashboard_cannot_save_a_value_of_the_wrong_type(client, config):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "token"
    ]
    response = client.put(
        "/api/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"updates": {"thresholds.cpu_percent": "lots", "thresholds.ram_percent": 80}},
    )
    body = response.json()
    assert "thresholds.cpu_percent" in body["rejected"]
    assert body["applied"] == {"thresholds.ram_percent": 80}
    assert config.thresholds.cpu_percent == 90.0
