"""Pytest configuration — ensure tests/ is on sys.path."""

import sys
import os

# Add tests/ dir to path so mock_cp4 can be imported
sys.path.insert(0, os.path.dirname(__file__))
# Add project root for pycrestron
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
