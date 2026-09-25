"""HTTP client for the VOEBB aDISWeb catalogue, no browser required."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import re
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)

URL = "https://www.voebb.de/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SPROD00"
TIMEOUT = aiohttp.ClientTimeout(total=30)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# aDISWeb binds its links and buttons to small JS handlers, e.g.
#   function fn2(e){ e.preventDefault(); top.htmlOnLink("*SBK");}
#   document.getElementById("idfn2")?.addEventListener("click", fn2, false);
# which submit the page form with an extra hidden field set.
_LISTENER_RE = re.compile(
    r'getElementById\("(?P<id>[^"]+)"\)\?\.addEventListener\("click",\s*(?P<fn>\w+)'
)
_DATE_RE = re.compile(r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})")
_FUNCTION_RE = r"function\s+{fn}\s*\([^)]*\)\s*\{{(?P<body>[^}}]*)\}}"
_LINK_RE = re.compile(r"htmlOnLink\(\s*[\"'](?P<code>[^\"']*)[\"']")
_BUTTON_RE = re.compile(
    r"mjsOnScriptButtonClicked\(\s*\w+\s*,\s*'[^']*'\s*,\s*'(?P<field>[^']*)'"
)
_INTERNAL_LINK_RE = re.compile(
    r"mjsOnInternalLinkClicked\(\s*\w+\s*,\s*'(?P<field>[^']*)'"
)
_RENEWALS_RE = re.compile(r"(?P<count>\d+)\s+Verlängerung")
# Notes on items that can't be renewed (yet), also not twice on the same day
_RENEWAL_BLOCKED = ("nicht möglich", "nicht verlängerbar", "Heute verlängert")

# Submit buttons on the Ausleihen page, "Alle verlängern" isn't used
RENEW_BUTTON = "Markierte Medien verlängern"
CHECK_BUTTON = "Markierte Medien verlängerbar?"


class VoebbError(Exception):
    """Base error for the VOEBB client."""


class CannotConnect(VoebbError):
    """The VOEBB website could not be reached or returned an unexpected page."""


class InvalidAuth(VoebbError):
    """The VOEBB credentials were rejected."""


class UnknownItem(VoebbError):
    """An item to renew isn't borrowed by the account."""


@dataclass
class Item:
    title: str
    author: str
    library: str
    call_number: str
    barcode: str
    return_date: date | None
    renewals: int
    # True when VOEBB says a renewal isn't possible (yet). False doesn't mean a
    # renewal is possible, VOEBB only tells that when asked with check_only
    renewal_blocked: bool
    extension: str


@dataclass
class Account:
    items: list[Item]
    # None when the account page couldn't be read
    ready_for_pickup: int | None
    reservations: int | None
    # Orders of items from the closed stacks ("Magazin")
    orders: int | None
    pickup_code: str | None
    card_valid_until: date | None


@dataclass
class RenewResult:
    barcode: str
    title: str
    return_date: date | None
    # Renewed, or renewable when only checked
    success: bool
    # The note of VOEBB about the renewal
    message: str


def _attr(element: Tag, name: str) -> str:
    """Return an HTML attribute as string, empty if missing."""
    value = element.get(name)
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


class Page:
    """A fetched aDISWeb page and the form that drives navigation on it."""

    def __init__(self, url: str, html: str) -> None:
        self.url = url
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")

    @property
    def error_message(self) -> str | None:
        for element in self.soup.select(".fehler, .error, [role=alert]"):
            if text := element.get_text(" ", strip=True):
                return text
        return None

    @property
    def is_logged_in(self) -> bool:
        button = self.soup.find("input", attrs={"name": "SUO1_AUTHFU_1"})
        return button is not None and _attr(button, "value") == "Abmelden"

    def form(self) -> tuple[str, dict[str, str]]:
        """Return the action URL and hidden fields of the page form."""
        form = self.soup.find("form")
        if form is None:
            raise CannotConnect(f"No form found on {self.url}")
        data = {
            _attr(field, "name"): _attr(field, "value")
            for field in form.find_all("input", attrs={"type": "hidden"})
            if _attr(field, "name")
        }
        # Mirrors prepareFormSubmission() in aDISMain.js
        if "scriptEnabled" in data:
            data["scriptEnabled"] = "true"
        return urljoin(self.url, _attr(form, "action")), data

    def action_for(self, element: Tag) -> dict[str, str]:
        """Return the form fields a click on element would submit."""
        code = f"{_attr(element, 'onclick')} {_attr(element, 'href')}"
        if element_id := _attr(element, "id"):
            for match in _LISTENER_RE.finditer(self.html):
                if match["id"] == element_id:
                    body = re.search(
                        _FUNCTION_RE.format(fn=re.escape(match["fn"])), self.html
                    )
                    if body:
                        code += " " + body["body"]
        if link := _LINK_RE.search(code):
            return {"keyCode": "0", "selected": f"ZTEXT       {link['code']}"}
        if button := _BUTTON_RE.search(code) or _INTERNAL_LINK_RE.search(code):
            return {button["field"]: "pressed"}
        if element.name == "input" and (name := _attr(element, "name")):
            return {name: _attr(element, "value")}
        raise CannotConnect(f"Don't know how to click {element} on {self.url}")

    def find_link(self, text: str) -> Tag | None:
        """Return the first link whose text or title contains text."""
        for link in self.soup.find_all("a"):
            if text in link.get_text(" ", strip=True) or text in _attr(link, "title"):
                return link
        return None


class VoebbClient:
    """Log into VOEBB and read the borrowed items of an account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password

    async def _request(
        self,
        method: str,
        url: str,
        referer: str | None = None,
        data: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> Page:
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
            headers["Origin"] = "https://www.voebb.de"
        try:
            async with self._session.request(
                method, url, headers=headers, timeout=TIMEOUT, data=data
            ) as response:
                response.raise_for_status()
                return Page(str(response.url), await response.text())
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Request to {url} failed: {err}") from err

    async def _click(self, page: Page, element: Tag) -> Page:
        action, data = page.form()
        data.update(page.action_for(element))
        return await self._request("POST", action, referer=page.url, data=data)

    async def async_login(self) -> Page:
        """Log in and return the logged in start page."""
        page = await self._request("GET", URL)
        button = page.soup.find("input", attrs={"name": "SUO1_AUTHFU_1"})
        if button is None:
            raise CannotConnect("Login button not found")
        page = await self._click(page, button)
        _LOGGER.debug("Navigated to login page %s", page.url)

        password = page.soup.find("input", attrs={"name": "LPASSW"})
        form = password.find_parent("form") if password else None
        if form is None:
            raise CannotConnect("Login form not found")
        page = await self._request(
            "POST",
            urljoin(page.url, _attr(form, "action")),
            referer=page.url,
            data={
                "L#AUSW": self._username,
                "LPASSW": self._password,
                "LLOGIN": "Login",
            },
        )

        if not page.is_logged_in:
            raise InvalidAuth(page.error_message or f"Not logged in at {page.url}")
        _LOGGER.debug("Auth succeeded")
        return page

    async def async_logout(self, page: Page) -> None:
        """End the session, errors are ignored."""
        if link := page.find_link("Sitzung beenden"):
            try:
                await self._click(page, link)
            except VoebbError as err:
                _LOGGER.debug("Logout failed: %s", err)

    async def _async_open_account(self) -> tuple[Page, Page | None]:
        """Log in, return the account overview and the Ausleihen page if any."""
        page = await self.async_login()

        account_link = page.find_link("Mein Konto")
        if account_link is None:
            raise CannotConnect("'Mein Konto' link not found")
        page = await self._click(page, account_link)
        _LOGGER.debug("Selected Mein Konto")

        # Without loans the entry is plain text instead of a link
        if page.soup.find(string=re.compile("Keine Ausleihen")):
            return page, None
        borrow_link = page.find_link("Ausleihen")
        if borrow_link is None:
            raise CannotConnect("'Ausleihen' link not found")
        loans = await self._click(page, borrow_link)
        _LOGGER.debug("Selected Ausleihen")
        return page, loans

    async def async_fetch_account(self) -> Account:
        """Return the borrowed items and the account overview."""
        overview, loans = await self._async_open_account()
        try:
            items = parse_items(loans.soup) if loans else []
            account = parse_account(overview.soup, items)
        finally:
            await self.async_logout(loans or overview)
        _LOGGER.debug("%d items fetched", len(account.items))
        return account

    async def async_renew(
        self, barcodes: list[str] | None = None, check_only: bool = False
    ) -> tuple[list[RenewResult], list[Item]]:
        """Renew items by barcode, all borrowed items when None.

        With check_only VOEBB is only asked whether the items can be renewed.
        Also returns the borrowed items as shown afterwards.
        """
        overview, loans = await self._async_open_account()
        page = loans or overview
        try:
            rows = _parse_rows(page.soup) if loans else []
            before = {item.barcode: (item, checkbox) for item, checkbox in rows}
            wanted = list(before) if barcodes is None else barcodes
            if unknown := [barcode for barcode in wanted if barcode not in before]:
                raise UnknownItem(", ".join(unknown))
            if not wanted:
                return [], parse_items(page.soup) if loans else []

            label = CHECK_BUTTON if check_only else RENEW_BUTTON
            button = page.soup.find("input", attrs={"type": "submit", "value": label})
            if button is None:
                raise CannotConnect(f"'{label}' button not found")
            action, data = page.form()
            # What a click on the button submits, see mjsInitButtonForElement()
            fields = [
                *data.items(),
                *(("$RTable_checkbox[]", before[barcode][1]) for barcode in wanted),
                (_attr(button, "name"), "pressed"),
                ("source", "$B"),
                ("focus", _attr(button, "data-fld")),
            ]
            page = await self._request("POST", action, referer=page.url, data=fields)
            _LOGGER.debug("Pressed %s for %s", label, wanted)
            items = parse_items(page.soup)
        finally:
            await self.async_logout(page)

        after = {item.barcode: item for item in items}
        results = []
        for barcode in wanted:
            old = before[barcode][0]
            new = after.get(barcode, old)
            if check_only:
                success = not new.renewal_blocked
            else:
                # A renewal moves the return date
                success = bool(
                    old.return_date
                    and new.return_date
                    and new.return_date > old.return_date
                )
            results.append(
                RenewResult(
                    barcode=barcode,
                    title=new.title,
                    return_date=new.return_date,
                    success=success,
                    message=new.extension,
                )
            )
        return results, items


def _cell_text(cell: Tag) -> str:
    """Return the text of a table cell like a browser renders it."""
    for br in cell.find_all("br"):
        br.replace_with("\n")
    lines = (" ".join(line.split()) for line in cell.get_text().split("\n"))
    return "\n".join(line for line in lines if line)


def _parse_date(text: str) -> date | None:
    """Parse the first dd.mm.yyyy date in text."""
    if match := _DATE_RE.search(text):
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    _LOGGER.warning("Could not parse date %r", text)
    return None


def _count(soup: BeautifulSoup, noun: str) -> int | None:
    """Count of an entry of the account overview, e.g. "Keine Vormerkungen"."""
    if soup.find(string=re.compile(f"Keine {noun}")):
        return 0
    # The navigation has plain links like "Bestellungen", so a number is required
    count = re.compile(rf"(?P<count>\d+)\s+{noun}")
    if (text := soup.find(string=count)) and (match := count.search(str(text))):
        return int(match["count"])
    return None


def parse_account(soup: BeautifulSoup, items: list[Item]) -> Account:
    """Parse the account overview."""
    # "Ausweis gültig bis", "Abholcode" etc. are a definition list
    values = {
        term.get_text(" ", strip=True): value.get_text(" ", strip=True)
        for term in soup.find_all("dt")
        if (value := term.find_next_sibling("dd"))
    }
    card_valid_until = values.get("Ausweis gültig bis")
    return Account(
        items=items,
        ready_for_pickup=_count(soup, "Bereitstellung"),
        reservations=_count(soup, "Vormerkung"),
        orders=_count(soup, "Bestellung"),
        pickup_code=values.get("Abholcode"),
        card_valid_until=_parse_date(card_valid_until) if card_valid_until else None,
    )


def parse_items(soup: BeautifulSoup) -> list[Item]:
    """Parse the Ausleihen table, sorted by return date."""
    items = [item for item, _ in _parse_rows(soup)]
    return sorted(items, key=lambda item: item.return_date or date.max)


def _parse_rows(soup: BeautifulSoup) -> list[tuple[Item, str]]:
    """Parse the Ausleihen table into items and the values of their checkboxes."""
    table = soup.find(id="resptable-1")
    if table is None:
        raise CannotConnect("Ausleihen table not found")
    body = table.find("tbody") or table

    rows = []
    for row in body.find_all("tr", recursive=False):
        cells = [_cell_text(cell) for cell in row.find_all("td", recursive=False)]
        if len(cells) < 5:
            # Shows when VOEBB changed the table
            _LOGGER.warning("Skipping unexpected row in the Ausleihen table: %s", cells)
            continue
        # "Title / Author", then the call number and the barcode on own lines.
        # "¬" marks articles that are skipped when sorting
        lines = cells[3].replace("¬", "").split("\n")
        barcode = lines.pop() if len(lines) > 1 and lines[-1].isdigit() else ""
        call_number = lines.pop() if len(lines) > 1 else ""
        # Instruments etc. start with their type, e.g. "[Musikinstrument]"
        if len(lines) > 1 and lines[0].startswith("[") and lines[0].endswith("]"):
            lines.pop(0)
        title, _, author = " ".join(lines).partition(" / ")
        renewals = _RENEWALS_RE.search(cells[4])
        checkbox = row.find("input", attrs={"type": "checkbox"})

        item = Item(
            return_date=_parse_date(cells[1]),
            library=cells[2],
            title=title,
            author=author,
            call_number=call_number,
            barcode=barcode,
            renewals=int(renewals["count"]) if renewals else 0,
            renewal_blocked=any(text in cells[4] for text in _RENEWAL_BLOCKED),
            extension=cells[4],
        )
        rows.append((item, _attr(checkbox, "value") if checkbox else ""))
    return rows
