"""Prepared bounded validation; OFF until its exact arm and expiry are configured.

No startup registration: preparing this module cannot dispatch a provider call.
Existing 15-second QA approval/run marker remains separate and unchanged.
"""
import os
from . import live_gemini_smoke as smoke

RUN = 'gmlqa20261023-10s'
FIXTURES = {
    'id': 'a76e081d3a1b128c8ee1b9f66befa21b30b15a6690579304c36330b85e5f4019',
    'en': 'f04c50fd63dc716418edeb80f09153079a8718d107dd2055927d21528323eed9',
}


def run():
    if os.environ.get(smoke.ARM) != RUN:
        return
    # Changes apply solely in this explicitly launched, short-lived QA child.
    smoke.RUN = RUN
    smoke.INPUT_MS = 10000
    smoke.FIXTURE_DIRECTORY = 'gemini_live_synthetic_10s'
    smoke.FIXTURES = FIXTURES
    smoke.run()


if __name__ == '__main__':
    run()
