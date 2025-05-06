"""Config flow for the voebb integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

import logging
import time

from .const import (
    DOMAIN,
    URL,
    CONF_SELENIUM_HOST,
    CONF_SELENIUM_PORT,
    CONF_SELENIUM_DEFAULT_PORT,
)

_LOGGER = logging.getLogger(__package__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SELENIUM_HOST): str,
        vol.Required(CONF_SELENIUM_PORT, default=CONF_SELENIUM_DEFAULT_PORT): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    url = f"http://{data[CONF_SELENIUM_HOST]}:{data[CONF_SELENIUM_PORT]}/wd/hub"

    if not await hass.async_add_executor_job(
        test_login, data[CONF_USERNAME], data[CONF_PASSWORD], url
    ):
        raise InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": f"VOEBB {data[CONF_USERNAME]}"}


def test_login(username: str, password: str, url: str):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Remote(command_executor=f"{url}", options=options)
    _LOGGER.debug(f"Connecting to {url}")

    driver.get(URL)
    driver.implicitly_wait(2)
    login_button = driver.find_element(by=By.NAME, value="SUO1_AUTHFU_1")
    login_button.click()

    username_box = driver.find_element(by=By.ID, value="L#AUSW")
    username_box.send_keys(username)
    password_box = driver.find_element(by=By.ID, value="LPASSW")
    password_box.send_keys(password)
    login_button = driver.find_element(by=By.NAME, value="LLOGIN")
    login_button.click()

    try:
        login_button = driver.find_element(by=By.NAME, value="SUO1_AUTHFU_1")
    except NoSuchElementException:
        driver.quit()
        return False

    if not login_button.get_attribute("value") == "Abmelden":
        driver.quit()
        return False
    driver.quit()
    return True


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for voebb."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
