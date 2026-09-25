"""Data update coordinator for the voebb integration."""

from __future__ import annotations

from dataclasses import replace
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Account, InvalidAuth, RenewResult, VoebbClient, VoebbError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__package__)

type VoebbConfigEntry = ConfigEntry[VoebbCoordinator]


class VoebbCoordinator(DataUpdateCoordinator[Account]):
    """Fetch the borrowed items of one VOEBB account."""

    config_entry: VoebbConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: VoebbConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    def _client(self, session: aiohttp.ClientSession) -> VoebbClient:
        return VoebbClient(
            session,
            self.config_entry.data[CONF_USERNAME],
            self.config_entry.data[CONF_PASSWORD],
        )

    async def async_renew(
        self, barcodes: list[str] | None, check_only: bool
    ) -> list[RenewResult]:
        """Renew items, errors of the client are passed on."""
        # A fresh session keeps the aDISWeb cookies separate per login
        async with aiohttp.ClientSession() as session:
            results, items = await self._client(session).async_renew(
                barcodes, check_only
            )
        if not check_only:
            # VOEBB shows the new return dates right away, no need for another login
            self.async_set_updated_data(replace(self.data, items=items))
        return results

    async def _async_update_data(self) -> Account:
        # A fresh session keeps the aDISWeb cookies separate per login
        async with aiohttp.ClientSession() as session:
            try:
                return await self._client(session).async_fetch_account()
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                    translation_placeholders={"error": str(err)},
                ) from err
            except VoebbError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="update_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
