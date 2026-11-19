# -*- coding: utf-8 -*-
"""peer_feedback - requests and bug reports from PEER to the head of the group.

Path of one request:
    Contact button -> make_request() -> outbox (local file) -> HTTP POST ->
    Google Apps Script receiver -> row on the "Requests" sheet of a Google Sheet.

Every request is written to the local outbox FIRST and removed from it only
after the receiver confirmed it. No internet / receiver down -> the request
stays in the outbox and is sent by flush_async() on the next Revit start.
The receiver drops duplicates by request id, so a retry never doubles a row.

Modules:
    config    - receiver address and key (repo file + local override)
    texts     - window strings (en / ru) and the topic list
    payload   - builds the request dict (pure python, tested)
    outbox    - local queue of unsent items (pure python, tested)
    transport - HTTP POST: .NET in Revit, urllib outside
    client    - submit / flush / ping on top of the above
    context   - what the script adds by itself (Revit API, Revit only)
"""
