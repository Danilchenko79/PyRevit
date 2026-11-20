# -*- coding: utf-8 -*-
"""Window strings and choice lists. Codes go to the table; labels are shown.

Codes are stable: the weekly summary and the receiver group by them, so a
label can be reworded without touching the data.
"""

# (code, label, when to pick)
TOPICS = [
    ('automation', u'Automation', u'"I want a button that..."'),
    ('improve', u'Improve a button', u'An existing button is awkward to use - pick it below'),
    ('bug', u'Bug', u'A script crashed or gave a wrong result - pick it below'),
    ('idea', u'Idea', u'A process suggestion, not necessarily about scripts'),
    ('routine', u'Routine', u'"I keep doing this by hand", no solution in mind'),
    ('template', u'Template & families', u'A family, type or parameter is missing'),
    ('howto', u'How-to question', u'Not clear how to do a task in Revit or PEER'),
    ('standard', u'Office standard', u'An office rule is unclear or inconvenient'),
]
TOPIC_CODES = [t[0] for t in TOPICS]
# topics where the button list is shown
TOPICS_WITH_BUTTON = ('improve', 'bug')

FREQUENCY = [
    ('', u'(not set)'),
    ('daily', u'Every day'),
    ('weekly', u'Every week'),
    ('rare', u'Rarely'),
]
DURATION = [
    ('', u'(not set)'),
    ('lt5', u'Up to 5 min'),
    ('5to30', u'5-30 min'),
    ('gt30', u'More than 30 min'),
]
FREQUENCY_CODES = [c for c, _ in FREQUENCY]
DURATION_CODES = [c for c, _ in DURATION]

STRINGS = {
    'title': u'Contact the head of the group',
    'how_to': u'Pick a topic and describe what you need in a few sentences. '
              u'Project, view and Revit version are added automatically '
              u'(listed at the bottom). You can see the status of your '
              u'request later in PEER.',
    'topic': u'Topic:',
    'button': u'Which button:',
    'text': u'What do you need? (required)',
    'text_bug': u'What were you doing? (optional when an error is attached)',
    'error': u'Error to attach (PEER errors of the last 7 days):',
    'no_error': u'(no error attached)',
    'error_hint': u'The full error text goes with the report.',
    'placeholder': u'Describe what you need in a few sentences...',
    'images': u'Screenshots and pictures (optional)',
    'images_hint': u'Ctrl+V pastes a screenshot (text copied from Excel / Word pastes as text in the box above). You can also drop image files here. Up to 5.',
    'add_image': u'Add image...',
    'image_too_big': u'This picture is too large even after shrinking it.',
    'image_max': u'Up to 5 pictures per request.',
    'shortcut': u'Ctrl+Enter - send',
    'frequency': u'How often:',
    'duration': u'Time per occurrence:',
    'context': u'Added automatically (click to see)',
    'send': u'Send',
    'cancel': u'Cancel',
    'no_button': u'(not about a specific button)',
    'err_text': u'Please describe the request in the text field.',
    'err_button': u'Please pick the button this is about.',
    'sent': u'Sent. Thank you!',
    'queued': u'No connection to the receiver right now.\n'
              u'The request is saved on this computer and will be sent '
              u'automatically on the next Revit start.',
    'rejected': u'The receiver did not accept this request (looks like a PEER bug).\n'
                u'It is kept on this computer in %APPDATA%\\PEER\\rejected - '
                u'please tell the head of the group.',
    'sending': u'Sending...',
    'background': u'The window was closed while sending.\n'
                  u'The request is saved on this computer and is being sent; '
                  u'if that fails it goes on the next Revit start. '
                  u'See Feedback -> My requests.',
    'not_configured': u'The receiver is not set up yet.\n'
                      u'The request is saved on this computer and will be sent '
                      u'as soon as the receiver address is set.',
}


def s(key):
    return STRINGS[key]
