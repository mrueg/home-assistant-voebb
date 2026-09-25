"""Binary sensors for the voebb integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .api import Item
from .coordinator import VoebbConfigEntry, VoebbCoordinator
from .entity import VoebbEntity

# Coordinator handles the polling, entities only read its data
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VoebbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VoebbOverdueSensor(config_entry.runtime_data)])


class VoebbOverdueSensor(VoebbEntity, BinarySensorEntity):
    """On when a borrowed item is past its return date."""

    _attr_translation_key = "overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "overdue")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Items become overdue at midnight, not when the website is polled
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _async_midnight(self, _: datetime) -> None:
        self.async_write_ha_state()

    def _overdue_items(self) -> list[Item]:
        today = dt_util.now().date()
        return [
            item
            for item in self.coordinator.data.items
            if item.return_date and item.return_date < today
        ]

    @property
    def is_on(self) -> bool:
        return bool(self._overdue_items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"titles": [item.title for item in self._overdue_items()]}
