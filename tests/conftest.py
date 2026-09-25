"""Common fixtures for the voebb tests."""

from collections.abc import Generator
from datetime import date
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.voebb.api import Account, Item
from custom_components.voebb.const import DOMAIN

USERNAME = "12345678901"
PASSWORD = "secret"

ITEMS = [
    Item(
        title="Der Titel",
        author="Muster, Max",
        library="Pankow",
        call_number="Buch",
        barcode="00000000001",
        return_date=date(2026, 10, 12),
        renewals=0,
        renewal_blocked=False,
        extension="",
    ),
    Item(
        title="Noch ein Titel",
        author="",
        library="Pankow",
        call_number="DVD",
        barcode="00000000002",
        return_date=date(2026, 10, 12),
        renewals=0,
        renewal_blocked=False,
        extension="",
    ),
    Item(
        title="Später",
        author="",
        library="Mitte",
        call_number="Buch",
        barcode="00000000003",
        return_date=date(2026, 11, 1),
        renewals=0,
        renewal_blocked=False,
        extension="",
    ),
]


def account(items: list[Item] | None = None) -> Account:
    """Return the data of an account, with ITEMS by default."""
    return Account(
        items=list(ITEMS) if items is None else items,
        ready_for_pickup=2,
        reservations=3,
        orders=1,
        pickup_code="12 Mu",
        card_valid_until=date(2027, 12, 31),
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in all tests."""
    yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "custom_components.voebb.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_flow_client() -> Generator[AsyncMock]:
    """Mock the client used by the config flow to check the login."""
    with patch(
        "custom_components.voebb.config_flow.VoebbClient", autospec=True
    ) as mock_flow_client:
        yield mock_flow_client


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the client used by the coordinator."""
    with patch(
        "custom_components.voebb.coordinator.VoebbClient", autospec=True
    ) as mock_client:
        mock_client.return_value.async_fetch_account.return_value = account()
        yield mock_client.return_value


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=USERNAME,
        title="VOEBB …8901",
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
