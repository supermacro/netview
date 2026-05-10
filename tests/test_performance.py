import logging
from time import sleep

from pytest import LogCaptureFixture

from netview.performance import performance_budget


def test_performance_budget_warns_when_function_exceeds_budget(
    caplog: LogCaptureFixture,
):
    @performance_budget(1)
    def slow_function():
        sleep(0.01)

    with caplog.at_level(logging.WARNING, logger="netview.performance"):
        slow_function()

    assert len(caplog.records) == 1
    assert "slow_function exceeded performance budget" in caplog.messages[0]
    assert "1.00ms" in caplog.messages[0]


def test_performance_budget_preserves_return_value_and_skips_fast_functions(
    caplog: LogCaptureFixture,
):
    @performance_budget(1000)
    def fast_function():
        return "ok"

    with caplog.at_level(logging.WARNING, logger="netview.performance"):
        result = fast_function()

    assert result == "ok"
    assert caplog.records == []
