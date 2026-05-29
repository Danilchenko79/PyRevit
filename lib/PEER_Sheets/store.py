# -*- coding: utf-8 -*-
"""Per-project persistence for the level-sheet tool.

Stored in a JSON file tied to the active document (pyRevit
get_document_data_file), so choices survive between sessions for this model:

    slab_choices : { level.UniqueId : floor.UniqueId }
        Which floor a level's top elevation is read from when the level has
        several slabs. The elevation itself is always read fresh from that
        floor, so moving the slab is picked up automatically.

    elev_labels  : { level.UniqueId : custom text }
        Manual elevation text used in sheet names only (set via the Shift
        editor). Overrides the computed elevation string.

    titleblock   : title block FamilySymbol.UniqueId
        The title block chosen last time, pre-selected on the next run.

    sheets       : [ { "level_uids": [...], "kind": str, "sheet_uid": str } ]
        Which sheet (by UniqueId) this tool created for which logical level
        (the set of member levels' UniqueIds) and role. Lets the tool rename /
        renumber on PR_Level change and detect orphaned sheets.
"""

import os
import json
import codecs

from pyrevit import script

_FILE_ID = "level_sheets"
_FILE_EXT = "json"


def _path():
    return script.get_document_data_file(_FILE_ID, _FILE_EXT)


def _empty():
    return {"slab_choices": {}, "elev_labels": {}, "sheets": []}


def load():
    path = _path()
    if not os.path.isfile(path):
        return _empty()
    try:
        with codecs.open(path, "r", "utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("slab_choices", {})
    data.setdefault("elev_labels", {})
    data.setdefault("sheets", [])
    return data


def save(data):
    try:
        with codecs.open(_path(), "w", "utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False
