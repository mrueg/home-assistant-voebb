"""Constants for the voebb integration."""

from datetime import timedelta

DOMAIN = "voebb"


# We don't want to hammer the website
UPDATE_INTERVAL = timedelta(hours=6)
