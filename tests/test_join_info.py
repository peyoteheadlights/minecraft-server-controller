"""The "How friends join" card shows only addresses read from this PC.

Nothing is filled in on a guess: no adapter means no home address, no
Tailscale means no Tailscale address, and whether the server can be
reached from the internet is always "not known".
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from agent import joininfo, tailscale


def addr(address, family=socket.AF_INET):
    return SimpleNamespace(family=family, address=address)


@pytest.fixture
def adapters(monkeypatch):
    def install(addresses, down=()):
        monkeypatch.setattr(joininfo.psutil, "net_if_addrs", lambda: addresses)
        monkeypatch.setattr(
            joininfo.psutil,
            "net_if_stats",
            lambda: {name: SimpleNamespace(isup=name not in down) for name in addresses},
        )

    return install


def test_only_private_addresses_of_adapters_that_are_up_are_listed(adapters):
    adapters(
        {
            "Ethernet": [addr("192.168.1.20"), addr("fe80::1", socket.AF_INET6)],
            "Wi-Fi": [addr("10.0.0.5")],
            "Loopback": [addr("127.0.0.1")],
            "Tailscale": [addr("100.101.102.103")],
            "Odd": [addr("100.70.0.1"), addr("169.254.3.4"), addr("8.8.8.8")],
            "vEthernet (WSL)": [addr("172.20.0.1")],
            "Unplugged": [addr("192.168.5.5")],
        },
        down={"Unplugged"},
    )
    found = joininfo.local_addresses()
    assert [(a["adapter"], a["address"]) for a in found] == [
        ("Ethernet", "192.168.1.20"),
        ("Wi-Fi", "10.0.0.5"),
        ("vEthernet (WSL)", "172.20.0.1"),
    ]
    assert [a["virtual"] for a in found] == [False, False, True]


def test_no_adapters_means_no_addresses_not_a_made_up_one(adapters):
    adapters({})
    assert joininfo.local_addresses() == []


def test_the_api_reports_what_it_read_and_says_internet_is_unknown(
    multi_client, adapters, monkeypatch
):
    adapters({"Ethernet": [addr("192.168.1.20")]})
    monkeypatch.setattr(
        tailscale,
        "connection_status",
        lambda: {"address": None, "connected": None, "verified": False, "detail": "not found"},
    )
    body = multi_client.get("/api/servers/creative/join").json()
    assert body["java"]["port"] == 25566
    assert body["java"]["default_port"] is False
    assert body["java"]["local"] == [
        {"address": "192.168.1.20", "adapter": "Ethernet", "virtual": False}
    ]
    assert body["java"]["tailscale"]["address"] is None
    assert body["internet"] == {"known": False, "reason": "not_tested"}
    assert body["bedrock"] is None  # crossplay is off


def test_tailscales_own_address_is_shown_when_it_reports_one(multi_client, adapters, monkeypatch):
    adapters({})
    monkeypatch.setattr(
        tailscale,
        "connection_status",
        lambda: {
            "address": "100.101.102.103",
            "dns_name": "gaming-pc.tail1234.ts.net",
            "connected": True,
            "verified": True,
            "source": "tailscale status",
        },
    )
    body = multi_client.get("/api/servers/survival/join").json()
    ts = body["java"]["tailscale"]
    assert ts["address"] == "100.101.102.103" and ts["verified"] is True
    assert ts["dns_name"] == "gaming-pc.tail1234.ts.net"
    assert body["java"]["default_port"] is True
