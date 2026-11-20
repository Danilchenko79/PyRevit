# -*- coding: utf-8 -*-
"""Every visible string of the library windows. One place = easy second language."""

APP = u'PEER Library'

# ---- statuses of a family against the open project --------------------------
ST_MISSING = u'Not in project'
ST_CURRENT = u'Up to date'
ST_OUTDATED = u'Project v{0} → library v{1}'
ST_UNKNOWN = u'In project, no version'
ST_NEWER = u'Project v{0} is newer than library v{1}'
ST_NEW = u'NEW'
ST_DEPRECATED = u'Deprecated'

# ---- library window ---------------------------------------------------------
TITLE_LIBRARY = u'PEER - Family library'
GROUP_ALL = u'All families'
GROUP_FAVORITES = u'★ Favorites'
GROUP_RECENT = u'Recently loaded'
FAV_ON = u'★ In favorites (click to remove)'
FAV_OFF = u'☆ Add to favorites'
BTN_UPDATE_ALL = u'Update all outdated ({0})'
UPDATE_ALL_ASK = (u'Update {0} families in this project to the library version?\n\n'
                  u'Parameter values changed in the project are kept.')
UPDATE_ALL_DONE = u'Updated {0} families.'
NOTE_NEEDED = u'Write what changed in this version (it goes to the history and What’s new).'
GROUP_POPULAR = u'Popular (90 days)'
GROUP_ATTENTION = u'⚠ Needs attention'
NEEDS = u'needs: {0}'
ALL_CATEGORIES = u'All Revit categories'
FILTER_CATALOG = u'With type catalog'
SORTS = [u'Sort: name', u'Sort: newest', u'Sort: popular']
STATS_LINE = u'Loaded {0} by {1} in 90 days'


def times(n):
    return u'once' if n == 1 else u'{0} times'.format(n)


def people(n):
    return u'1 person' if n == 1 else u'{0} people'.format(n)

TAB_PROJECT = u'This project'

# ---- requests / issues -------------------------------------------------------
BTN_REQUEST = u'Request a family…'
BTN_ISSUE = u'Report a problem…'
BTN_SEND = u'Send'
FILL_BOTH = u'Fill in both fields.'
TITLE_REQUEST = u'PEER - Request a family'
REQUEST_HEAD = u'Which family do you need?'
REQUEST_HINT = (u'The admins see the request in Inbox and answer in Library → My proposals. '
                u'Have a family file already? Use Propose family instead.')
REQUEST_L1 = u'What (e.g. "Pile cap 4 piles, chamfered")'
REQUEST_L2 = u'What for, project, deadline, examples'
REQUEST_SENT = u'Sent. The answer comes in Library → My proposals.'
TITLE_ISSUE = u'PEER - Report a problem'
ISSUE_HEAD = u'Problem with {0}'
ISSUE_HINT = u'Describe what is wrong; the admins fix it and publish a new version.'
ISSUE_L1 = u'Family'
ISSUE_L2 = u'What is wrong (view, parameter, type, project)'

# ---- admin in the library window --------------------------------------------------
ADMIN_HEADER = u'Admin'
BTN_EDIT_INFO = u'Edit info…'
BTN_NEW_VERSION = u'New version…'
ALL_DOCS = u'Also load into the other open projects ({0})'
OTHER_DOCS_FAILED = u'Loaded here, but not into:'
BTN_COLL_ADD = u'Add to collection…'
BTN_COLL_REMOVE = u'Remove from this collection'
BTN_DEPRECATE = u'Deprecate…'
MENU_COPY_ID = u'Copy ID'
RESTORE = u'restore'
RESTORE_TIP = u'Publish v{0} again as the next version (opens Publish with that file)'
RESTORE_NOTE = u'Restored v{0}: '
RESTORE_BAD = u'The stored file of v{0} is damaged - it cannot be restored.'
INFO_SAVED = u'Saved: {0} (no new version).'
NEW_COLLECTION = u'+ New collection…'
NEW_COLLECTION_PROMPT = u'Name of the new collection (e.g. "Foundations - start kit")'
COLL_ADDED = u'{0} added to "{1}".'
DEPRECATE_ASK = (u'Deprecate {0}? It disappears from the library window; projects keep it. '
                 u'Why (shown in the history):')
BTN_COLL_LOAD = u'Load collection ({0})'
COLL_LOAD_ASK = u'Load {0} families of this collection into the project?'
COLL_DONE = u'Loaded {0} families.'
COLL_NOTHING = u'Everything of this collection is already in the project.'
COLL_CATALOGS = u'With a type catalog - choose the types one by one: {0}'

# ---- this project --------------------------------------------------------------
BTN_PROJ_UPDATE = u'Update selected from library'
BTN_PROJ_PROPOSE = u'Propose selected to library…'
BTN_REFRESH = u'Refresh'
PROJ_SUMMARY = u'{0} families in the project · {1} from the library · {2} outdated'
PROJ_FILTERS = [u'All families', u'Need update', u'Not in the library', u'From the library']
PS_NOT_IN_LIBRARY = u'Not in the library'
PS_NO_VERSION = u'In library, project copy has no version'
PS_OUTDATED = u'Outdated - library has v{0}'
PS_NEWER = u'Newer than the library'
PS_CURRENT = u'Up to date'
PROJ_SELECT_LIBRARY = u'Select families that are in the library.'
PROJ_SELECT_ONE_NOTLIB = u'Select one family that is not in the library.'
PROJ_NOT_EDITABLE = u'This family cannot be exported (system or not editable).'

# ---- card info in Excel -----------------------------------------------------------
CSV_EXPORTED = u'{0} families written to {1}. Edit name / group / tags / description / help_url, ' \
               u'save as CSV, then "Info from Excel".'
CSV_NOTHING = u'No changes found in the file.'
CSV_ASK = u'Update the info of {0} families (no new versions, files are not touched)?\n\n{1}'
CSV_PROBLEMS = u'Skipped:'
CSV_DONE = u'Updated {0} families.'

# ---- kinds of proposals ------------------------------------------------------------
KIND_LABELS = {'new': u'New family', 'fix': u'Improvement', 'request': u'Request',
               'issue': u'Problem'}
GROUP_NEW = u'New (14 days)'
GROUP_IN_PROJECT = u'In this project'
GROUP_OUTDATED = u'Need update'
SEARCH_HINT = u'Search by name, ID or tag'
BTN_LOAD = u'Load'
BTN_LOAD_PLACE = u'Load and place'
BTN_UPDATE = u'Update'
BTN_UPDATE_PLACE = u'Update and place'
OVERWRITE = u'Overwrite parameter values in the project'
OVERWRITE_WARN = (u'Values changed in the project (dimensions, materials, text) will be '
                  u'replaced by the library values. Continue?')
RESET_FAILED = u'Could not reset the parameter values: {0}'

# ---- check before replacing a family in the project (load_check) ----
CHECK_BREAKS = u'Replacing it breaks something in this project'
CHECK_WARNINGS = u'Replacing it is possible - look at the notes first'
CHECK_CLEAN = u'Nothing in this project breaks'
CHECK_NO_FILE = u'The library file could not be read: {0}'
CHECK_NOT_EDITABLE = u'The family in the project cannot be opened - parameters were not compared.'
CHECK_NOT_LIBRARY = (u'This family in the project did not come from the library (no PEER_Version) - '
                     u'only its name is the same. The check finds data that breaks, not a different '
                     u'drawing: compare the two pictures.')
CHECK_RENAME_FAILED = u'Revit did not rename "{0}".'
LOAD_REFUSED = u'Revit refused the load: {0}'
CHECK_TITLE = u'PEER Library - before the update'
CHECK_HEAD = u'"{0}" is already in this project'
CHECK_PIC_PROJECT = u'In this project'
CHECK_PIC_LIBRARY = u'In the library'
CHECK_NO_PICTURE = u'no picture'
CHECK_LIST = u'What the update changes in this project (checked by a trial load that was undone)'
CHECK_NOTHING = u'Parameters, values, dimensions and tags stay as they are.'
CHECK_L_ERROR = u'Breaks'
CHECK_L_WARNING = u'Check'
CHECK_L_INFO = u'Note'
CHECK_BTN_UPDATE = u'Update'
CHECK_BTN_ANYWAY = u'Update anyway'
CHECK_BTN_ASIDE = u'Load next to it'
CHECK_BTN_CANCEL = u'Cancel'
CHECK_BTN_COPY = u'Copy report'
CHECK_COPIED = u'Copied'
CHECK_ASIDE_TIP = (u'The family in the project keeps its elements and values and is renamed to '
                   u'"<name> (project)". The library family is loaded next to it - switch '
                   u'elements to it when you are ready.')
CHECK_HINT_OK = (u'Update replaces the family in the project (Ctrl+Z undoes it). Load next to it '
                 u'changes nothing that is placed.')
CHECK_HINT_BREAKS = (u'Update anyway replaces the family and loses / deletes what is marked '
                     u'"Breaks" (Ctrl+Z undoes it). Load next to it keeps the project family as it '
                     u'is under another name and adds the library one - nothing placed changes.')
CHECK_ANYWAY_ASK = u'Replace the family and lose what is marked "Breaks"?'
CHECKING = u'Checking what the update of {0} changes in this project...'
CHECK_OK_STATUS = u'Checked: nothing in this project breaks.'
CHECK_CANCELLED = u'Not updated.'
CHECK_ASIDE_DONE = (u'The project family is now "{0}" (its elements are unchanged); {1} from the '
                    u'library is loaded next to it.')
CHECK_SKIPPED = u'Not replaced - they would break something or are not from the library ' \
                u'(open each one to see the check):'
CHECK_NOT_FROM_LIBRARY = u'in the project, but not from the library'
CHECK_FAILED_ASK = u'The check before the update did not work ({0}).\n\nUpdate without the check?'
FCHECK_TITLE = u'PEER - Check family'
FCHECK_ERRORS = u'Fix before publishing - it breaks schedules, tags or filters in projects'
FCHECK_WARNINGS = u'Usable - look at the notes'
FCHECK_CLEAN = u'No problems found'
FCHECK_LIST = u'What the check found (nothing in the family was changed)'
FCHECK_NOTHING = u'Parameters, names and types are in order.'
FCHECK_CLOSE = u'Close'
FCHECK_SUMMARY = u'{0} · {1} parameters ({2} shared) · {3} types'
FCHECK_SHARED_NOTE = u'Shared parameters checked against: {0}'
FCHECK_NO_SHARED = (u'No company shared parameter file found ({0}) - shared parameters were not '
                    u'compared. Set it in Revit (Manage > Shared Parameters) or in the library settings.')
FCHECK_PICK = (u'Select a family in the project (an element or a type), open a family, '
               u'or choose a folder of .rfa files to check them all.\n\nChoose a folder now?')
FCHECK_FOLDER = u'Folder with families to check'
FCHECK_FOLDER_HEAD = u'{0} families in {1}'
FCHECK_FOLDER_SUMMARY = u'{0} to fix, {1} with notes, {2} in order · full list: {3}'
FCHECK_PROGRESS = u'Checking {value} of {max_value}'
FCHECK_NOT_EDITABLE = u'This family cannot be opened (in-place or system family).'
FIX_BTN = u'Fix automatically ({0})'
FIX_FOLDER_BTN = u'Fix copies (up to {0} families)...'
FIX_FOLDER_TIP = (u'Old shared parameter names -> company names, family parameters -> company '
                  u'shared ones. Fixed copies go to another folder; the files here stay as they are.')
FIX_CHANGE_BTN = u'Change a parameter...'
FIX_CHANGE_TIP = (u'Pick a parameter: replace it with a company shared parameter, make it a family '
                  u'parameter, rename or delete it. Formulas and dimensions stay.')
FIX_DONE = u'{0} of {1} changes made. Save the family to keep them (Ctrl+Z undoes them).'
FIX_FAILED = u'Not done:'
FIX_PICK_PARAM = u'Parameter to change'
FIX_PICK_ACTION = u'What to do with "{0}"?'
FIX_A_SHARED = u'Replace with a company shared parameter'
FIX_A_FAMILY = u'Make it a family parameter'
FIX_A_RENAME = u'Rename'
FIX_A_DELETE = u'Delete'
FIX_PICK_SHARED = u'Company shared parameter (same kind: {0})'
FIX_NEW_NAME = u'New name for "{0}"'
FIX_DELETE_ASK = u'Delete "{0}"? Formulas and dimensions that use it lose it.'
FIX_NO_FILE = u'No company shared parameter file - set it in Revit (Manage > Shared Parameters).'
FIX_IN_EDITOR = u'Open the family (Edit Family) to change it - here it is only checked.'
FIX_OUT_FOLDER = u'Folder for the fixed copies (not the one being checked)'
FIX_SAME_FOLDER = u'Choose another folder - the families being checked are never overwritten.'
FIX_FOLDER_DONE = u'{0} families saved to {1}.\nList of changes: {2}'
MENU_CHECK = u'Check against this project...'
MENU_CHECK_TIP = u'What an update would change here - nothing is loaded until you choose.'
TYPES_HEADER = u'Types from the type catalog ({0})'
TYPES_HINT = u'Tick the types to load. Nothing ticked = choose before loading.'
TYPES_NONE = u'Tick at least one type from the catalog.'
NOTHING_SELECTED = u'Select a family on the left.'
DETAILS_HINT = (u'Select a family to see its preview, versions and types.\n\n'
                u'Double click or Shift+Enter: load and place.\n'
                u'Right click: more actions.\n'
                u'Type in the search box, Enter jumps to the best match.')
OFFLINE = u'Offline - showing the saved copy of the library ({0}).'
ONLINE = u'{0} families · {1}'
LOADING = u'Loading the library…'
DOWNLOADING = u'Downloading {0}…'
LOADED = u'Loaded: {0}'
UPDATED = u'Updated: {0} (v{1})'
NO_PLACE = u'{0} is loaded; it cannot be placed from here (e.g. a rebar shape) - use it in Revit.'
PLACE_AFTER =u'Click in the view to place {0}. Esc to finish.'
FAMILY_DOC = (u'The library loads families into projects. Switch to a project window '
              u'(the family editor is not supported).')
NO_DOC = u'Open a project first.'
NOT_CONFIGURED = (u'The library folder is not set on this computer.\n\n'
                  u'Choose the folder that contains PEER-Library.')
PICK_ROOT = u'Folder that contains PEER-Library'
TAB_LIBRARY = u'Library'
TAB_NEWS = u'What’s new'
TAB_MINE = u'My proposals'
NEWS_ADDED = u'added'
NEWS_UPDATED = u'updated'
NEWS_DEPRECATED = u'deprecated'
HISTORY = u'History'
HELP = u'Instructions'
VERSION_LINE = u'Library v{0} · {1}'
OLD_REVIT = (u'The library families are saved in Revit {0} - Revit {1} cannot load them. '
             u'Open the project in Revit {0} or newer.')
PROJECT_LINE = u'In project: {0}'
NO_PREVIEW = u'no preview'
OWNED = u'The family is used by another user: {0}'

# ---- proposals --------------------------------------------------------------
TITLE_PROPOSE = u'PEER - Propose a family'
SRC_FILE = u'File on disk'
SRC_SELECTED = u'Family of the selected element'
SRC_EDITOR = u'Family open in the editor'
KIND_NEW = u'New family'
KIND_FIX = u'Improvement of an existing one'
PROPOSE_SENT = u'Sent. The admins will look at it - the status is in Library → My proposals.'
PROPOSE_NEED = u'Fill in the name and the reason.'
PROPOSE_SAVE_EDITOR = u'Save the family first - an unsaved family cannot be sent.'
PROPOSE_NO_SELECTION = u'Select one element of a loadable family in the project.'
P_PENDING = u'Waiting for review'
P_ACCEPTED = u'Accepted'
P_REJECTED = u'Rejected'

# ---- admin ------------------------------------------------------------------
TITLE_PUBLISH = u'PEER - Publish to the library'
TITLE_INBOX = u'PEER - Library inbox'
MODE_NEW = u'New family'
MODE_UPDATE = u'New version of an existing family'
ACCEPT_WARNINGS = u'I checked the warnings - publish anyway'
PUBLISH_OK = u'Published {0} v{1}.'
PUBLISH_BLOCKED = u'Not published - fix the errors above.'
PUBLISH_NEED_ACCEPT = u'There are warnings - tick the box to publish anyway.'
PUBLISH_ONLY_2024 = u'Publish from Revit {0} only.'
BATCH_TITLE = u'Publish a sorted folder'
BATCH_DONE = u'Published {0}, skipped {1}, failed {2}. Report: {3}'
REJECT_NEED = u'Write why the proposal is rejected.'
INBOX_EMPTY = (u'Nothing waiting for review.\n\n'
               u'New proposals, requests and problem reports from colleagues appear here.')
INBOX_SELECT = u'Select a proposal on the left.'
NOT_ADMIN = u'Only library admins can do this.'

# ---- account (one key for the whole PEER tab) --------------------------------
ACC_TITLE = u'PEER - Account'
ACC_DASH = u'-'
ACC_ST_OK = u'Signed in'
ACC_ST_STALE = u'Key not checked for 14 days'
ACC_ST_NONE = u'Not signed in'
ACC_ST_REQUESTED = u'Access request waiting'
ACC_ST_REVOKED = u'Key not valid'
ACC_ST_OFF = u'Not set up'
ACC_OK = u'This key opens the PEER buttons and the family library on this computer.'
ACC_OFFLINE = (u'No connection to the PEER service - working from the last check. '
               u'PEER keeps working offline for {0} more day(s).')
ACC_STALE = u'Connect to the internet and press Check now.'
ACC_STALE_LOCKED = (u'The key was last checked more than 14 days ago - the PEER buttons are off. '
                    u'Connect to the internet and press Check now.')
ACC_NONE = u'Sign in with the key from a PEER admin, or request access.'
ACC_NONE_LOCKED = (u'The PEER buttons are off until you sign in. Paste the key from a PEER admin, '
                   u'or request access.')
ACC_REQUESTED = (u'Your access request is waiting for an admin. Press Sign in after it is approved - '
                 u'you are signed in automatically.')
ACC_REVOKED = u'This key is not valid any more. Ask a PEER admin for a new one, or request access.'
ACC_OFF = u'The PEER service address is not set on this computer - nothing to sign in to.'
ACC_ROLE_ADMIN = u'Admin'
ACC_ROLE_USER = u'User'
ACC_BTN_SIGNIN = u'Sign in / request access…'
ACC_BTN_CHANGE = u'Change key…'
ACC_SIGNOUT_ASK = (u'Sign out on this computer?\n\nThe key is removed from this computer. '
                   u'To sign in again you need the key or a new access request.')
ACC_NEED_KEY = (u'PEER works with a personal key.\n\nSign in now? (PEER tab → Account: paste the key '
                u'from a PEER admin, or request access.)')

# ---- families loaded together (card field "companions") ---------------------------
COMP_HEADER = u'Also load'
COMP_PRESENT = u'already in the project'
COMP_CATALOG = u'has a type catalog - load it from its own card'
COMP_RETIRED = u'retired in the library'
COMP_MISSING = u'not in the library (fix the card)'
COMP_LOADED = u'Also loaded: {0}.'
COMP_FAILED = u'The family is loaded, but these could not be loaded with it:'
COMP_UNKNOWN = u'Not in the library: {0}. Use the family ID (the grey line under its name).'

# ---- project template --------------------------------------------------------------
TPL_TITLE = u'PEER - New project'
TPL_NO_SERVICE = u'The PEER service is not set up on this computer - there is no template to take.'
TPL_NOT_READY = (u'The company template is not on this computer yet and could not be downloaded:\n\n{0}\n\n'
                 u'Check the internet and PEER -> Account, then try again.')
TPL_SAVE_AS = u'New project from PR_Template Concrete v{0} - save as'
TPL_NOT_OVER = u'Choose another name: this is the template file itself.'
