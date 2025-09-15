from dataclasses import dataclass
from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType


from selenium import webdriver
from selenium.webdriver.common.by import By

import logging
import time

from .const import (
    URL,
    DEFAULT_ICON,
    CONF_SELENIUM_HOST,
    CONF_SELENIUM_PORT,
    DOMAIN,  # noqa
    SCAN_INTERVAL,  # noqa
)

_LOGGER = logging.getLogger(__package__)


class FailedFetchingAusleihen(HomeAssistantError):
    """Error to indicate there is an issue failed to fetch the Ausleihen page."""


@dataclass
class Item:
    title: str
    author: str
    library: str
    metadata: str
    return_date: datetime
    extension: str

    @classmethod
    def from_dict(cls, source):
        timestamp = datetime.fromisoformat(source.get("return_date"))

        return cls(
            title=source["title"],
            author=source["author"],
            library=source["library"],
            metadata=source["metadata"],
            return_date=timestamp.strftime("%Y-%m-%d"),
            extension=source["extension"],
        )

    def to_dict(self):
        return {
            "title": self.title,
            "author": self.author,
            "library": self.library,
            "metadata": self.metadata,
            "return_date": self.return_date,
            "extension": self.extension,
        }

    def __hash__(self):
        return hash(tuple(sorted(self.to_dict().items())))


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    _: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor platform."""
    async_add_entities([VOEBBSensor(hass)])


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([VOEBBSensor(hass, config_entry.data)])


class VOEBBSensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass: HomeAssistant = hass
        self.config: dict = config
        self.username: str = config.get(CONF_USERNAME)
        self.password: str = config.get(CONF_PASSWORD)
        self.selenium_host: str = config.get(CONF_SELENIUM_HOST)
        self.selenium_port: str = config.get(CONF_SELENIUM_PORT)
        self.items: list[Item] = []
        self._last_updated: datetime

    @property
    def name(self) -> str:
        return f"VOEBB: {self.username}"

    @property
    def unique_id(self) -> str:
        return f"voebb_{self.username}"

    @property
    def state(self) -> str:
        _LOGGER.debug(f"{DOMAIN} - state() called")
        next_item = self.next_item()
        if next_item:
            return f"Next item to return: {next_item.title} at {next_item.return_date}"
        return "N/A"

    @property
    def extra_state_attributes(self):
        return {"items": [item.to_dict() for item in self.items or []]}

    @property
    def icon(self) -> str:
        return DEFAULT_ICON

    def update(self) -> None:
        _LOGGER.debug(f"{DOMAIN} - update() called")
        # We don't want to hammer the website if we have items and updated once
        if (
            self.items
            and self._last_updated
            and (datetime.now() - self._last_updated) < timedelta(hours=6)
        ):
            _LOGGER.debug(
                f"Last update was on {self._last_updated} - skipping for 6 hours"
            )
        else:
            self.items = self.fetch_items()
            self._last_updated = datetime.now()

    def fetch_items(self) -> list[Item]:
        _LOGGER.debug(f"{DOMAIN} - fetch_items() called")
        items = []

        options = webdriver.ChromeOptions()
        options.add_argument("--window-size=1920,1080")
        url = f"http://{self.selenium_host}:{self.selenium_port}/wd/hub"
        _LOGGER.debug(f"{DOMAIN} - fetch_items: Connecting to {url}")

        driver = webdriver.Remote(command_executor=url, options=options)
        driver.get(URL)
        driver.implicitly_wait(2)
        login_button = driver.find_element(by=By.NAME, value="SUO1_AUTHFU_1")
        login_button.click()

        _LOGGER.debug(f"{DOMAIN} - fetch_items: Navigating to login page")

        username_box = driver.find_element(by=By.ID, value="L#AUSW")
        username_box.send_keys(self.username)
        password_box = driver.find_element(by=By.ID, value="LPASSW")
        password_box.send_keys(self.password)
        login_button = driver.find_element(by=By.NAME, value="LLOGIN")
        login_button.click()

        try:
            login_button = driver.find_element(by=By.NAME, value="SUO1_AUTHFU_1")
        except NoSuchElementException:
            _LOGGER.debug(f"{DOMAIN} - fetch_items: Auth failed")
            driver.quit()
            raise InvalidAuth

        _LOGGER.debug(f"{DOMAIN} - fetch_items: Auth succeeded")
        account_link = driver.find_element(
            by=By.XPATH, value="//a[@title='Mein Konto']"
        )
        account_link.click()
        try:
            borrow_link = driver.find_element(by=By.PARTIAL_LINK_TEXT, value="Ausleihen")
        except NoSuchElementException:
            _LOGGER.debug(f"{DOMAIN} - fetch_items: Fetching Ausleihen failed")
            driver.quit()
            raise FailedFetchingAusleihen

        borrow_link.click()
        _LOGGER.debug(f"{DOMAIN} - fetch_items: Selected Ausleihen")

        rows = len(driver.find_elements(By.XPATH, '//*[@id="resptable-1"]/tbody/tr'))

        _LOGGER.debug(f"{DOMAIN} - fetch_items: {rows} items fetched")

        for r in range(1, rows + 1):
            title = driver.find_element(
                by=By.XPATH, value=f'//*[@id="resptable-1"]/tbody/tr[{r}]/td[4]'
            ).text

            metadata = ""
            author = ""
            if " / " in title:
                title, author = title.split(" / ", 1)
                if "\n" in author:
                    author, metadata = author.split("\n", 1)
            else:
                if "\n" in title:
                    title, metadata = title.split("\n", 1)

            _LOGGER.debug(
                f"{DOMAIN} - fetch_items: {title} # {author} # {metadata} fetched"
            )
            items.append(
                Item(
                    return_date=driver.find_element(
                        by=By.XPATH, value=f'//*[@id="resptable-1"]/tbody/tr[{r}]/td[2]'
                    ).text,
                    library=driver.find_element(
                        by=By.XPATH, value=f'//*[@id="resptable-1"]/tbody/tr[{r}]/td[3]'
                    ).text,
                    title=title,
                    author=author,
                    metadata=metadata,
                    extension=driver.find_element(
                        by=By.XPATH, value=f'//*[@id="resptable-1"]/tbody/tr[{r}]/td[5]'
                    ).text,
                )
            )

        driver.quit()
        return items

    def next_item(self):
        _LOGGER.debug(f"{DOMAIN} - next_item() called")
        if self.items and isinstance(self.items, list):
            return self.items[0]
        return None
