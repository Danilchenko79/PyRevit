# -*- coding: utf-8 -*-
"""RAModel: Revit analytical model -> Robot Structural Analysis.

Modules:
    config        rule settings (JSON in %APPDATA%\\RAModel)
    util          units, comment tags, small helpers
    geom          geometry (everything in feet, as inside Revit)
    levels        slab axes the model is snapped to
    align         alignment of wall axes, columns, joints and beams
    physical      collection and parsing of physical elements
    builder       rule-based analytical model generation
    snapshot      analytical model snapshot for checks
    checks        checks of the physical and analytical model
    fixes         analytical model auto-fixes
    report        reference report and CSV
    robot_export  direct export to Robot via COM (RobotOM)
"""
VERSION = '1.1'

# Tag in "Comments" of everything the tool creates.
TAG = 'RA:'
