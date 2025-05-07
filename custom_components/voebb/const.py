"""Constants for the voebb integration."""

from datetime import timedelta

DOMAIN = "voebb"

SCAN_INTERVAL = timedelta(minutes=60)

URL = "https://www.voebb.de/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SPROD00"

DEFAULT_ICON = "mdi:library"

CONF_SELENIUM_HOST = "Hostname of remote selenium webserver"
CONF_SELENIUM_PORT = "Port to remote selenium webdriver"
default = CONF_SELENIUM_DEFAULT_PORT = "4444"
