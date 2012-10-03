# -*- coding: utf-8 -*-

# Schirm - a linux compatible terminal emulator providing html modes.
# Copyright (C) 2011  Erik Soehnel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import fcntl
import termios
import itertools
import cgi
import json
import struct
import Queue
import threading
import logging
import base64
import pwd
import types
import time
import pkg_resources
from warnings import warn
from UserList import UserList

import pyte

import termscreen
from termscreen import TermScreen, SchirmStream

import termkey
import htmlterm
import termiframe

logger = logging.getLogger(__name__)

class attrdict(dict):
    def __getattr__(self, k):
        return self[k]

def json_escape_all_u(src):
    dst = ""
    for c in src:
        dst += "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')
    return dst

def fork_terminal(f, *args):
    pid, master = os.forkpty()
    if pid == 0:
        # child
        os.putenv('TERM', 'xterm')
        os.putenv('COLORTERM', 'Terminal')
        os.putenv('COLUMNS', str(size[0]))
        os.putenv('LINES', str(size[1]))
        os.execl(shell, shell_name)
        assert False
    else:
        # parent
        return pid, master

class Terminal(object):
    """
    Wrapper to set up and use a termscreen.Screen.
    """

    # Create a pyte Screen using termscreen.TermScreen and connect it
    # to the (pyte Stream) SchirmStream.
    # Keep the current screen state as read through the screens messages.
    # (The screen itself only keeps state necessary to compute the
    # transitions to the next state - i.e. it completely disregards
    # iframe resources).

    def __init__(self, terminal_io, terminal_ui, size=(80, 25)):

        # set up the screen
        self.screen = TermScreen(*size)
        self.stream = SchirmStream()
        self.stream.attach(self.screen)

        self.last_cursor_line = 0 # ???
        self.focus = False
        self.size = [0,0]

        # the terminal_io must be a file-like object providing
        # .read and .write and .flush methods
        self.terminal_io = terminal_io

        # object for communicating with the UI and the html
        # document, regardless whether its gan
        # embedded webiew or a browser
        self.terminal_ui = terminal_ui

        self.iframes = termiframe.Iframes(terminal_io, terminal_ui)

        # request id of the terminal comm websocket if established
        self.termframe_websocket_id = websocket_id
        self._execute_queue = []

        # webview console logging (setup in schirm.main())
        self.console_logger = logging.getLogger('webview_console')

    def write(self, s):
        self.terminal_io.write(s)

    def write_iframe(self, s):
        if self.screen.iframe_mode:
            self.write(s)

    def write_request(self, request_data):
        # request data is a list of strings:
        #   req_id, method, path, headers (k, v)*, data
        if self.pty.screen.iframe_mode == 'closed':
            request = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE
            self.terminal_io.write(request)

    def remove_history(self, lines_to_remove):
        self.screen.remove_history(lines_to_remove)

    def iframe_resize(self, height):
        #iframe_id = self.screen.iframe_id
        #self.screen.linecontainer.iframe_resize(iframe_id, height)

        # todo: this has nothing todo with self.screen
        pass

    def resize(self, size):
        self.screen.resize(size.height, size.width)
        self.terminal_io.set_size(size.height, size.width)

    def set_focus(self, focus=True):
        """Setting the focus flag currently changes the way the cursor is rendered."""
        self.focus = bool(focus)
        #self.screen.ui_set_focus(focus)
        # redraw the terminal with the new focus settings
        #self.input_queue.put(('redraw', None)) # ???
        # maybe there should be a TermScreen.set_focus method

    def _dispatch_message(self, msg):
        """Invoke the appropriate action according to msg['cmd']."""
        if msg['cmd'] == 'resize':
            # always set size
            w = msg.get('width')
            h = msg.get('height')

            if w and h:
                self.resize(attrdict({'width': int(w),
                                      'height':int(h)}))

        elif msg['cmd'] == "iframeresize":
            try:
                height = int(msg['height'])
            except:
                return
            logger.debug("Iframe resize request to %s", height)
            self.screen.linecontainer.iframe_resize(msg.get('id') or self.screen.iframe_id, height)

        elif msg['cmd'] == 'removehistory':
            try:
                n = int(msg['n'])
            except:
                return False
            self.screen.linecontainer.remove_history(n)

        else:
            raise Exception("unknown command in message: %r" % msg)

    def console_log(self, data): # TODO: move IPC dispatch code into a function, make args a dictionary (for easy json-over-websocket transport)
        msg, line, source_id = data

        # decode message to see if its a console log or IPC command
        ipc_prefix = 'schirmcommand'
        if msg.startswith(ipc_prefix):
            self.console_logger.debug("IPC: (%s:%s) %s", source_id, line, msg)
            # todo: only dispatch terminal command if source_id is 'termframe.html' or the like
            # todo: check that, for iframe commands, source id contains the iframe id-url (iframe-id.localhost)
            # todo: catch decode errors
            self._dispatch_message(json.loads(msg))
        else:
            # log it
            if source_id:
                self.console_logger.info("(%s:%s): %s", source_id, line, msg)
            else:
                self.console_logger.info(msg)

    def _keypress(self, key):
        """Decode a keypress into terminal escape-codes.

        Expect a namedtuple in data with .name, .shift, .alt, .control
        and .string attribs.

        Return a (possibly empty) string to feed into the terminal.
        """
        # compute the terminal key
        k = termkey.map_key(keyname=key.name,
                            modifiers=(key.shift, key.alt, key.control),
                            screen_mode=(pyte.mo.DECAPP in self.screen.mode))
        if not k:
            if key.alt:
                k = "\033%s" % key.string
            else:
                k = key.string

        if self.screen.iframe_mode:
            # in iframe mode, only write some ctrl-* events to the
            # terminal process
            if k and \
                    key.control and \
                    key.name in "dcz":
                return k
        else:
            if k:
                return k

        return ''

    def _feed(self, input):
        # input is a list of strings or tuples
        for i in input if isinstance(input, (list, tuple)) else [input]:
            if i:
                if isinstance(i, basestring):
                    # raw input coming from the process driving the terminal
                    self.stream.feed(i)
                elif isinstance(i, tuple):
                    name, data = i
                    if name == 'keypress':
                        x = self._keypress(data)
                        self.terminal_io.write(x)
                    elif name == 'pty_read_error':
                        self.stream.close()
                    elif name == 'set_focus':
                        self.set_focus(data)
                    elif name == 'request':
                        self.request(data)
                    elif name == 'console_log':
                        self.console_log(data)
                    else:
                        logger.error('unknown input identifier: %r' % (name,))
            else:
                pass

    def execute(self, js_string):
        if self.termframe_websocket_id:
            if self._execute_queue:
                for s in self._execute_queue:
                    self.terminal_ui.respond(self.termframe_websocket_id, data=''.join(s), close=False)
                self._execute_queue = []
            self.terminal_ui.respond(self.termframe_websocket_id, data=''.join(js_string), close=False)
        else:
            self._execute_queue.append(js_string)

    def advance(self, input):

        # turn off the cursor
        self.screen.linecontainer.hide_cursor(self.screen.cursor.y)

        # advance the terminal state machine based on the given input
        # return a list of tuples: (message, arguments)
        self._feed(input)

        if not self.screen.cursor.hidden and not self.screen.iframe_mode:
            # make sure the terminal cursor is drawn
            self.screen.linecontainer.show_cursor(
                self.screen.cursor.y,
                self.screen.cursor.x,
                'cursor' if self.focus else 'cursor-inactive')

        # capture render events
        events = self.screen.linecontainer.get_and_clear_events()

        # group javascript in chunks for performance
        js = [[]]
        def js_flush():
            #self.terminal_ui.execute(js[0])
            self.execute(js[0])
            js[0] = []

        def js_append(x):
            js[0].append(x)

        # issue the screen0 as the last event
        screen0 = None

        for e in events:

            name = e[0]
            args = e[1:]

            if name.startswith('iframe_'):
                # iframes:
                js_flush()
                self.iframes.dispatch(e)
            elif name == 'set_title':
                js_flush()
                self.terminal_ui.set_title(args[0])
            elif name == 'set_screen0':
                screen0 = args[0]
            elif name == 'close_stream':
                raise Exception('terminal exit')
            elif name in htmlterm.Events.__dict__:
                # sth. to be translated to js
                js_append(getattr(htmlterm.Events,name)(*args))
            else:
                logger.error('unknown event: %r', name)

        if screen0 is not None:
            js_append(htmlterm.Events.set_screen0(screen0))

        js_flush()

    def request(self, req):
        # dispatch to self.iframes depending on the current subdomain
        if req.type == 'http':
            if req.path.startswith('http://termframe.localhost'):
                # terminal requests
                # default static resources:
                # - relative paths are looked up in schirm.resources module
                #   using pkg_resources.
                # - absolute paths are loaded from the filesystem (user.css)
                static_resources = {# terminal emulator files
                                    #'/term.html': 'term.html',
                                    '/term.js': 'term.js',
                                    '/term.css': 'term.css',
                                    # user configurable stylesheets
                                    '/user.css': '/home/timmy/.schirm/user.css' #get_config_file_path('user.css') or 'user.css',
                                    }
                not_found = set(["/favicon.ico"])

                path = req.path[len('http://termframe.localhost'):]
                if path in not_found:
                    self.terminal_ui.respond(req.id)
                elif path in static_resources:
                    self.terminal_ui.respond_resource_file(req.id, static_resources[path])
                elif path == '/term.html':
                    data = pkg_resources.resource_string('schirm.resources', 'term.html')
                    resp = self.terminal_ui.make_response('text/html', json.dumps(data % {'websocket_url': 'ws://localhost:%s' % req.proxy_port}))
                    self.terminal_ui.respond(req.id, resp)

            else:
                # try to dispatch the request to the current iframe
                self.iframes.request(req)

        elif req.type == 'websocket':
            if 'upgrade' in req and req.path == '/':
                if not self.termframe_websocket_id:
                    self.termframe_websocket_id = req.id
                    self.terminal_ui.respond(req.id, True, close=False)
                else:
                    # deny
                    self.terminal_ui.respond(req.id) # 404

            elif req.id == self.termframe_websocket_id:
                # main frame websocket connection:
                # required for RPC
                # todo: profile: is this faster than using webkit.execute and console.log for exchanging text??
                self._dispatch_message(json.loads(req.data))

            else:
                self.iframes.request(req)

        else:
            assert False

# interfaces to talk to:
#   the webkit rendering the terminal state, reflecting the
#   communication protocol (http)
# class TerminalUi(object):
#     def make_request(self, mimetype, data)
#     def guess_type(self, filename)
#     def respond(self, request_id, data, close)
#     def respond_resource_file(self, request_id, resource_name)
#     def execute(self, script) # exceute a command in the 'term' context
#
# #   to talk to the process driving the terminal, either a real
# #   forked pty or a wrapped channel for an embedded terminal
# class TerminalIo(object):
#     def read(self) # non-blocking, use <#NoneType> for 'nothing'
#     def write(self, data or [data*])
#     def set_size(self, columns, lines) # e.g. issue a sigwinch


# class Pty(object):
#
#     def __init__(self, size=(80, 25)):
#
#         shell = pwd.getpwuid(os.getuid()).pw_shell
#         shell_name = os.path.basename(shell)
#
#         # WTF?: putting the forkpty into a method or function does not
#         # work, am I missing sth?
#         #self._pid, self._pty = self.fork(shell, shell_name)
#         #self._pid, self._pty = fork_terminal(shell, shell_name)
#
#         pid, master = os.forkpty()
#         if pid == 0:
#             # child
#             os.putenv('TERM', 'xterm')
#             os.putenv('COLORTERM', 'Terminal')
#             os.putenv('COLUMNS', str(size[0]))
#             os.putenv('LINES', str(size[1]))
#             os.execl(shell, shell_name)
#             assert False
#         else:
#             # parent
#             self._pid = pid
#             self._pty = master
#
#         self._size = [0,0]
#         self._focus = True
#
#         self.screen = TermScreen(*size)
#         self.last_cursor_line = 0
#         self.stream = SchirmStream()
#         self.stream.attach(self.screen)
#
#         self.set_size(*size)
#
#         # set up input (pty -> schirm) queue
#         # and a default producer which os.reads from the pty
#         # to get simple asyncronous/interruptible os.read without
#         # dealing with signals
#         self.input_queue = Queue.Queue(4)
#         def read_from_pty():
#             try:
#                 while True:
#                     # de-priorize input data to not block the UI
#                     # test: cat a huge file, ctrl-c should work instantly
#                     input_data = os.read(self._pty, 8192)
#                     put_nowait_sleep(self.input_queue, ('pty_data', input_data))
#                     #self.input_queue.put(('pty_data', input_data))
#
#             except OSError, e:
#                 # self._pty was closed or reading interrupted by a
#                 # signal -> application exit
#                 self.input_queue.put(('pty_read_error', None))
#
#         t = threading.Thread(target=read_from_pty)
#         t.setDaemon(True)
#         t.start()
#
#
#     # def fork(self, file, args):
#     #     pid, master = os.forkpty()
#     #     if pid == 0:
#     #         # child
#     #         os.putenv('TERM', 'xterm')
#     #         os.putenv('COLORTERM', 'Terminal')
#     #         os.putenv('COLUMNS', str(size[0]))
#     #         os.putenv('LINES', str(size[1]))
#     #         os.execl(file, *args)
#     #     else:
#     #         # parent
#     #         return pid, master
#
#     # q
#
#     def q_write(self, s):
#         "Queued version of self.write()."
#         self.input_queue.put(lambda : self.write(s))
#
#     def q_write_iframe(self, s):
#         "Write content to the PTYs stdin only if its in iframe mode."
#         self.input_queue.put(lambda : self.write(s) if self.screen.iframe_mode else None)
#
#     def q_set_size(self, h, w):
#         "Queued version of self.set_size()"
#         self.input_queue.put(lambda : self.set_size(h, w))
#
#     def q_resize(self, lines, cols):
#         self.input_queue.put(lambda : self.resize(lines, cols))
#
#     def q_set_focus(self, focus=True):
#         self.input_queue.put(lambda : self.set_focus(focus))
#
#     def q_remove_history(self, lines_to_remove):
#         self.input_queue.put(lambda: self.screen.remove_history(lines_to_remove))
#
#     def q_iframe_resize(self, height):
#         iframe_id = self.screen.iframe_id
#         self.input_queue.put(lambda: self.screen.linecontainer.iframe_resize(iframe_id, height))
#
#     def write(self, s):
#         """
#         Writes the given string or each string in the given iterator to
#         the pty.
#         """
#         if isinstance(s, basestring):
#             os.write(self._pty, s)
#         else:
#             for x in s:
#                 os.write(self._pty, x)
#
#     def set_size(self, h, w): # h/lines, w/columns
#         """
#         Use the TIOCSWINSZ ioctl to change the size of _pty if neccessary.
#         """
#         oldw, oldh = self._size
#         if oldw != w or oldh != h and w > 0 and h > 0:
#             empty_win = struct.pack('HHHH',0,0,0,0)
#             win = fcntl.ioctl(self._pty, termios.TIOCGWINSZ, empty_win)
#             _h,_w,x,y = struct.unpack('HHHH', win)
#             win = struct.pack('HHHH', h, w, x, y)
#             fcntl.ioctl(self._pty, termios.TIOCSWINSZ, win)
#             self._size = [w, h]
#
#     def resize(self, lines, cols):
#         # this is only eventual consistent :/
#         self.input_queue.put(lambda: self.screen.resize(lines, cols)) # put resize on the render thread
#         self.set_size(lines, cols) # -> issues sigwinch
#
#     def set_focus(self, focus=True):
#         """Setting the focus flag currently changes the way the cursor is rendered."""
#         self._focus = bool(focus)
#
#         # redraw the terminal with the new focus settings
#         self.input_queue.put(('redraw', None))
#
#     def read_and_feed(self):
#         res = self.input_queue.get(block=True)
#         if isinstance(res, types.FunctionType):
#             res()
#         else:
#             type, data = res
#             if type == 'pty_data':
#                 self.stream.feed(data)
#             elif type == 'pty_read_error':
#                 self.stream.close()
#             elif type == 'redraw':
#                 pass
#
#     def render_changes(self):
#         # TODO: move this into termscreen
#         # make this a function of:
#         # the termscreen + an EventRenderer class/instance providing event implementations
#         # to render
#
#         q = []
#         lines = self.screen.linecontainer
#
#         if not self.screen.cursor.hidden and not self.screen.iframe_mode:
#             # make sure the terminal cursor is drawn
#             #print "cursor is", self.screen.cursor.y, self.screen.cursor.x
#             lines.show_cursor(self.screen.cursor.y,
#                               self.screen.cursor.x,
#                               'cursor' if self._focus else 'cursor-inactive')
#
#         events = lines.get_and_clear_events()
#         for e in events:
#             x = getattr(EventRenderer, e[0])(*e[1:])
#             if x:
#                 q.append(x)
#
#         # line changes
#         line_q = []
#         for i,line in lines.get_changed_lines():
#             line.changed = False
#             line_q.append(set_line_to(i, renderline(line)))
#
#         # garbagecollect history?
#         q.append(EventRenderer.check_history_size())
#
#         q.append("\n".join(line_q))
#
#         if not self.screen.cursor.hidden and not self.screen.iframe_mode:
#             # make sure our current cursor will be deleted next time
#             # we update the screen
#             lines.hide_cursor(self.screen.cursor.y)
#
#         return q
#
#     def read_and_feed_and_render(self):
#         self.read_and_feed()
#         return self.render_changes()
#
#     def paste(self, data):
#         """Write data into the terminals stdin.
#
#         When in plain terminal mode, paste data and return True. When
#         in iframe_mode, do nothing and return False.
#         """
#         if self.screen.iframe_mode:
#             return False
#         else:
#             self.q_write(data)
#             return True
#
# # 1: A
# # 2: B
# # 3: C
# # 4: D
#
# # set line 2: X   --> line 2, changed
# # appendline: Y
# # set line 3: Z   --> line




