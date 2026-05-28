# -*- coding: utf-8 -*-
__title__ = "Create Worksets"                           # Name of the button displayed in Revit UI
__doc__ = """
Creating default worksets with the Construction workset 
also generates filters for coordination view templates and replaces them with PEER Work and PEER Work SEC.

"""


# EXTRA: You can remove them.
__author__ = "Dima D"                                       # Script's Author
                                      # Limit your Scripts to certain Revit versions if it's not compatible due to RevitAPI Changes.
# __context__     = ['Walls', 'Floors', 'Roofs']                # Make your button available only when certain categories are selected. Or Revit/View Types.

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ ⬇️ IMPORTS
# ==================================================
# Regular + Autodesk
import os, sys, math, datetime, time                                    # Regular Imports
from Autodesk.Revit.DB import *                                         # Import everything from DB (Very good for beginners)
from Autodesk.Revit.DB import Transaction, FilteredElementCollector     # or Import only classes that are used.
from Autodesk.Revit.UI.Selection import Selection
from Autodesk.Revit.UI.Selection import ObjectType




# pyRevit
from pyrevit import revit, forms                                        # import pyRevit modules. (Lots of useful features)

# Custom Imports
from Samples import CreateFilters
from Snippets._selection import get_selected_elements                   # lib import
from Snippets._convert import convert_internal_to_m                     # lib import

# .NET Imports
import clr                                  # Common Language Runtime. Makes .NET libraries accessinble
clr.AddReference("System")                  # Refference System.dll for import.
from System.Collections.Generic import List # List<ElementType>() <- it's special type of list from .NET framework that RevitAPI requires
# List_example = List[ElementId]()          # use .Add() instead of append or put python list of ElementIds in parentesis.

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ 📦 VARIABLES
# ==================================================
doc   = __revit__.ActiveUIDocument.Document   #type:Document
uidoc = __revit__.ActiveUIDocument            #type:UIDocument
app   = __revit__.Application                 # Represents the Autodesk Revit Application, providing access to documents, options and other application wide data and settings.
PATH_SCRIPT = os.path.dirname(__file__)     # Absolute path to the folder where script is placed.

# GLOBAL VARIABLES

# - Place global variables here.

# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ 🧬 FUNCTIONS
# ==================================================

# - Place local functions here. If you might use any functions in other scripts, consider placing it in the lib folder.

# ╔═╗╦  ╔═╗╔═╗╔═╗╔═╗╔═╗
# ║  ║  ╠═╣╚═╗╚═╗║╣ ╚═╗
# ╚═╝╩═╝╩ ╩╚═╝╚═╝╚═╝╚═╝ ⏹️ CLASSES
# ==================================================

# - Place local classes here. If you might use any classes in other scripts, consider placing it in the lib folder.

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ 🎯 MAIN
# ==================================================
# -*- coding: utf-8 -*-
# Создание ворксетов из списка имён (pyRevit / RevitPythonShell)
# Автор: ChatGPT (GPT-5 Thinking)


import re

# --- Revit API ---
from Autodesk.Revit.DB import (
    Transaction, Workset, WorksetKind, FilteredWorksetCollector
)


# ====== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ ======
# Задайте здесь список ворксетов, которые нужно создать:
WORKSET_NAMES = [
    u"+AR Link",
    u"+ST Link",
    u"+ME Link",
    u"+EL Link",
    u"+PL Link",
    u"+LS Link",
    u"+CO Link",
    u"Construction",
]

# Включать ли Worksharing автоматически, если он выключен:
AUTO_ENABLE_WORKSHARING = True

# Имена дефолтных ворксетов при автовключении Worksharing:
DEFAULT_WS_LEVELS_GRIDS = u"Shared Levels and Grids"
DEFAULT_WS_WORKSET1 = u"Workset1"
# ====================================


def is_workshared(document):
    try:
        return document.IsWorkshared
    except:
        return False


def ensure_worksharing(document, auto_enable=True):
    """Включает worksharing при необходимости (создаёт два дефолтных ворксета)."""
    if is_workshared(document):
        return False  # уже включен
    if not auto_enable:
        raise Exception(u"В этом файле не включён Worksharing. Включите его вручную или установите AUTO_ENABLE_WORKSHARING=True.")
    # Включаем worksharing (создаст два дефолтных ворксета)
    document.EnableWorksharing(DEFAULT_WS_LEVELS_GRIDS, DEFAULT_WS_WORKSET1)
    return True


def sanitize_name(name):
    """Удаляет недопустимые символы и приводит к аккуратному виду."""
    if name is None:
        name = u"Workset"
    name = name.strip()
    # Заменим недопустимые в Revit/Windows символы на подчёркивания
    # (для подстраховки: / \\ : ; * ? " < > | и управляющие)
    name = re.sub(ur'[\/\\\:\;\*\?\"\<\>\|\x00-\x1F]', u"_", name)
    # Убираем повторяющиеся подчёркивания
    name = re.sub(ur'_+', u'_', name)
    # Не допускаем пустое имя
    if not name:
        name = u"Workset"
    return name


def collect_existing_user_worksets(document):
    """Возвращает множество имён пользовательских ворксетов."""
    return set(ws.Name for ws in FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset))


def create_worksets(document, names):
    """Создаёт ворксеты из списка строк. Возвращает словарь с итогом."""
    if document.IsFamilyDocument:
        raise Exception(u"Открыт файл семейства. Ворксеты доступны только в проектных файлах (RVT).")

    # Включаем worksharing при необходимости
    was_enabled_now = ensure_worksharing(document, AUTO_ENABLE_WORKSHARING)

    existing = collect_existing_user_worksets(document)
    created = []
    skipped = []  # существовали или пустые после санитизации
    errors = []

    t = Transaction(document, "Create Worksets from List")
    t.Start()
    try:
        for raw in names:
            if raw is None:
                continue
            base = sanitize_name(unicode(raw))
            if not base:
                continue

            # если ворксет уже существует, просто пропускаем
            if base in existing:
                skipped.append(base)
                continue

            try:
                Workset.Create(document, base)
                existing.add(base)
                created.append(base)
            except Exception as ex:
                errors.append((base, unicode(ex)))
        t.Commit()
    except Exception as ex:
        t.RollBack()
        raise
    return {
        "worksharing_enabled_now": was_enabled_now,
        "created": created,
        "skipped": skipped,
        "errors": errors
    }


def main():
    try:
        result = create_worksets(doc, WORKSET_NAMES)
        msg_lines = []
        if result["worksharing_enabled_now"]:
            msg_lines.append(u"Worksharing was disabled and has been enabled automatically.")
        if result["created"]:
            msg_lines.append(u"Created worksets: {}".format(u"; ".join(result["created"])))
        if result["skipped"]:
            msg_lines.append(u"Skipped (already existed): {}".format(u"; ".join(result["skipped"])))
        if result["errors"]:
            msg_lines.append(u"Errors (name → message):")
            for name, err in result["errors"]:
                msg_lines.append(u"  • {} → {}".format(name, err))
        if not msg_lines:
            msg_lines.append(u"Nothing to create. Check the list of names.")
        print(u"\n".join(msg_lines))
    except Exception as e:
        print(u"[ERROR] {}".format(unicode(e)))


if __name__ == "__main__":
    main()
CreateFilters.run()
