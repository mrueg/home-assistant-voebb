"""Constants for the voebb integration."""

from datetime import timedelta

DOMAIN = "voebb"

SCAN_INTERVAL = timedelta(seconds=900)

URL = "https://www.voebb.de/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SPROD00"

DEFAULT_ICON ="mdi:library"
