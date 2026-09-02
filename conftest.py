"""Put the repository root on sys.path for the Home Assistant layer tests.

pytest inserts the directory containing a test file, not the repository
root, so `custom_components.glkvm` is not importable without this. The pure
tests do not need it - they load the client by path on purpose - but the
config flow and entity tests import the package properly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
