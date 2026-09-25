"""Diagnostics for the voebb integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import VoebbConfigEntry

# The library card number is also part of the title and unique_id
TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VoebbConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    account = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "last_exception": repr(coordinator.last_exception)
        if coordinator.last_exception
        else None,
        "account": {
            "ready_for_pickup": account.ready_for_pickup,
            "reservations": account.reservations,
            "orders": account.orders,
            # Contains the initials of the account holder
            "pickup_code": "**REDACTED**" if account.pickup_code else None,
            "card_valid_until": str(account.card_valid_until),
        }
        if account
        else None,
        # The diagnostics encoder doesn't turn dates into plain strings
        "items": [
            asdict(item) | {"return_date": str(item.return_date)}
            for item in (account.items if account else [])
        ],
    }
