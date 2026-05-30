# -*- coding: utf-8 -*-
"""AutoSections - reusable building blocks for the unique-section tool.

Runs on the ACTIVE PLAN VIEW and builds vertical sections at the windows of that
level. A window section is a thin (10 mm) slice at the window's plan position,
cropped between the lower window's head and this window's sill, so it shows only
the floor slab and the concrete wall between the stacked windows - the windows
themselves are cropped out.

Sections are built ONLY for unique "nodes" (wall thickness + slab thickness +
spandrel height). Repeated nodes do not get new views: a REFERENCE marker is
placed pointing back at the first, unique section.

Modules (each does one thing):
    convert     - unit conversion (ft <-> mm) and tolerance bucketing
    params      - shared BuiltInParameter reads
    collect     - gather windows/beams of a level, find ViewFamilyType / title block
    geometry    - section origin + look direction, oriented section box
    adjacency   - slab queries (thickness in a band; side context for beams)
    nodes       - turn an element into a section node (geometry + uniqueness key)
    signatures  - bucket elements by node key
    sections    - create the real sections + the reference markers (model-side)
    sheets      - lay the real views out on sheets in a grid
    ui          - category / per-sheet prompts (English UI)
"""
