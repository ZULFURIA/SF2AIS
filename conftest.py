"""Pytest configuration: add project root to sys.path for test imports."""
import os
import sys

# Add the project root (the directory containing this file) to sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
