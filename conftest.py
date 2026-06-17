"""Pytest fixtures shared across the backend test suite.

Keeps tests hermetic and fast: axes lockout disabled (otherwise repeated
auth attempts across tests trip the limiter), and the cache forced to
in-memory (no Redis dependency in CI / local test runs).
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _hermetic_settings(settings):
    settings.AXES_ENABLED = False
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }
    # Sessions ride on the cache backend in this project; keep them local too.
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    # Throttling state lives in the cache; clear it per test so rate counters
    # never bleed across tests and trip a 429 mid-suite.
    cache.clear()
