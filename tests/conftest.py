"""Pytest configuration — ensure tests/ and src/ are on sys.path."""

import sys
import os

# Add tests/ dir to path so mock_cp4 can be imported
sys.path.insert(0, os.path.dirname(__file__))
# Add src/ for pycrestron package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
