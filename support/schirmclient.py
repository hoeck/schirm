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

__all__ = ('enter', 'leave', 'close', 'frame', 'debug', 'terminal_echo',
           'resource', 'resource_data', 'read_next', 'respond', 'send')

import os
import sys
import cgi
import fcntl
import json
import base64
import termios
import urlparse
from collections import namedtuple
from contextlib import contextmanager

ESC = "\x1b"
CSI = ESC + "["
MODE_PRIV = CSI + "?"
SET_MODE = "h"
RESET_MODE = "l"
DOCUMENT_MODE = "5151"
RESPONSE_MODE = "5152"
STR_START = ESC + "X"
STR_END = ESC + "\\"
ALT_BUFFER_MODE = "1049" # save cursor and use alternative buffer (without scrollback)

# primitives
def _set_mode_str(mode_id, cookie=None):
    return ''.join([MODE_PRIV, mode_id] +
                   [';' + cookie[i:i+4] for i in range(0, len(cookie or ''), 4)] +
                   [SET_MODE])

def _reset_mode_str(mode_id):
    return ''.join([MODE_PRIV, mode_id, RESET_MODE])

@contextmanager
def _terminal_str(out=sys.stdout):
    out.write(STR_START)
    try:
        yield
    finally:
        out.write(STR_END)
        out.flush()

def _write_request(header, body, out=sys.stdout):
    with _terminal_str():
        out.write(json.dumps(header))
        out.write("\n\n")
        out.write(base64.b64encode(body))

def terminal_echo(enable):
    """Control printing of input characters and return the previous echo setting.

    Does nothing and returns None in case neither stdin or stdout are
    connected to a terminal.

    see also 'man termios'
    """

    # TODO: what about get_fdin (see frame)???
    if sys.stdin.isatty():
        fd = sys.stdin
    elif sys.stdout.isatty():
        fd = sys.stdout
    else:
        return None

    # tcsetattr, C-API :/
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(fd)

    # keep prev echo setting around
    echo_state = bool(lflag & termios.ECHO)

    if echo_state != enable:
        termios.tcsetattr(fd,
                          termios.TCSANOW,
                          [iflag, oflag, cflag, (lflag | termios.ECHO) if enable else (lflag & ~termios.ECHO), ispeed, ospeed, cc])

    return echo_state

def enter():
    """Enter the frame mode.

    Creates an iframe in the schirm terminal on the current line. All
    subsequent writes are written with document.write() to the iframes
    document.

    When you have written the document, call close() to trigger the
    javascript document.load() handler. Call leave() to go back to
    normal terminal emulation mode.

    You must ensure that the terminal echo is disabled before entering
    frame mode (see terminal_echo and frame).

    See also the frame() contextmanager which handles leave and echo
    state automatically.
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

def isaschirm():
    """Determine whether this process is connected to the schirm terminal emulator."""
    # TODO: check the $SCHIRM_COOKIE
    return sys.stdout.isatty()

def get_fdin():
    """Return the filedescriptor of the controlling schirm terminal."""
    if isaschirm():
        if sys.stdin.isatty():
            return sys.stdin.fileno()
        else:
            return os.open(os.ctermid(), os.O_RDONLY)

@contextmanager
def frame(newline=True, fullscreen=False, url=None, resources={}):
    """Enter frame mode, leaving it on return or exceptions.

    When in frame mode, all data send to the terminal may be written
    to the current frame (depending on the url parameter). Responses
    to HTTP requests from the frame or Websocket messages can be
    issued with the `respond` or `send` methods.

    Use fullscreen=True to use the whole terminal screen, hiding the
    other terminal contents and the scrollback.

    newline=True emits a newline after leaving the frame mode so that
    the shell prompt appears on a new line and doesn't overwrite the
    previous frame.

    When url is not None, it must be a url path string that gets
    loaded in the new frame.
    When url is None, the frames is opened for writing. Anything send
    to the terminal is put into it until `close()` is called.

    resources should be a dictionary of urlpath:(data, mimetype) items.

    Turns echo off during frame mode as otherwise the echoed iframe
    request strings that are written to the terminal by the emulator
    would interfere with the responses printed to it the application
    running in frame mode.
    """
    if not isaschirm():
        raise Exception("Not connected to the schirm terminal.")

    # turn echo off so that requests do not interfere with responses
    echo = terminal_echo(False)

    try:
        if fullscreen:
            out = sys.stdout
            out.write(_set_mode_str(ALT_BUFFER_MODE))
            out.flush()
        enter()

        for name, (data, mimetype) in resources.items():
            resource_data(data, name, mimetype)

        if url:
            close()
            _write_request(header={'x-schirm-frame-options': True},
                           body=json.dumps({'url': url}))

        yield get_fdin()
    finally:
        leave(newline=newline)
        if fullscreen:
            out = sys.stdout
            out.write(_reset_mode_str(ALT_BUFFER_MODE))
            out.flush()

        # restore previous echo setting
        terminal_echo(echo)

def resource(path, name=None, mimetype=''):
    """Make the resource name available to the current iframe.

    Name defaults to the filename.

    If no mimetype is given, uses names file-ending to determine the
    content type or text/plain.
    """
    if not name:
        _, name = os.path.split(path)

    header = {'X-Schirm-Path': name}
    if mimetype:
        header['Content-Type'] = mimetype

    with open(path) as f:
        _write_request(header, f.read())

def resource_data(data, name, mimetype=''):
    """Make the given data available as resource 'name' to the current iframe."""

    header = {'X-Schirm-Path': name}
    if mimetype:
        header['Content-Type'] = mimetype

    _write_request(header, data)

def debug(*msg):
    """Write a message to the schirm terminal process stdout.

    Use this instead of print to print-debug running frame mode
    programms.
    """
    _write_request({'x-schirm-debug':''}, ' '.join(map(str,msg)))

def set_block(fd, block=True):
    """Make fd a blocking or non-blocking file"""
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    if block:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    else:
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

def _read_next_string(fd):
    state = None
    current = []
    while 1:
        ch = os.read(fd, 1)
        if state == None:
            if ch == ESC:
                ch += os.read(fd, 1)
                if ch == STR_START:
                    # STR START
                    current = []
                    state = 'string'
        elif state == 'string':
            if ch == ESC:
                ch += os.read(fd, 1)
                if ch == STR_END:
                    return "".join(current)
            else:
                current.append(ch)

def read_next(fd=None, interrupt='exit'):
    """Read and decode requests from the given filedescriptor (defaults to stdin).

    Returns a header dict and a message body on success.

    interrupt defines what should happen when the user presses CTRL-C or
    hits the iframes close button (terminal sends SIGINT, Python
    raises a KeyboardInterrupt).
    Possible values are:
        'exit'   .. (default) calls sys.exit(0)
        None     .. passes the KeyboardException on
        callable .. called with no arg, return it result
    """
    try:
        header, body = _read_next_string(fd or sys.stdin.fileno()).split('\n',1)
        return json.loads(header), body
    except KeyboardInterrupt, e:
        if interrupt == 'exit':
            sys.exit(0)
        elif interrupt == None:
            raise
        else:
            return interrupt()

def respond(requestid, status, header, body):
    """Write an HTTP response to requestid to the schirm terminal.

    status should be the status string, e.g. '200 OK'.
    header a dict or list of tuples f header-key and value pairs.
    body the data (string) of the response
    """
    h = dict(header)
    h['X-Schirm-Request-Id'] = requestid
    h['Status'] = status
    _write_request(h, body)

def send(data):
    """Send the given data to the current iframe.

    If data is a Python dict, json-encode it before sending.
    """
    _write_request({'X-Schirm-Message':None},
                   json.dumps(data) if isinstance(data, dict) else data)


### WSGI

def _wsgi_handle_request(request, application):

    req_header, req_body = request
    request_id = req_header['X-Schirm-Request-Id']
    url = urlparse.urlparse(req_header['X-Schirm-Request-Path'])
    method = req_header['X-Schirm-Request-Method']

    environ = {
        # The HTTP request method, such as "GET" or "POST".  This
        # cannot ever be an empty string, and so is always required.
        'REQUEST_METHOD': method,
        # The initial portion of the request URL's "path" that
        # corresponds to the application object, so that the
        # application knows its virtual "location". This may be an
        # empty string, if the application corresponds to the "root"
        # of the server.
        'SCRIPT_NAME': '',
        # The remainder of the request URL's "path", designating the
        # virtual "location" of the request's target within the
        # application. This may be an empty string, if the request URL
        # targets the application root and does not have a trailing
        # slash.
        'PATH_INFO': (url.path + ';' + url.params) if url.params else url.path,
        # The portion of the request URL that follows the "?" , if
        # any. May be empty or absent.
        'QUERY_STRING': (url.query + '#' + url.fragment) if url.fragment else url.query,
        # The contents of any Content-Type fields in the HTTP
        # request. May be empty or absent.
        'CONTENT_TYPE': req_header.get('Content-Type', None),
        # The contents of any Content-Length fields in the HTTP
        # request. May be empty or absent.
        'CONTENT_LENGTH': req_header.get('Content-Type', None),
        # When combined with SCRIPT_NAME and PATH_INFO , these
        # variables can be used to complete the URL. Note, however,
        # that HTTP_HOST , if present, should be used in preference to
        # SERVER_NAME for reconstructing the request URL. See the URL
        # Reconstruction section below for more detail. SERVER_NAME
        # and SERVER_PORT can never be empty strings, and so are
        # always required.
        'SERVER_NAME': url.netloc.split(':',1)[0],
        'SERVER_PORT': (url.netloc.split(':',1)[1:] or [None])[0],
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }

    # HTTP_ Variables
    # Variables corresponding to the client-supplied HTTP request headers (i.e., variables whose names begin with "HTTP_" ). The presence or absence of these variables should correspond with the presence or absence of the appropriate HTTP header in the request.
    for k,v in req_header.items():
        if k.lower().startswith('x-schirm'):
            pass
        else:
            environ['HTTP_%s' % k.upper().replace('-','_')] = v

    environ.update({
        'wsgi.input':        sys.stdin,
        'wsgi.errors':       sys.stderr,
        'wsgi.version':      (1, 0),
        'wsgi.multithread':  False,
        'wsgi.multiprocess': True,
        'wsgi.run_once':     True,
        'wsgi.url_scheme':  'http',
        'schirm.request_id': request_id,
    })

    response = {'status':None, 'headers': None}

    def start_response(status, response_headers, exc_info=None):
        assert status, "status is missing"

        if exc_info:
            try:
                if response['status']:
                    # headers have already been send, raise and abort
                    # otherwise, continue with the response
                    raise exc_info[0], exc_info[1], exc_info[2]
            finally:
                exc_info = None     # avoid dangling circular ref

        assert response['status'] == None, "start_response has been called already"

        response['status']  = status
        response['headers'] = response_headers

        def write(data):
            # Deprecated, intended only for use by older frameworks
            # (https://www.python.org/dev/peps/pep-0333/#the-write-callable).
            # The preferred method to provide response data is
            # returning an iterator of strings from the call to
            # application instead of calling this function.
            raise NotImplementedError()

        return write

    result = application(environ, start_response)
    # TODO: allow streaming responses
    respond(request_id, response['status'], response['headers'], ''.join(result))

def wsgi_run(app=None, fullscreen=False, newline=True, resources={}, url='/'):
    """Run WSGI application app in a frame.

    see `frame` for more documentation.
    """
    assert url, "url must not be empty"

    if not app:
        import bottle
        app = bottle.default_app()

    with frame(newline=newline, fullscreen=fullscreen, url=url, resources={}):
        while True:
            req = read_next()
            _wsgi_handle_request(req, app)
