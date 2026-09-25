"""Calendar with the return dates of borrowed items."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import groupby

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Item
from .coordinator import VoebbConfigEntry, VoebbCoordinator
from .entity import VoebbEntity

# Coordinator handles the polling, entities only read its data
PARALLEL_UPDATES = 0

# Event texts, translations in strings.json don't cover calendar events
SUMMARIES = {
    "de": ("{title} zurückgeben", "{count} Medien zurückgeben"),
    "en": ("Return {title}", "Return {count} items"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VoebbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VoebbCalendar(config_entry.runtime_data)])


def _events(items: list[Item], language: str) -> list[CalendarEvent]:
    """One all-day event per return date and library."""
    dated = sorted(
        (item for item in items if item.return_date),
        key=lambda item: (item.return_date, item.library),
    )
    single, multiple = SUMMARIES.get(language.split("-")[0], SUMMARIES["en"])
    events = []
    for (due, library), group in groupby(
        dated, key=lambda item: (item.return_date, item.library)
    ):
        grouped = list(group)
        summary = (
            single.format(title=grouped[0].title)
            if len(grouped) == 1
            else multiple.format(count=len(grouped))
        )
        events.append(
            CalendarEvent(
                start=due,
                end=due + timedelta(days=1),
                summary=summary,
                description="\n".join(
                    f"{item.title} / {item.author}" if item.author else item.title
                    for item in grouped
                ),
                location=library,
                uid=f"{due.isoformat()}_{library}",
            )
        )
    return events


class VoebbCalendar(VoebbEntity, CalendarEntity):
    """Return dates of borrowed items."""

    _attr_translation_key = "return_dates"

    def __init__(self, coordinator: VoebbCoordinator) -> None:
        super().__init__(coordinator, "return_dates")

    @property
    def event(self) -> CalendarEvent | None:
        """The next upcoming return date."""
        today = dt_util.now().date()
        events = _events(self.coordinator.data.items, self.hass.config.language)
        return next((event for event in events if event.end > today), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start, end = start_date.date(), end_date.date()
        return [
            event
            for event in _events(self.coordinator.data.items, self.hass.config.language)
            if event.start <= end and event.end > start
        ]
