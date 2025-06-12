# -*- coding: utf-8 -*-
__title__   = "Rebar Shape 14"
__doc__     = """Version = 1.0"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#==================================================
from Autodesk.Revit.DB import *

#.NET Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List



from pyrevit import script
from PlaceFamily import load_and_place

FAMILY_NAME = "PEER_Rebar_Shape 14"
load_and_place(FAMILY_NAME)
