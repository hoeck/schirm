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
           'register_resource', 'read_next', 'respond', 'execute', 'eval')

import os
import sys
import fcntl
import base64
from collections import namedtuple
from contextlib import contextmanager

ESC   = "\033"
INTRO = ESC + "R"
END   = ESC + "Q"
SEP   = ESC + ";"
EXIT  = ESC + "x"

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
    sys.stdout.write("".join((INTRO, 'enter', END)))
    sys.stdout.flush()

def leave(newline=True):
    """Get back to normal terminal emulation mode.

    If not already done, invoke close() to close the iframe
    document. All static resources remain available until a new iframe
    is opened again.

    If newline is True, advance the cursor to the next line. If set to
    False, the cursor is left on the current iframe line and any
    following output may replace the iframe.
    """
    sys.stdout.write(EXIT)
    if newline:
        sys.stdout.write("\n")
    sys.stdout.flush()

def close():
    """If in frame mode, close the current iframe document (triggering document.load events).

    Any subsequent writes to stdout reopen (and therefor clear) the
    current document again.
    """
    sys.stdout.write("".join((INTRO, 'close', END)))
    sys.stdout.flush()

@contextmanager
def frame(newline=True):
    """Enter frame mode, leaving it on return or exceptions."""
    try:
        enter()
        yield
    finally:
        leave(newline=newline)

def register_resource(path, name=None, mimetype=''):
    """Make the resource name available to the current iframe.
    
    Name defaults to the filename.

    If no mimetype is given, uses names file-ending to determine the
    content type or text/plain.
    """
    out = sys.stdout
    if not name:
        _, name = os.path.split(path)
    out.write("".join((INTRO, "register_resource", SEP,
                       base64.b64encode(name), SEP,
                       base64.b64encode(mimetype), SEP)))
    with open(path, "rb") as f:
        out.write(base64.b64encode(f.read()))
    out.write(END)

def register_resource_data(data, name, mimetype=''):
    """Make the given data available as resource 'name' to the current iframe."""
    out = sys.stdout
    if not name:
        _, name = os.path.split(path)
    out.write("".join((INTRO, "register_resource", SEP,
                       base64.b64encode(name), SEP,
                       base64.b64encode(mimetype), SEP)))
    out.write(base64.b64encode(data))
    out.write(END)

def debug(*msg):
    """Write a message to the schirm terminal process stdout.

    Use this instead of print to print-debug running frame mode
    programms.
    """
    out = sys.stdout
    out.write("".join((INTRO, "debug", SEP)))
    out.write(base64.b64encode(" ".join(map(str, msg))))
    out.write(END)

def set_block(fd, block=True):
    """Make fd a blocking or non-blocking file"""
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    if block:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    else:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


def read_list():
    """Read a list of strings from stdin and return it.
    
    All arguments are separated by '\033;', terminated with '\033Q'.
    The first element is plain text, the following elements are base64
    encoded.
    """
    current = []
    args = []

    def append_arg(a):
        if args:
            # all subsequent args are b64 encoded
            args.append(base64.decodestring(a))
        else:
            # the first arg is the request type name
            args.append(a)

    while 1:
        ch = sys.stdin.read(1)
        if ch == ESC:
            ch = sys.stdin.read(1)
            if ch == ';':
                # read another arg, store the current one
                append_arg("".join(current))
                current = []
            elif ch == 'Q':
                append_arg("".join(current))
                return args
            else:
                pass
        else:
            current.append(ch)

_request = namedtuple('Request', ('type', 'id', 'protocol', 'method', 'path', 'header', 'data'))
class Request(_request):
    """
    Represents HTTP request data.

    The type field is always 'request'.

    Note: Use the returned id and the schirmclient.response() function to
    send a response to the schirm terminal emulator.
    """
    pass


_message = namedtuple('Message', ('type', 'data'))
class Message(_message):
    """
    Represents schirmlog messages (type='message') or js evaluation
    results (type='result').
    
    The data slot contains the result as a string.
    """
    pass


_keypress = namedtuple('KeyPress', ('type', 'data', 'esc'))
class KeyPress(_keypress):
    """
    Represents single characters read from stdin
    (type='keypress', data=<char>, esc=<bool>).
    """


def read_next():
    """Read characters off sys.stdin until a full request, a message or result has been read.

    Returns a namedtuple of type Request or Message.
    """
    while 1:
        ch = sys.stdin.read(1)
        if ch == ESC:
            ch = sys.stdin.read(1)
            if ch == 'R':
                args = read_list()
                if args[0] == 'request':
                    # ('request', requestid, protocol, method, path, header-key*, header-value*, [post-data])
                    headers = dict((args[i], args[i+1]) for i in range(5, len(args)-1, 2))
                    return Request('request', args[1], args[2], args[3], args[4], headers, args[-1] if len(args)%2 else None)
                else:
                    return Message(*args)
            else:
                # some keycombo
                return KeyPress('keypress', ch, True)
        else:
            # plain keypress
            return KeyPress('keypress', ch, False)

def respond(requestid, response):
    """Write a response to requestid to the schirm terminal.

    Response must be a http response.
    """
    out = sys.stdout
    out.write("".join((INTRO, "respond", SEP, requestid, SEP)))
    out.write(base64.b64encode(response))
    out.write(END)


def execute(src):
    """Execute the given javascript string src in the current frames context.

    Discard the result (use schirmlog("message"); to send strings to
    the client from javascript).
    """
    out = sys.stdout
    out.write("".join((INTRO, "execute", SEP)))
    out.write(base64.b64encode(src))
    out.write(END)


def eval(src):
    """Execute the given javascript string src in the current frames context.

    The result will be returned as a base64 encoded string over stdin
    starting with '\033Rresult\033;' (see read_next). Results will be
    delivered asynchronously but in the order of the evals.
    """
    out = sys.stdout
    out.write("".join((INTRO, "eval", SEP)))
    out.write(base64.b64encode(src))
    out.write(END)
