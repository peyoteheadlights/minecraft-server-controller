import pytest

from agent.security import auth
from agent.security.auth import AuthError, RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(auth.time, "time", c)
    return c


def test_requests_over_the_limit_are_rejected(clock):
    limiter = RateLimiter(limit=3, window=60)
    for _ in range(3):
        limiter.check("ip")
    with pytest.raises(AuthError) as err:
        limiter.check("ip")
    assert err.value.status == 429
    assert err.value.retry_after == 61


def test_retrying_while_blocked_does_not_extend_the_block(clock):
    limiter = RateLimiter(limit=2, window=60)
    limiter.check("ip")
    limiter.check("ip")
    for _ in range(20):
        clock.now += 2
        with pytest.raises(AuthError):
            limiter.check("ip")
    clock.now = 1000.0 + 60
    limiter.check("ip")  # the first accepted request has left the window


def test_idle_callers_are_forgotten(clock):
    limiter = RateLimiter(limit=5, window=60)
    for n in range(100):
        limiter.check(f"ip-{n}")
    clock.now += 61 + RateLimiter.SWEEP_INTERVAL
    limiter.check("someone-new")
    assert list(limiter._hits) == ["someone-new"]
