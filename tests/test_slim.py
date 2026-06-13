"""Tests for the slim helpers (run: python tests\\test_slim.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.slim import title_case


def test_title_case():
    cases = {
        "TAYLOR CREEK PARK": "Taylor Creek Park",
        "ST. ANDREW'S PLAYGROUND": "St. Andrew's Playground",
        "HIGH PARK": "High Park",
        "CHRISTIE PITS": "Christie Pits",
        "DUFFERIN GROVE PARK (NORTH)": "Dufferin Grove Park (North)",
        "MOUNT PLEASANT-DAVISVILLE": "Mount Pleasant-Davisville",
        "LOWER DON PARKLANDS/TRAIL": "Lower Don Parklands/Trail",
    }
    for raw, expected in cases.items():
        got = title_case(raw)
        assert got == expected, f"{raw!r}: expected {expected!r}, got {got!r}"
    print(f"test_title_case: {len(cases)} cases OK")


if __name__ == "__main__":
    test_title_case()
