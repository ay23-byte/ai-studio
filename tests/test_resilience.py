"""Retry behaviour: recover from blips, give up cleanly, never swallow Ctrl-C."""

from __future__ import annotations

import pytest

from studio import resilience
from studio.resilience import RetryExhausted, retry_call


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries must not make the suite slow."""
    monkeypatch.setattr(resilience.time, "sleep", lambda *_: None)


def test_returns_first_success():
    calls = []

    def work():
        calls.append(1)
        return "ok"

    assert retry_call(work, attempts=3, label="work") == "ok"
    assert len(calls) == 1


def test_retries_until_success():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("network blip")
        return len(calls)

    assert retry_call(flaky, attempts=5, label="flaky") == 3
    assert len(calls) == 3


def test_exhaustion_keeps_last_error():
    def always_fail():
        raise ValueError("nope")

    with pytest.raises(RetryExhausted) as excinfo:
        retry_call(always_fail, attempts=2, label="always")
    assert isinstance(excinfo.value.last_error, ValueError)
    assert excinfo.value.attempts == 2
    assert "always" in str(excinfo.value)


def test_on_retry_receives_context():
    events = []

    def fail_once():
        if not events:
            raise RuntimeError("first")
        return "done"

    result = retry_call(
        fail_once, attempts=2, label="ctx",
        on_retry=lambda attempt, error, delay: events.append((attempt, str(error))),
    )
    assert result == "done"
    assert events == [(1, "first")]


def test_keyboard_interrupt_is_not_retried():
    calls = []

    def interrupted():
        calls.append(1)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        retry_call(interrupted, attempts=3, label="interrupt")
    assert len(calls) == 1


def test_attempts_clamped_to_one():
    def fail():
        raise RuntimeError("once")

    with pytest.raises(RetryExhausted):
        retry_call(fail, attempts=0, label="clamped")


def test_give_up_on_stops_retrying_immediately():
    calls = []

    class Fatal(Exception):
        pass

    def never_works():
        calls.append(1)
        raise Fatal("retired model")

    with pytest.raises(Fatal):
        retry_call(never_works, attempts=4, label="fatal", give_up_on=(Fatal,))
    assert len(calls) == 1


def test_give_up_on_does_not_block_other_retries():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise ConnectionError("blip")
        return "ok"

    class Fatal(Exception):
        pass

    assert retry_call(flaky, attempts=3, label="mixed", give_up_on=(Fatal,)) == "ok"
    assert len(calls) == 2
