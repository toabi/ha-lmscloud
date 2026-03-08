"""Data coordinator for LMSCloud."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LMSCloudApiClient, LMSCloudApiError, LMSCloudAuthError, LMSCloudConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class LMSCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and coordinate LMSCloud data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: LMSCloudApiClient,
        entry_id: str,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from LMSCloud."""
        try:
            snapshot = await self._client.get_account_snapshot()
        except LMSCloudAuthError as err:
            raise ConfigEntryAuthFailed from err
        except LMSCloudConnectionError as err:
            raise UpdateFailed("Could not connect to LMSCloud API") from err
        except LMSCloudApiError as err:
            raise UpdateFailed(f"LMSCloud API error: {err}") from err

        return snapshot
