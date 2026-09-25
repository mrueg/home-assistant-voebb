"""Test setup, migration and entities of the voebb integration."""

from datetime import date
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.voebb.api import CannotConnect, InvalidAuth
from custom_components.voebb.const import DOMAIN, UPDATE_INTERVAL

from .conftest import PASSWORD, USERNAME, account

COUNT = "sensor.voebb_borrowed_items"
NEXT = "sensor.voebb_next_return_date"
CALENDAR = "calendar.voebb_return_dates"
OVERDUE = "binary_sensor.voebb_overdue"


async def test_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the entities show the borrowed items."""
    freezer.move_to("2026-10-01 12:00:00+00:00")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get(COUNT)
    assert state.state == "3"
    assert [item["title"] for item in state.attributes["items"]] == [
        "Der Titel",
        "Noch ein Titel",
        "Später",
    ]
    assert state.attributes["items"][0]["return_date"] == date(2026, 10, 12)
    assert (
        entity_registry.async_get(COUNT).unique_id == f"voebb_{USERNAME}_borrowed_items"
    )

    state = hass.states.get(NEXT)
    assert state.state == "2026-10-12"
    assert state.attributes["titles"] == ["Der Titel", "Noch ein Titel"]

    state = hass.states.get(OVERDUE)
    assert state.state == "off"
    assert state.attributes["titles"] == []

    state = hass.states.get("sensor.voebb_ready_for_pickup")
    assert state.state == "2"
    assert state.attributes["pickup_code"] == "12 Mu"
    assert hass.states.get("sensor.voebb_library_card_valid_until").state == (
        "2027-12-31"
    )
    assert hass.states.get("sensor.voebb_reservations").state == "3"
    assert hass.states.get("sensor.voebb_orders_from_the_stacks").state == "1"

    state = hass.states.get(CALENDAR)
    assert state.state == "off"
    assert state.attributes["message"] == "Return 2 items"
    assert state.attributes["location"] == "Pankow"
    assert state.attributes["start_time"] == "2026-10-12 00:00:00"

    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": "2026-10-01", "end_date_time": "2026-12-01"},
        target={"entity_id": CALENDAR},
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in events[CALENDAR]["events"]] == [
        "Return 2 items",
        "Return Später",
    ]

    # Only one login at setup, the next one after the update interval
    assert mock_client.async_fetch_account.call_count == 1
    freezer.tick(UPDATE_INTERVAL / 2)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_client.async_fetch_account.call_count == 1

    mock_client.async_fetch_account.return_value = account([])
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_client.async_fetch_account.call_count == 2
    assert hass.states.get(COUNT).state == "0"
    assert hass.states.get(NEXT).state == "unknown"


async def test_update_failed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test entities become unavailable when the website fails."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_client.async_fetch_account.side_effect = CannotConnect
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(COUNT).state == STATE_UNAVAILABLE


async def test_setup_not_ready(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test setup is retried when the website fails."""
    mock_client.async_fetch_account.side_effect = CannotConnect
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_invalid_auth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Test a rejected password starts a reauth flow."""
    mock_client.async_fetch_account.side_effect = InvalidAuth
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == config_entry.entry_id


async def test_overdue_at_midnight(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test items become overdue at midnight without polling the website."""
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-12 23:59:00+00:00")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(OVERDUE).state == "off"

    freezer.move_to("2026-10-13 00:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(OVERDUE)
    assert state.state == "on"
    assert state.attributes["titles"] == ["Der Titel", "Noch ein Titel"]
    assert mock_client.async_fetch_account.call_count == 1


async def test_calendar_german(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test calendar events follow the configured language."""
    freezer.move_to("2026-10-01 12:00:00+00:00")
    hass.config.language = "de"
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Entity IDs are created from the translated names
    calendar = "calendar.voebb_ruckgabetermine"
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": "2026-10-01", "end_date_time": "2026-12-01"},
        target={"entity_id": calendar},
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in events[calendar]["events"]] == [
        "2 Medien zurückgeben",
        "Später zurückgeben",
    ]


async def test_update_failed_message(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the update error is translated."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    mock_client.async_fetch_account.side_effect = CannotConnect("table not found")
    await coordinator.async_refresh()
    assert str(coordinator.last_exception) == (
        "Fetching the borrowed items from VOEBB failed: table not found"
    )


async def test_setup_selenium_entry(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Test entries of the Selenium version still load."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            "Hostname of remote selenium webserver": "chromium",
            "Port to remote selenium webdriver": "4444",
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(COUNT).state == "3"
