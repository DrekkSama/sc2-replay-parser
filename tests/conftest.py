"""Pytest configuration for SC2 replay benchmarks."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--replay",
        action="store",
        default=None,
        help="Path to .SC2Replay file to parse and benchmark",
    )
    parser.addoption(
        "--parsed",
        action="store",
        default=None,
        help="Path to pre-parsed JSON file to benchmark",
    )