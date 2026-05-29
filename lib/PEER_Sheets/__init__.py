# -*- coding: utf-8 -*-
"""PEER_Sheets - reusable building blocks for the level-based sheet creation tool.

Stage 1: create sheets per level driven by the shared parameter PR_Level.

Modules (each does one thing):
    levels   - read/write PR_Level, collect levels, previous-level lookup
    slabs    - find floors by reference level, top-of-slab elevation
    naming   - sheet name templates (Hebrew) + sheet number derivation
    creation - create the sheets, skipping existing numbers
    ui       - WPF windows (English UI)
"""
