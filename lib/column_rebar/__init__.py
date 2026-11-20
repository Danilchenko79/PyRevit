# -*- coding: utf-8 -*-
"""Column reinforcement without Revit API (IronPython 2.7 and CPython).

    rules     what reinforcement a section gets: totals, stirrup, ties
    grouping  columns -> table rows (groups), marks and mark ranges
    layout    where each section goes on the drafting view

All lengths are millimetres. The Revit script converts at its edge.
Tests:  py -3 -m unittest discover -s lib/column_rebar/tests
"""
