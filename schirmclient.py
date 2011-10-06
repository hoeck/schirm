# -*- coding: utf-8 -*-
"""
    Schirm Client Library.
    
    Provides functions to write and read the additional schirm html
    terminal emulator escape sequences.

    :copyright: (c) 2011 by Erik Söhnel
    :license: GPL
"""

__all__ = ('enter', 'leave', 'close', 'frame', 'debug',
           'register_resource', 'read_next_request', 'respond')

import os
import sys
import fcntl
import base64
from contextlib import contextmanager

ESC = "\033"
INTRO = "\033R"
END = "\033Q"
SEP = "\033;"
EXIT = "\033x"

def enter():
    """
    Enter the frame mode.

    Creates an iframe in the schirm terminal and all subsequent writes
    are written with document.write to the iframes document.
    """
    sys.stdout.write("".join((INTRO, 'enter', END)))
    sys.stdout.flush()

def leave():
    """
    Get back to normal terminal emulation mode.

    If not already done, invoke close to close the iframe
    document. All static resources remain available until a new iframe
    is opened again.
    """
    sys.stdout.write(EXIT)
    sys.stdout.flush()

def close():
    """
    If in frame mode, close the current iframe document (triggering
    document.load events). Any subsequent writes to stdout reopen
    (and therefor clear) the current document again.
    """
    sys.stdout.write("".join((INTRO, 'close', END)))
    sys.stdout.flush()

@contextmanager
def frame():
    """
    Enter frame mode, leaving it on return or exceptions.
    """
    try:
        enter()
        yield
    finally:
        leave()

def register_resource(path, name=None):
    """
    Make the resource name available to the current iframe. Name must
    have a valid file-ending so that the content type can be
    determined properly (as a fallback, text/plain is used).
    """
    out = sys.stdout
    if not name:
        _, name = os.path.split(path)
    out.write("".join((INTRO,
                       "register_resource",
                       SEP,
                       base64.b64encode(name),
                       SEP)))
    with open(path, "rb") as f:
        out.write(base64.b64encode(f.read()))
    out.write(END)

def debug(msg):
    """
    Write a message to the schirm terminal process stdout. Use this
    instead of print to print-debug running frame mode programms.
    """
    out = sys.stdout
    out.write("".join((INTRO, "debug", SEP)))
    out.write(base64.b64encode(msg))
    out.write(END)

def set_block(fd, block=True):
    """
    Make fd a blocking or non-blocking file
    """
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    if block:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    else:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

def read_next_request():
    """
    Read characters off sys.stdin until a full request has been read.
    Return the request, which is a list of:

       (requestid, protokoll, method, path, header-key*, header-value*, [data])

    Use the returned requestid and the response function to send a
    response to the schirm terminal.
    """
    req = []
    buf = []
    state = None
    while 1:
        ch = sys.stdin.read(1)
        if state == 'esc':
            if ch == "Q":
                req.append(base64.decodestring("".join(buf)))
                return req
            elif ch == ';':
                req.append(base64.decodestring("".join(buf)))
                buf = []
                state = 'arg'
            elif ch == 'R':
                state = 'arg'
                req = []
                buf = []
            else:
                # ignore
                state = None
        elif state == 'arg':
            if ch == ESC:
                state = 'esc'
            else:
                buf.append(ch)
        elif state == None:
            if ch == ESC:
                state = 'esc'
            else:
                pass

def respond(requestid, response):
    """
    Write a response to requestid to the schirm terminal.
    Response must be a http response.
    """
    out = sys.stdout
    out.write("".join((INTRO, "respond", SEP, requestid, SEP)))
    out.write(base64.b64encode(response))
    out.write(END)
