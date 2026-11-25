"""Validate acquisition controls before reading credentials or contacting NASA."""
from __future__ import annotations

import math


class ConfigurationError(ValueError):
    """A named acquisition setting has an invalid value."""


def runtime_options(config):
    """Return typed defaults without mutating the caller's configuration."""
    retries = config.get('retries', 3)
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 1:
        raise ConfigurationError('retries must be a positive integer')
    options = {'retries': retries}
    for name, default in (('timeout_seconds', 120), ('api_batch_max_age_hours', 24)):
        value = config.get(name, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ConfigurationError(f'{name} must be a finite positive number')
        options[name] = float(value)
    refresh = config.get('refresh_api_batches', False)
    if not isinstance(refresh, bool):
        raise ConfigurationError('refresh_api_batches must be a Boolean')
    options['refresh_api_batches'] = refresh
    return options


def filesystem_setting(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f'{name} must be a nonempty filesystem path string')
    return value
