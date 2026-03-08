"""Constants for the LMSCloud integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "lmscloud"

CONF_BASE_DOMAIN = "base_domain"

PLATFORMS: list[Platform] = [Platform.SENSOR]
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)
