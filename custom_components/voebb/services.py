"""Actions of the voebb integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .api import InvalidAuth, UnknownItem, VoebbError
from .const import DOMAIN
from .coordinator import VoebbConfigEntry

ATTR_BARCODES = "barcodes"
ATTR_CHECK_ONLY = "check_only"

SERVICE_RENEW = "renew"
RENEW_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_BARCODES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_CHECK_ONLY, default=False): cv.boolean,
    }
)


async def _async_renew(call: ServiceCall) -> ServiceResponse:
    entry: VoebbConfigEntry | None = call.hass.config_entries.async_get_entry(
        call.data[ATTR_CONFIG_ENTRY_ID]
    )
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_found"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_loaded"
        )

    try:
        results = await entry.runtime_data.async_renew(
            call.data.get(ATTR_BARCODES), call.data[ATTR_CHECK_ONLY]
        )
    except UnknownItem as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_item",
            translation_placeholders={"barcodes": str(err)},
        ) from err
    except InvalidAuth as err:
        entry.async_start_reauth(call.hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
            translation_placeholders={"error": str(err)},
        ) from err
    except VoebbError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="renew_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    return {
        "items": [
            {
                "barcode": result.barcode,
                "title": result.title,
                "return_date": result.return_date.isoformat()
                if result.return_date
                else None,
                "success": result.success,
                "message": result.message,
            }
            for result in results
        ]
    }


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions of the integration."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENEW,
        _async_renew,
        schema=RENEW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
