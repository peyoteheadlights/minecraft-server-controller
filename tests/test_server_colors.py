"""Each server's color: a palette people can tell apart, assigned without
repeats, stored on the servers row, and changeable from the dashboard."""

import itertools
import math
import sqlite3

import pytest

from agent import colors
from agent.core import AgentCore
from agent.database.db import MIGRATIONS, Database

from .conftest import make_server_folder
from .test_multi_server import multi, multi_client  # noqa: F401  (fixtures)

# ------------------------------------------------------------------ palette
# Color-blindness simulation (Machado, Oliveira and Fernandes 2009, full
# severity) and the CIEDE2000 color difference. A difference of about 10 is
# clearly visible side by side; under 5 starts to look like the same color.
CVD = {
    "protanopia": [
        [0.152286, 1.052583, -0.204868],
        [0.114503, 0.786281, 0.099216],
        [-0.003882, -0.048116, 1.051998],
    ],
    "deuteranopia": [
        [0.367322, 0.860646, -0.227968],
        [0.280085, 0.672501, 0.047413],
        [-0.011820, 0.042940, 0.968881],
    ],
    "tritanopia": [
        [1.255528, -0.076749, -0.178779],
        [-0.078411, 0.930809, 0.147602],
        [0.004733, 0.691367, 0.303900],
    ],
}
MIN_DIFFERENCE = {"normal": 20.0, "protanopia": 12.0, "deuteranopia": 12.0, "tritanopia": 12.0}


def _linear(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c):
    c = min(1.0, max(0.0, c))
    return 255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)


def _rgb(hex_):
    return [int(hex_[i : i + 2], 16) for i in (1, 3, 5)]


def _simulate(rgb, kind):
    if kind == "normal":
        return rgb
    lin = [_linear(c) for c in rgb]
    return [_gamma(sum(row[j] * lin[j] for j in range(3))) for row in CVD[kind]]


def _lab(rgb):
    r, g, b = (_linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _ciede2000(lab1, lab2):
    (l1, a1, b1), (l2, a2, b2) = lab1, lab2
    c_bar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dh = 0.0 if c1p * c2p == 0 else h2p - h1p
    if dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    d_l, d_c = l2 - l1, c2p - c1p
    d_h = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    l_bar, cp_bar = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    else:
        h_bar = (h1p + h2p + (360 if h1p + h2p < 360 else -360)) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )
    d_theta = 30 * math.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(cp_bar**7 / (cp_bar**7 + 25**7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    s_c, s_h = 1 + 0.045 * cp_bar, 1 + 0.015 * cp_bar * t
    r_t = -math.sin(math.radians(2 * d_theta)) * r_c
    return math.sqrt(
        (d_l / s_l) ** 2 + (d_c / s_c) ** 2 + (d_h / s_h) ** 2 + r_t * (d_c / s_c) * (d_h / s_h)
    )


def test_the_palette_has_ten_to_twelve_different_hues():
    hexes = [h for _id, _name, h in colors.PALETTE]
    assert 10 <= len(hexes) <= 12
    assert len(set(hexes)) == len(hexes)
    assert len({i for i, _n, _h in colors.PALETTE}) == len(hexes)


@pytest.mark.parametrize("vision", list(MIN_DIFFERENCE))
def test_any_two_palette_colors_are_easy_to_tell_apart(vision):
    labs = {name: _lab(_simulate(_rgb(hex_), vision)) for _id, name, hex_ in colors.PALETTE}
    closest = min((_ciede2000(labs[a], labs[b]), a, b) for a, b in itertools.combinations(labs, 2))
    assert closest[0] >= MIN_DIFFERENCE[vision], f"{vision}: {closest}"


def test_a_new_server_gets_the_first_unused_color():
    first, second, third = (h for _i, _n, h in colors.PALETTE[:3])
    assert colors.next_unused([]) == first
    assert colors.next_unused([first]) == second
    assert colors.next_unused([second.lower(), None]) == first
    assert colors.next_unused([first, second]) == third


def test_colors_are_only_shared_once_all_are_taken():
    every = [h for _i, _n, h in colors.PALETTE]
    assert colors.next_unused(every) == every[0]
    assert colors.next_unused([*every, every[0]]) == every[1]


@pytest.mark.parametrize(
    ("given", "stored"),
    [("teal", "#0D4B48"), ("TEAL", "#0D4B48"), ("#abcdef", "#ABCDEF"), (" #123456 ", "#123456")],
)
def test_palette_ids_and_hex_are_accepted(given, stored):
    assert colors.normalise(given) == stored


@pytest.mark.parametrize("given", ["", "red", "#12345", "#1234567", "rgb(1,2,3)", "#GGGGGG"])
def test_anything_else_is_refused(given):
    with pytest.raises(colors.ColorError):
        colors.normalise(given)


# ------------------------------------------------------------------ storage
def test_an_older_database_gains_the_color_column(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    for version, script in MIGRATIONS:
        if version > 3:
            break
        conn.executescript(script)
        conn.execute("INSERT INTO schema_version VALUES (?, 0)", (version,))
    conn.execute("INSERT INTO servers (id, name, directory, created_at) VALUES ('a', 'A', '/x', 0)")
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        assert db.version == MIGRATIONS[-1][0]
        assert db.server_color("a") is None
        db.set_server_color("a", "#0D4B48")
        assert db.server_color("a") == "#0D4B48"
        db.register_server("a", "Renamed", "/x")
        assert db.server_color("a") == "#0D4B48"
    finally:
        db.close()


def test_servers_get_different_colors_that_survive_a_restart(multi):  # noqa: F811
    core = AgentCore(multi)
    try:
        first = {sid: ctx.color for sid, ctx in core.servers.items()}
    finally:
        core.db.close()
    assert len(set(first.values())) == len(first) == 2
    core = AgentCore(multi)
    try:
        assert {sid: ctx.color for sid, ctx in core.servers.items()} == first
    finally:
        core.db.close()


# ------------------------------------------------------------------ API
def test_the_server_list_carries_colors_and_the_palette(multi_client):  # noqa: F811
    data = multi_client.get("/api/servers").json()
    assert all(s["color"].startswith("#") for s in data["servers"])
    assert [p["hex"] for p in data["palette"]] == [h for _i, _n, h in colors.PALETTE]
    assert data["next_color"] not in {s["color"] for s in data["servers"]}


def test_a_server_color_can_be_changed(multi_client):  # noqa: F811
    response = multi_client.put("/api/servers/creative/color", json={"color": "#112233"})
    assert response.status_code == 200, response.text
    rows = {s["id"]: s["color"] for s in multi_client.get("/api/servers").json()["servers"]}
    assert rows["creative"] == "#112233"
    assert multi_client.get("/api/servers/creative/settings").json()["color"] == "#112233"
    response = multi_client.put("/api/servers/creative/color", json={"color": "magenta"})
    assert response.json()["color"] == "#A61888"


def test_a_bad_color_is_refused_and_nothing_changes(multi_client):  # noqa: F811
    before = multi_client.get("/api/servers").json()["servers"]
    response = multi_client.put("/api/servers/creative/color", json={"color": "red"})
    assert response.status_code == 400
    assert multi_client.get("/api/servers").json()["servers"] == before


def test_an_added_server_takes_the_chosen_or_next_color(multi_client, tmp_path):  # noqa: F811
    nxt = multi_client.get("/api/servers").json()["next_color"]
    folder = make_server_folder(tmp_path / "Skyblock", 25567)
    added = multi_client.post("/api/servers", json={"name": "Skyblock", "directory": str(folder)})
    assert added.json()["server"]["color"] == nxt
    folder = make_server_folder(tmp_path / "Hardcore", 25568)
    added = multi_client.post(
        "/api/servers", json={"name": "Hardcore", "directory": str(folder), "color": "rose"}
    )
    assert added.status_code == 200, added.text
    rows = {s["id"]: s["color"] for s in multi_client.get("/api/servers").json()["servers"]}
    assert rows["hardcore"] == "#FCA1B1"
