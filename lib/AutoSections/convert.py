# -*- coding: utf-8 -*-
"""Unit conversion and tolerance bucketing.

Revit stores lengths internally in feet. Everything user-facing in this tool is
in millimetres, so all the size logic lives in mm and only crosses back to feet
when it touches the API (section box, crop, marker tails).
"""

FT = 0.3048          # 1 ft = 0.3048 m
MM_PER_FT = FT * 1000.0
TOL = 50.0           # mm bucket: sizes within one bucket count as "the same"


def mm(ft_value):
    """Feet -> millimetres."""
    return ft_value * MM_PER_FT


def to_ft(mm_value):
    """Millimetres -> feet."""
    return mm_value / MM_PER_FT


def round_to(value_mm, tol=TOL):
    """Snap a mm value to a tolerance bucket so near-equal sizes group together."""
    return int(round(value_mm / tol) * tol)
