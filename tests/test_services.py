"""Test the actions of the voebb integration."""

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.voebb.api import (
    CannotConnect,
    InvalidAuth,
    RenewResult,
    UnknownItem,
)
from custom_components.voebb.const import DOMAIN

from .conftest import ITEMS

RESULTS = [
    RenewResult(
        barcode="00000000001",
        title="Der Titel",
        return_date=date(2026, 11, 9),
        success=True,
        message="Heute verlängert\n1 Verlängerung",
    ),
    RenewResult(
        barcode="00000000002",
        title="Noch ein Titel",
        return_date=date(2026, 10, 12),
        success=False,
        message="nicht verlängerbar : Verlängerung noch nicht möglich",
    ),
]

# The borrowed items after renewing
RENEWED = [ITEMS[1]]


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> MockConfigEntry:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.async_renew.return_value = (RESULTS, RENEWED)
    return config_entry


async def renew(hass: HomeAssistant, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, "renew", data, blocking=True, return_response=True
    )


async def test_renew(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test renewing returns the result per item and updates the entities."""
    response = await renew(
        hass,
        config_entry_id=setup_entry.entry_id,
        barcodes=["00000000001", "00000000002"],
    )
    await hass.async_block_till_done()

    mock_client.async_renew.assert_called_once_with(
        ["00000000001", "00000000002"], False
    )
    assert response == {
        "items": [
            {
                "barcode": "00000000001",
                "title": "Der Titel",
                "return_date": "2026-11-09",
                "success": True,
                "message": "Heute verlängert\n1 Verlängerung",
            },
            {
                "barcode": "00000000002",
                "title": "Noch ein Titel",
                "return_date": "2026-10-12",
                "success": False,
                "message": "nicht verlängerbar : Verlängerung noch nicht möglich",
            },
        ]
    }
    # Updated from the page VOEBB shows after renewing, without another login
    assert mock_client.async_fetch_account.call_count == 1
    assert hass.states.get("sensor.voebb_next_return_date").state == "2026-10-12"
    assert hass.states.get("sensor.voebb_borrowed_items").state == "1"


async def test_renew_check_only(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test checking all items doesn't refresh the entities."""
    await renew(hass, config_entry_id=setup_entry.entry_id, check_only=True)
    await hass.async_block_till_done()

    mock_client.async_renew.assert_called_once_with(None, True)
    assert mock_client.async_fetch_account.call_count == 1


async def test_renew_unknown_item(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_renew.side_effect = UnknownItem("00000000099")

    with pytest.raises(
        ServiceValidationError, match="These items are not borrowed: 00000000099"
    ):
        await renew(hass, config_entry_id=setup_entry.entry_id, barcodes="00000000099")


async def test_renew_invalid_auth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test a rejected password starts a reauth flow."""
    mock_client.async_renew.side_effect = InvalidAuth("wrong password")

    with pytest.raises(HomeAssistantError, match="VOEBB rejected the login"):
        await renew(hass, config_entry_id=setup_entry.entry_id)
    await hass.async_block_till_done()

    (flow,) = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH


async def test_renew_failed(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_renew.side_effect = CannotConnect("button not found")

    with pytest.raises(
        HomeAssistantError, match="Renewing at VOEBB failed: button not found"
    ):
        await renew(hass, config_entry_id=setup_entry.entry_id)


async def test_renew_entry_not_found(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="not found"):
        await renew(hass, config_entry_id="missing")


async def test_renew_entry_not_loaded(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    await hass.config_entries.async_unload(setup_entry.entry_id)

    with pytest.raises(ServiceValidationError, match="not loaded"):
        await renew(hass, config_entry_id=setup_entry.entry_id)
