"""Sensors for the voebb integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VoebbConfigEntry, VoebbCoordinator
from .entity import VoebbEntity

# Coordinator handles the polling, entities only read its data
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VoebbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    async_add_entities(
        [
            VoebbBorrowedItemsSensor(coordinator),
            VoebbNextReturnSensor(coordinator),
            VoebbReadyForPickupSensor(coordinator),
            VoebbCountSensor(coordinator, "reservations"),
            VoebbCountSensor(coordinator, "orders"),
            VoebbCardValidUntilSensor(coordinator),
        ]
    )


class VoebbBorrowedItemsSensor(VoebbEntity, SensorEntity):
    """Number of borrowed items, with all items as attribute."""

    _attr_translation_key = "borrowed_items"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The item list can be large, keep it out of the recorder database
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "borrowed_items")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"items": [asdict(item) for item in self.coordinator.data.items]}


class VoebbNextReturnSensor(VoebbEntity, SensorEntity):
    """Date the next borrowed item is due."""

    _attr_translation_key = "next_return_date"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "next_return_date")

    @property
    def native_value(self) -> date | None:
        # Items are sorted by return date
        return (
            self.coordinator.data.items[0].return_date
            if self.coordinator.data.items
            else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        due = self.native_value
        return {
            "titles": [
                item.title
                for item in self.coordinator.data.items
                if item.return_date == due
            ]
            if due
            else []
        }


class VoebbReadyForPickupSensor(VoebbEntity, SensorEntity):
    """Number of reserved items waiting for pickup, with the pickup code."""

    _attr_translation_key = "ready_for_pickup"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "ready_for_pickup")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.ready_for_pickup

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pickup_code": self.coordinator.data.pickup_code}


class VoebbCountSensor(VoebbEntity, SensorEntity):
    """A count of the account overview, e.g. the reservations."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoebbCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key

    @property
    def native_value(self) -> int | None:
        value: int | None = getattr(self.coordinator.data, self._key)
        return value


class VoebbCardValidUntilSensor(VoebbEntity, SensorEntity):
    """Date the library card expires."""

    _attr_translation_key = "card_valid_until"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "card_valid_until")

    @property
    def native_value(self) -> date | None:
        return self.coordinator.data.card_valid_until
