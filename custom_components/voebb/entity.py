"""Base entity for the voebb integration."""

from __future__ import annotations

from homeassistant.const import CONF_USERNAME
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoebbCoordinator


class VoebbEntity(CoordinatorEntity[VoebbCoordinator]):
    """An entity of one VOEBB account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VoebbCoordinator, key: str) -> None:
        super().__init__(coordinator)
        username = coordinator.config_entry.data[CONF_USERNAME]
        self._attr_unique_id = f"voebb_{username}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, username)},
            name="VOEBB",
            manufacturer="Verbund der Öffentlichen Bibliotheken Berlins",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.voebb.de",
        )
