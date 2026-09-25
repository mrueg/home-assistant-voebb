"""Test the voebb diagnostics."""

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import PASSWORD, USERNAME


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the password and card number are redacted."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert USERNAME not in str(result)
    assert PASSWORD not in str(result)
    # The pickup code contains initials of the account holder
    assert "12 Mu" not in str(result)
    assert result["account"] == {
        "ready_for_pickup": 2,
        "reservations": 3,
        "orders": 1,
        "pickup_code": "**REDACTED**",
        "card_valid_until": "2027-12-31",
    }
    assert result["entry"]["data"] == {
        "username": "**REDACTED**",
        "password": "**REDACTED**",
    }
    assert result["last_update_success"] is True
    assert result["last_exception"] is None
    assert [item["title"] for item in result["items"]] == [
        "Der Titel",
        "Noch ein Titel",
        "Später",
    ]
    assert result["items"][0]["return_date"] == "2026-10-12"
