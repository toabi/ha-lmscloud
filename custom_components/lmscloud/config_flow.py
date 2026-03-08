"""Config flow for LMSCloud."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_TIME_ZONE, CONF_USERNAME
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    LMSCloudApiClient,
    LMSCloudApiError,
    LMSCloudAuthError,
    LMSCloudConnectionError,
    normalize_base_url,
)
from .const import CONF_BASE_DOMAIN, DOMAIN


class LMSCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LMSCloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_domain = user_input[CONF_BASE_DOMAIN]
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            time_zone = user_input[CONF_TIME_ZONE]

            try:
                normalized = normalize_base_url(base_domain)
                ZoneInfo(time_zone)
                await self.async_set_unique_id(f"{normalized.host}:{username}")
                self._abort_if_unique_id_configured()

                client = LMSCloudApiClient(
                    session=async_get_clientsession(self.hass),
                    base_domain=base_domain,
                    username=username,
                    password=password,
                    time_zone=time_zone,
                )
                await client.validate_user()
                await client.get_borrowed_count()

            except ValueError:
                errors["base"] = "invalid_base_domain"
            except ZoneInfoNotFoundError:
                errors["base"] = "invalid_time_zone"
            except LMSCloudAuthError:
                errors["base"] = "invalid_auth"
            except LMSCloudConnectionError:
                errors["base"] = "cannot_connect"
            except LMSCloudApiError:
                errors["base"] = "unknown"
            except AbortFlow:
                raise
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

            if not errors:
                entry_data = {
                    CONF_BASE_DOMAIN: str(normalized),
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_TIME_ZONE: time_zone,
                }
                return self.async_create_entry(
                    title=f"{normalized.host} ({username})",
                    data=entry_data,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BASE_DOMAIN): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(
                    CONF_TIME_ZONE,
                    default=self.hass.config.time_zone or "UTC",
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
