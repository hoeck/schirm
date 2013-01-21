# -*- coding: utf-8 -*-
# Copyright 2011 Erik Soehnel. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are
# permitted provided that the following conditions are met:
#
#    1. Redistributions of source code must retain the above copyright notice, this list of
#       conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright notice, this list
#       of conditions and the following disclaimer in the documentation and/or other materials
#       provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY <COPYRIGHT HOLDER> ''AS IS'' AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
# FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
    Schirm Client Library.

    Provides functions to write and read the additional schirm html
    terminal emulator escape sequences.

    :copyright: (c) 2011 by Erik Soehnel
    :license: Simplified BSD License
"""

__all__ = ('enter', 'leave', 'close', 'frame', 'debug',
           'resource', 'resource_data', 'read_next', 'respond', 'send')

import os
import sys
import fcntl
import json
import base64
from collections import namedtuple
from contextlib import contextmanager

ESC = "\x1b"
CSI = ESC + "["
MODE_PRIV = CSI + "?"
DOCUMENT_MODE = "5151"
RESPONSE_MODE = "5152"
STR_START = ESC + "X"
STR_END = ESC + "\\"

# primitives
def _set_mode_str(mode_id, cookie=None):
    return ''.join([MODE_PRIV, mode_id] +
                   [';' + s[i:i+4] for i in range(0, len(cookie or ''), 4)] +
                   ['h'])

def _reset_mode_str(mode_id):
    return ''.join([MODE_PRIV, mode_id, 'l'])

def _write_request(header, body, out=sys.stdout):
    try:
        out.write(STR_START)
        out.write(json.dumps(header))
        out.write("\n\n")
        out.write(base64.b64encode(body))
    finally:
        out.write(STR_END)
        out.flush()

def enter():
    """Enter the frame mode.

    Creates an iframe in the schirm terminal on the current line. All
    subsequent writes are written with document.write() to the iframes
    document.

    When you have written the document, call close() to trigger the
    javascript document.load() handler. Call leave() to go back to
    normal terminal emulation mode.

    See also the frame() contextmanager.
    """
    out = sys.stdout
    out.write(_set_mode_str(mode_id=DOCUMENT_MODE,
                            cookie=os.environ.get('SCHIRM_COOKIE')))
    out.flush()

def close():
    """If in frame mode, close the current iframe document (triggering document.load events).

    Any subsequent writes to stdout reopen (and therefor clear) the
    current document again.
    """
    out = sys.stdout
    out.write(_set_mode_str(mode_id=RESPONSE_MODE,
                            cookie=os.environ.get('SCHIRM_COOKIE')))
    out.flush()

def leave(newline=True):
    """Get back to normal terminal emulation mode.

    If not already done, invoke close() to close the iframe
    document. All static resources remain available until a new iframe
    is opened again.

    If newline is True, advance the cursor to the next line. If set to
    False, the cursor is left on the current iframe line and any
    following output may replace the iframe.
    """
    out = sys.stdout
    out.write(_reset_mode_str(DOCUMENT_MODE))
    if newline:
        out.write("\n")
    out.flush()

@contextmanager
def frame(newline=True):
    """Enter frame mode, leaving it on return or exceptions."""
    try:
        enter()
        yield
    finally:
        leave(newline=newline)

def resource(path, name=None, mimetype=''):
    """Make the resource name available to the current iframe.

    Name defaults to the filename.

    If no mimetype is given, uses names file-ending to determine the
    content type or text/plain.
    """
    if not name:
        _, name = os.path.split(path)

    header = {'x-schirm-path': name}
    if mimetype:
        header['ContentType'] = mimetype

    with open(path) as f:
        _write_request(header, f.read())

def resource_data(data, name, mimetype=''):
    """Make the given data available as resource 'name' to the current iframe."""

    header = {'x-schirm-path': name}
    if mimetype:
        header['ContentType'] = mimetype

    _write_request(header, data)

def debug(*msg):
    """Write a message to the schirm terminal process stdout.

    Use this instead of print to print-debug running frame mode
    programms.
    """
    _write_request({'x-schirm-debug':''}, ' '.join(msg))

def set_block(fd, block=True):
    """Make fd a blocking or non-blocking file"""
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    if block:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    else:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

def read_next():
    """Read characters off sys.stdin until a full request has been read.

    Returns a header dict and a message body.
    """
    state = None
    current = []
    while 1:
        ch = sys.stdin.read(1)
        if state == None:
            if ch == ESC:
                ch += sys.stdin.read(1)
                if ch == STR_START:
                    # STR START
                    current = []
                    state = 'string'
        elif state == 'string':
            if ch == ESC:
                ch += sys.stdin.read(1)
                if ch == STR_END:
                    return "".join(current)
            else:
                current.append(ch)

def respond(requestid, header, body):
    """Write a response to requestid to the schirm terminal.

    Response must be a http response.
    """
    h = dict(header)
    h['x-schirm-requestid'] = requestid
    _write_request(h, body)

def send(data):
    """Send the given data (a string) to the current iframe."""
    _write_request({'x-schirm-message':None}, data)
