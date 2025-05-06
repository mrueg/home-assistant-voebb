from dataclasses import dataclass
from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType


from selenium import webdriver
from selenium.webdriver.common.by import By

import time

from .const import URL, DEFAULT_ICON


@dataclass
class Book:
    title: str
    author: str
    library: str
    metadata: str
    expiry: datetime
    extension: str

    @classmethod
    def from_dict(cls, source):
        timestamp = datetime.fromisoformat(source.get("expiry"))

        return cls(
            title=source["title"],
            author=source["author"],
            library=source["library"],
            metadata=source["metadata"],
            expiry=timestamp.strftime("%Y-%m-%d"),
            extension=source["extension"],
        )

    def to_dict(self):
        return {
            "title": self.title,
            "author": self.author,
            "library": self.library,
            "metadata": self.metadata,
            "expiry": self.expiry,
            "extension": self.extension,
        }

    def __hash__(self):
        return hash(tuple(sorted(self.to_dict().items())))

    def __lt__(self, other):
        return self.expiry < other.expiry


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
        self.books: list[Book] = []

    @property
    def name(self) -> str:
        return f"VOEBB: {self.username}"

    @property
    def unique_id(self) -> str:
        return f"voebb_{self.username}"

    @property
    def state(self) -> str:
        next_book = self.next_book()
        if next_book:
            return f"Next Book to return: {next_book.title} at {next_book.expiry}"
        return "N/A"

    @property
    def extra_state_attributes(self):
        return {"books": [book.to_dict() for book in self.books or []]}

    @property
    def icon(self) -> str:
        return DEFAULT_ICON

    def update(self):
        self.books = self.fetch_books()

    def fetch_books(self) -> list[Book]:
        books = []

        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=options)
        driver.get(URL)
        driver.implicitly_wait(2)
        login_button = driver.find_element(by=By.NAME, value="SUO1_AUTHFU_1")
        login_button.click()

        username_box = driver.find_element(by=By.ID, value="L#AUSW")
        username_box.send_keys(self.username)
        password_box = driver.find_element(by=By.ID, value="LPASSW")
        password_box.send_keys(self.password)
        login_button = driver.find_element(by=By.NAME, value="LLOGIN")
        login_button.click()
        account_link = driver.find_element(
            by=By.XPATH, value="//a[@title='Mein Konto']"
        )
        account_link.click()
        borrow_link = driver.find_element(by=By.LINK_TEXT, value="11 Ausleihen")
        borrow_link.click()
        rows = len(driver.find_elements(By.XPATH, '//*[@id="resptable-1"]/tbody/tr'))

        for r in range(1, rows + 1):
            title = driver.find_element(
                by=By.XPATH, value=f'//*[@id="resptable-1"]/tbody/tr[{r}]/td[4]'
            ).text

            title, author = title.split(" / ", 1)
            author, metadata = author.split("\n", 1)
            books.append(
                Book(
                    expiry=driver.find_element(
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

        return books.sort()

    def next_book(self):
        if self.books and isinstance(self.books, list):
            return self.books[0]
        return None
