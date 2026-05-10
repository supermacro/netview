import logging
from collections.abc import Callable
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def performance_budget(
    budget_ms: float,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = perf_counter()

            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (perf_counter() - start) * 1000

                if elapsed_ms > budget_ms:
                    logger.warning(
                        "%s exceeded performance budget: %.2fms > %.2fms",
                        func.__qualname__,
                        elapsed_ms,
                        budget_ms,
                    )

        return wrapper

    return decorator
