"""Test parsing of the VOEBB pages."""

from datetime import date

from bs4 import BeautifulSoup
import pytest

from custom_components.voebb.api import Page, parse_items

# Cell formats as seen on the real Ausleihen page
TABLE = """
<table id="resptable-1"><thead><tr><th>x</th></tr></thead><tbody>
<tr><td></td><td>01.11.2026</td><td>Mitte</td><td>Nur Titel<br>DVD</td>
<td>Verlängerung noch nicht möglich- Stand 03.05.2026 1 Verlängerung</td></tr>
<tr><td><input type=checkbox></td><td>12.10.2026</td><td>Stadtbibliothek   Pankow</td>
<td>Der Titel / [Ill.: Muster, Max]<br>4.3/Tech 1128 TITE<br>00740849801</td>
<td>2 Verlängerungen</td></tr>
<tr><td></td><td>01.12.2026</td><td>Mitte</td><td>Ohne Signatur</td><td></td></tr>
</tbody></table>
"""

HOME = """
<form action="/aDISWeb/_abc/app" method="POST" name="Form0">
<input type="hidden" name="identity" value="xyz">
<input type="hidden" name="scriptEnabled" value="false">
<input id="onscriptbuttonScriptButton" type="button" name="SUO1_AUTHFU_1" value="Anmelden">
<a href="#" id="idfn2" title="Mein Konto"><span>Mein Konto</span></a>
</form>
<script>
function fn1(e) { e.preventDefault(); mjsOnScriptButtonClicked(e, 'SUO1_AUTHFU_1','$ScriptButton');}
function fn2(e){  e.preventDefault(); top.htmlOnLink("*SBK");}
document.getElementById("onscriptbuttonScriptButton")?.addEventListener("click", fn1, false);
document.getElementById("idfn2")?.addEventListener("click", fn2, false);
</script>
"""


def test_parse_items() -> None:
    items = parse_items(BeautifulSoup(TABLE, "html.parser"))
    # Sorted by return date
    assert [(i.title, i.return_date) for i in items] == [
        ("Der Titel", date(2026, 10, 12)),
        ("Nur Titel", date(2026, 11, 1)),
        ("Ohne Signatur", date(2026, 12, 1)),
    ]
    first, second, third = items
    assert first.author == "[Ill.: Muster, Max]"
    assert first.call_number == "4.3/Tech 1128 TITE"
    assert first.barcode == "00740849801"
    assert first.library == "Stadtbibliothek Pankow"
    assert (first.renewals, first.renewal_blocked) == (2, False)
    assert first.extension == "2 Verlängerungen"

    assert second.author == ""
    assert (second.call_number, second.barcode) == ("DVD", "")
    assert (second.renewals, second.renewal_blocked) == (1, True)

    assert (third.call_number, third.barcode) == ("", "")
    assert (third.renewals, third.renewal_blocked) == (0, False)


def test_page_actions() -> None:
    page = Page("https://www.voebb.de/aDISWeb/app/prod00", HOME)
    action, data = page.form()
    assert action == "https://www.voebb.de/aDISWeb/_abc/app"
    assert data == {"identity": "xyz", "scriptEnabled": "true"}

    button = page.soup.find("input", attrs={"name": "SUO1_AUTHFU_1"})
    assert page.action_for(button) == {"$ScriptButton": "pressed"}
    assert page.action_for(page.find_link("Mein Konto")) == {
        "keyCode": "0",
        "selected": "ZTEXT       *SBK",
    }


def test_parse_unexpected_row(caplog: pytest.LogCaptureFixture) -> None:
    """Test rows the parser doesn't understand are logged."""
    table = TABLE.replace("</tbody>", "<tr><td>Neue Spalte</td></tr></tbody>")

    assert len(parse_items(BeautifulSoup(table, "html.parser"))) == 3
    assert "Skipping unexpected row in the Ausleihen table: ['Neue Spalte']" in (
        caplog.text
    )
