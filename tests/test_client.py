"""Test the HTTP flow of the VOEBB client against captured pages."""

from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path

import aiohttp
from aioresponses import aioresponses
import pytest
from yarl import URL

from custom_components.voebb.api import (
    URL as START,
    CannotConnect,
    InvalidAuth,
    UnknownItem,
    VoebbClient,
)

from .conftest import PASSWORD, USERNAME

FIXTURES = Path(__file__).parent / "fixtures"

APP = "https://www.voebb.de/aDISWeb/_testsessiontoken0000000000000000/app"
AUTHORIZE = "https://www.voebb.de/oidcp/authorize?client_id=adis001"
LOGINCHECK = "https://www.voebb.de/oidcp/logincheck"
LOGGED_IN = f"{APP}/prod00/1"

WRONG_PASSWORD = "Your password is incorrect."


def page(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def posts(mock: aioresponses, url: str) -> list[dict[str, str]]:
    """Return the form data of all POST requests to url."""
    return [call.kwargs["data"] for call in mock.requests[("POST", URL(url))]]


@pytest.fixture
def mock_http() -> Generator[aioresponses]:
    with aioresponses() as mock:
        yield mock


@pytest.fixture
async def client() -> AsyncGenerator[VoebbClient]:
    async with aiohttp.ClientSession() as session:
        yield VoebbClient(session, USERNAME, PASSWORD)


def mock_login(mock: aioresponses, login_result: str = "logged_in") -> None:
    """Serve the pages up to the logged in start page, like voebb.de does."""
    mock.get(START, body=page("start"))
    mock.post(APP, status=302, headers={"Location": AUTHORIZE})
    mock.get(AUTHORIZE, body=page("login"))
    if login_result == "logged_in":
        mock.post(LOGINCHECK, status=302, headers={"Location": LOGGED_IN})
        mock.get(LOGGED_IN, body=page("logged_in"))
    else:
        mock.post(LOGINCHECK, body=login_result)


async def test_fetch_no_loans(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test an account without loans, on the real pages."""
    mock_login(mock_http)
    mock_http.post(APP, body=page("account_no_loans"))
    mock_http.post(APP, body=page("start"))

    account = await client.async_fetch_account()

    assert account.items == []
    # From the account overview
    assert account.ready_for_pickup == 0
    assert account.reservations == 0
    # Not confused with the "Bestellungen" link of the navigation
    assert account.orders == 0
    assert account.pickup_code == "12 Mu"
    assert account.card_valid_until == date(2027, 12, 31)

    login, account, logout = posts(mock_http, APP)
    # The login button, then the links as their JavaScript handlers submit them
    assert login["$ScriptButton"] == "pressed"
    assert login["identity"] == "testidentity"
    assert login["scriptEnabled"] == "true"
    assert account["selected"] == "ZTEXT       *SBK"
    assert logout["selected"] == "ZTEXT       *SE"
    assert posts(mock_http, LOGINCHECK) == [
        {"L#AUSW": USERNAME, "LPASSW": PASSWORD, "LLOGIN": "Login"}
    ]


async def test_fetch_items(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test an account with loans."""
    mock_login(mock_http)
    mock_http.post(APP, body=page("account_with_loans"))
    mock_http.post(APP, body=page("loans"))
    mock_http.post(APP, body=page("start"))

    account = await client.async_fetch_account()
    items = account.items
    assert account.ready_for_pickup == 0

    assert [(item.title, item.return_date) for item in items] == [
        ("Geige Modell A 1/4 : [Musikinstrument]", date(2026, 10, 14)),
        ("Geige Modell A 1/8 : [Musikinstrument]", date(2026, 10, 15)),
        ("Der lange Wintertag : sieben kleine Mäuse im Schnee", date(2026, 10, 23)),
        ("Das Beispielhorn und der Geburtstag", date(2026, 10, 23)),
        ("Wir beide - Die große Reise", date(2026, 10, 23)),
    ]
    violin, _, book, _, illustrated = items
    # Instruments have their type on an own line and no author
    assert violin.author == ""
    assert violin.call_number == "Mus 400 VIOL"
    assert violin.barcode == "00000000011"
    assert violin.library == "Mitte: Stadtbibliothek Beispiel"
    assert (violin.renewals, violin.renewal_blocked, violin.extension) == (0, False, "")

    assert book.author == (
        "Erika Beispiel ; Max Muster. Aus dem Japan. übers. von Berta Beispiel"
    )
    assert (book.call_number, book.barcode) == ("1.2 LANG", "00000000013")
    # Can't be renewed twice on the same day
    assert (book.renewals, book.renewal_blocked) == (1, True)
    assert book.extension == "Heute verlängert\n1 Verlängerung"
    assert illustrated.author == "Erika Beispiel ; Max Muster [Illustrator/in]"

    _, _, loans, logout = posts(mock_http, APP)
    assert loans["selected"] == "ZTEXT       *SZA"
    assert logout["selected"] == "ZTEXT       *SE"


def mock_loans(mock: aioresponses, result: str) -> None:
    """Serve the pages up to the Ausleihen page, then result and the logout."""
    mock_login(mock)
    mock.post(APP, body=page("account_with_loans"))
    mock.post(APP, body=page("loans"))
    mock.post(APP, body=result)
    mock.post(APP, body=page("start"))


async def test_renew_check(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test asking whether an item can be renewed, on the real result page."""
    mock_loans(mock_http, page("renew_check"))

    (result,), items = await client.async_renew(["00000000013"], check_only=True)

    assert result.barcode == "00000000013"
    assert result.title == "Der lange Wintertag : sieben kleine Mäuse im Schnee"
    assert result.return_date == date(2026, 10, 23)
    assert not result.success
    assert len(items) == 5
    assert result.message == (
        "nicht verlängerbar : Verlängerung noch nicht möglich- Stand 25.09.2026\n"
        "1 Verlängerung"
    )

    check = mock_http.requests[("POST", URL(APP))][3].kwargs["data"]
    # The selected row and what a click on the check button submits
    assert ("$RTable_checkbox[]", "CheckCell_1") in check
    assert ("$Button$2", "pressed") in check
    assert ("source", "$B") in check
    assert ("focus", "$$GFBO_7") in check
    assert not any(field.startswith(("$Button$0", "$Button$1")) for field, _ in check)


async def test_renew(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test renewing items."""
    # The page after a successful renewal wasn't captured yet, VOEBB shows the
    # Ausleihen page again with the new return dates
    renewed = page("loans").replace("14.10.2026", "11.11.2026")
    mock_loans(mock_http, renewed)

    (violin, book), items = await client.async_renew(["00000000011", "00000000013"])

    assert (violin.success, violin.return_date) == (True, date(2026, 11, 11))
    assert (book.success, book.return_date) == (False, date(2026, 10, 23))
    # The borrowed items as VOEBB shows them after renewing
    assert items[-1].return_date == date(2026, 11, 11)

    renew = mock_http.requests[("POST", URL(APP))][3].kwargs["data"]
    assert [value for field, value in renew if field == "$RTable_checkbox[]"] == [
        "CheckCell",
        "CheckCell_1",
    ]
    assert ("$Button$1", "pressed") in renew
    assert ("focus", "$$GFBO_4") in renew


async def test_renew_all(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test all borrowed items are selected when no barcodes are given."""
    mock_loans(mock_http, page("renew_check"))

    results, _ = await client.async_renew(check_only=True)

    # The violins can be renewed, the books were checked or renewed today
    assert [result.success for result in results] == [True, True, False, False, False]
    check = mock_http.requests[("POST", URL(APP))][3].kwargs["data"]
    assert [value for field, value in check if field == "$RTable_checkbox[]"] == [
        "CheckCell",
        "CheckCell_0",
        "CheckCell_1",
        "CheckCell_2",
        "CheckCell_3",
    ]


async def test_renew_unknown_item(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test nothing is submitted for items that aren't borrowed."""
    mock_login(mock_http)
    mock_http.post(APP, body=page("account_with_loans"))
    mock_http.post(APP, body=page("loans"))
    mock_http.post(APP, body=page("start"))

    with pytest.raises(UnknownItem, match="00000000099"):
        await client.async_renew(["00000000099"])

    *_, logout = posts(mock_http, APP)
    assert logout["selected"] == "ZTEXT       *SE"


async def test_renew_no_loans(mock_http: aioresponses, client: VoebbClient) -> None:
    mock_login(mock_http)
    mock_http.post(APP, body=page("account_no_loans"))
    mock_http.post(APP, body=page("start"))

    assert await client.async_renew() == ([], [])


async def test_invalid_auth(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test the error message of the login page is passed on."""
    # The login page shows errors in a "fehler" box above the form
    rejected = page("login").replace(
        '<div class="form-primary-inside">',
        '<div class="form-primary-inside"><div class="widget hinweis fehler">'
        f"<span>{WRONG_PASSWORD}</span></div>",
    )
    mock_login(mock_http, login_result=rejected)

    with pytest.raises(InvalidAuth, match=WRONG_PASSWORD):
        await client.async_fetch_account()


async def test_website_down(mock_http: aioresponses, client: VoebbClient) -> None:
    mock_http.get(START, status=503)

    with pytest.raises(CannotConnect):
        await client.async_fetch_account()


async def test_unexpected_page(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test a changed website is reported instead of crashing."""
    mock_http.get(START, body="<html><body>Wartungsarbeiten</body></html>")

    with pytest.raises(CannotConnect, match="Login button not found"):
        await client.async_fetch_account()


async def test_account_counts(mock_http: aioresponses, client: VoebbClient) -> None:
    """Test the counts of the account overview."""
    # Only "Keine …" was seen on the real page so far
    overview = (
        page("account_no_loans")
        .replace("Keine Bereitstellungen", "2 Bereitstellungen")
        .replace("Keine Vormerkungen", "3 Vormerkungen")
        .replace("Keine Bestellungen (Magazin)", "1 Bestellung (Magazin)")
    )
    mock_login(mock_http)
    mock_http.post(APP, body=overview)
    mock_http.post(APP, body=page("start"))

    account = await client.async_fetch_account()

    assert (account.ready_for_pickup, account.reservations, account.orders) == (
        2,
        3,
        1,
    )
