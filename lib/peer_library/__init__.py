# -*- coding: utf-8 -*-
"""PEER family library: cloud/office folder of families with versions.

Modules without Revit API (run under CPython for tests):
    groups       library groups (folders)
    jsonio       json read/write, atomic replace
    config       %APPDATA%/PEER/library.json - backend, folder, cache, role
    rfa_info     Revit version of a .rfa without Revit, sha1
    checks_file  checks before opening a family: name, size, Revit version
    index        family card, index.json, changelog.json, version bump
    cache        local copy in %LOCALAPPDATA%/PEER/Library, sha1 check
    backend_base storage interface + errors
    backend_local storage on a plain folder (PEER-Library + PEER-Inbox)
    strings      every UI string in one place
    log          %APPDATA%/PEER/library.log

Revit modules (IronPython only): revit_family, loader, publish.
"""

FORMAT = 1           # library storage format (.peer-library)
