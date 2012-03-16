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
import simplejson
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
from itertools import cycle
from UserList import UserList

import pyte

import termscreen
from termscreen import TermScreen, SchirmStream

def json_escape_all_u(src):
    dst = ""
    for c in src:
        dst += "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')
    return dst


### creating html to render the terminal contents

def create_class_string(chartuple, additional_classes=[]):
    data, fg, bg, bold, italics, underscore, strikethrough, reverse = chartuple
    c = []
    if reverse:
        if bg == 'default':
            c.append("f-default-reversed")
        else:
            c.append("f-{0}".format(bg))
        if fg == 'default':
            c.append("b-default-reversed")
        else:
            c.append("b-{0}".format(fg))
    else:
        if fg != 'default':
            c.append("f-{0}{1}".format('bold-' if bold else '',fg))
        if bg != 'default':
            c.append("b-{0}".format(bg))

    if bold: c.append("bold")
    if italics: c.append("italics")
    if underscore: c.append("underscore")
    if strikethrough: c.append("strikethrough")
    if reverse:
        c.append("reverse")
    c.extend(additional_classes)
    return " ".join(c)

def equal_attrs(chartuple0, chartuple1):
    """
    Return True if both _Char tuples have the same attributes set.
    """
    return \
        chartuple0 \
        and chartuple1 \
        and (chartuple0._replace(data="") \
                 == chartuple1._replace(data=""))

class CursorMarker():
    def __init__(self, ch, cursorclass):
        self.char = ch
        self.cursorclass = cursorclass

def group_by_attrs(line):
    """
    Return a list of groups of _Char tuples having the same attributes.
    """
    prev_tuple = None
    groups = []
    cursorpos = line.cursorpos
    cursorclass = line.cursorclass

    for i, chartuple in enumerate(line):
        if cursorpos==i:
            groups.append(CursorMarker(chartuple, cursorclass))
            prev_tuple = None
        elif equal_attrs(prev_tuple, chartuple):
            groups[-1].append(chartuple)
            prev_tuple = chartuple
        else:
            groups.append([chartuple])
            prev_tuple = chartuple

    return groups

def unicode_escape_char(c):
    return "\\u%s" % ("%x" % ord(c)).rjust(4,'0')

def create_span(group):
    def _span(cl, contents):
        if cl:
            return '<span class="{0}">{1}</span>'.format(cl, contents)
        else:
            return '<span>{0}</span>'.format(contents)
    if isinstance(group, list):
        cl = create_class_string(group[0])
        return _span(cl, cgi.escape("".join(map(lambda ch: ch.data, group))))
    elif isinstance(group, CursorMarker):
        cl = create_class_string(group.char, [group.cursorclass])
        return _span(cl, cgi.escape(group.char.data))
    else:
        return _span("", "")

def renderline(line):
    """
    Given a line of pyte.Chars, create a string of spans with appropriate style.
    """
    return "".join(map(lambda x:  create_span(x), group_by_attrs(line)))

def wrap_in_span(s):
    return '<span>{0}</span>'.format(s)

def render_all_js(screen):
    return """document.getElementById("term").innerHTML = {0};""".format(json.dumps("\n".join(map(wrap_in_span, map(renderline, screen)))))

def set_line_to(i, content):
    return """term.setLine({0}, {1});""".format(i, json.dumps(content))


# screen events, return a js string
class EventRenderer():

    @staticmethod
    def reset(lines):
        if lines:
            return "term.reset({});\n{}" \
                .format(len(lines),
                        "\n".join([set_line_to(i,renderline(l))
                                   for i,l in enumerate(lines)]))
        else:
            return "term.reset();"

    @staticmethod
    def pop(index, line):
        return "term.removeLine({});".format(index)

    @staticmethod
    def pop_bottom():
        return "term.removeLastLine();"

    @staticmethod
    def append(line):
        if line.changed:
            content = renderline(line)
            return "term.appendLine({});".format(json.dumps(content))
        else:
            return ""

    @staticmethod
    def insert(index, line):
        if isinstance(line, termscreen.IframeLine):
            return 'term.insertIframe({}, {}, {});'.format(index, json.dumps(line.id), json.dumps(line.args))
        else:
            content = renderline(line)
            return "term.insertLine({}, {});".format(index, json.dumps(content))

    @staticmethod
    def iframe(content):
        return 'term.iframeWrite({});'.format(json.dumps(content))

    @staticmethod
    def iframe_close():
        return 'term.iframeCloseDocument();'

    @staticmethod
    def iframe_leave():
        return 'term.iframeLeave();'

    @staticmethod
    def iframe_execute(source):
        """Execute and discard the result."""
        def _iframe_execute(pty, browser, gtkthread):
            gtkthread.invoke(lambda : bool(browser.webview.eval_js_in_last_frame("", source)))
            logging.debug('iframe-execute: {}'.format(source))
        return _iframe_execute

    @staticmethod
    def iframe_eval(source):
        """Execute and write the result to the pty."""
        def eval_and_write_to_pty(js_str, pty, browser):
            ret = browser.webview.eval_js_in_last_frame("", js_str)
            logging.debug('iframe-eval: {} -> {}'.format(js_str, ret))
            pty.q_write(("\033Rresult\033;", base64.encodestring(ret), "\033Q", "\n"))

        def _iframe_eval(pty, browser, gtkthread):
            gtkthread.invoke(eval_and_write_to_pty, source, pty, browser)

        return _iframe_eval

    @staticmethod
    def set_title(title):
        def _set_title(pty, browser, gtkthread):
            gtkthread.invoke(lambda : browser.set_title(title))
        return _set_title

class Pty(object):

    def __init__(self, size=(80, 25)):
        pid, master = os.forkpty()
        if pid == 0:
            # child
            os.putenv('TERM', 'xterm')
            os.putenv('COLORTERM', 'Terminal')
            os.putenv('COLUMNS', str(size[0]))
            os.putenv('LINES', str(size[1]))
            shell = pwd.getpwuid(os.getuid()).pw_shell
            shell_name = os.path.basename(shell)
            os.execl(shell, shell_name)
        else:
            # parent
            pass
        self._running = True
        self._size = [0,0]
        self._pty = master
        self._server = None # must be set later

        self._focus = True

        self.screen = TermScreen(*size)
        self.last_cursor_line = 0
        self.stream = SchirmStream()
        self.stream.attach(self.screen)

        self.set_size(*size)

        # set up input (schirm -> pty) queue and a consumer thread that
        # pops off functions and executes them
        # used to serialize input (keys, resize events, http responses, ...)
        self.input_queue = Queue.Queue()

        def process_queue_input():
            while 1:
                self.input_queue.get(block=True)()

        t = threading.Thread(target=process_queue_input)
        t.daemon = True
        t.start()

        # set up output (pty -> schirm) queue
        # and a default producer which os.reads from the pty
        # to get simple asyncronous/interruptible os.read without
        # dealing with signals
        self.output_queue = Queue.Queue()
        def read_from_pty():
            try:
                while 1:
                    self.output_queue.put(os.read(self._pty, 8192))
            except OSError, e:
                # self._pty was closed or reading interrupted by a
                # signal -> application exit
                self._running = False
                self.output_queue.put('') # trigger the pty_loop

        t = threading.Thread(target=read_from_pty)
        t.start()

    def q_write(self, s):
        "Queued version of self.write()."
        self.input_queue.put(lambda : self.write(s))

    def q_write_iframe(self, s):
        "Write content to the PTYs stdin only if its in iframe mode."
        self.input_queue.put(lambda : self.write(s) if self.screen.iframe_mode else None)

    def q_set_size(self, h, w):
        "Queued version of self.set_size()"
        self.input_queue.put(lambda : self.set_size(h, w))

    def q_resize(self, lines, cols):
        self.input_queue.put(lambda : self.resize(lines, cols))

    def q_echo_on(self):
        self.input_queue.put(lambda : self.echo_on())

    def q_echo_off(self):
        self.input_queue.put(lambda : self.echo_off())

    def q_set_focus(self, focus=True):
        self.input_queue.put(lambda : self.set_focus(focus))

    def write(self, s):
        """
        Writes the given string or each string in the given iterator to
        the pty.
        """
        if isinstance(s, basestring):
            os.write(self._pty, s)
        else:
            for x in s:
                os.write(self._pty, x)

    def fake_input(self, input_string):
        # TIOCSTI const char *argp
        # Insert the given byte in the input queue.
        # doesn't work
        fcntl.ioctl(self._pty, termios.TIOCSTI, input_string)

    def q_fake_input(self, input_string):
        self.input_queue.put(lambda : self.fake_input(input_string))

    def running(self):
        """Return True if the shell process is still running."""
        return self._running

    def set_size(self, h, w): # h/lines, w/columns
        """
        Use the TIOCSWINSZ ioctl to change the size of _pty if neccessary.
        """
        oldw, oldh = self._size
        if oldw != w or oldh != h and w > 0 and h > 0:
            empty_win = struct.pack('HHHH',0,0,0,0)
            win = fcntl.ioctl(self._pty, termios.TIOCGWINSZ, empty_win)
            _h,_w,x,y = struct.unpack('HHHH', win)
            win = struct.pack('HHHH', h, w, x, y)
            fcntl.ioctl(self._pty, termios.TIOCSWINSZ, win)
            self._size = [w, h]

    def set_webserver(self, server):
        self._server = server

    def resize(self, lines, cols):
        self.screen.resize(lines, cols)
        self.set_size(lines, cols)

    def set_focus(self, focus=True):
        """Setting the focus flag currently changes the way the cursor is rendered."""
        self._focus = bool(focus)

        # redraw the terminal with the new focus settings
        self.output_queue.put('')

    def read_and_feed(self):
        res = self.output_queue.get(block=True)
        if res:
            self.stream.feed(res)

    def render_changes(self):
        """
        Find changes and return a list of strings.
        """
        q = []
        lines = self.screen.linecontainer
        
        if not self.screen.cursor.hidden and not self.screen.iframe_mode:
            # make sure the terminal cursor is drawn
            lines.show_cursor(self.screen.cursor.y,
                              self.screen.cursor.x,
                              'cursor' if self._focus else 'cursor-inactive')

        events = lines.get_and_clear_events()

        triggers = {}
        for e in events:
            # iframe events do sometimes more than just updating the
            # screen
            if e[0] == 'iframe_register_resource':
                self._server.register_resource(*e[1:])
            elif e[0] == 'iframe_respond':
                self._server.respond(e[1], e[2])
            elif e[0] == 'iframe_enter':
                # Make sure we have no old resources.
                # The embedded webkit takes some time to load
                # resources, so we want them to be around even if we
                # already left iframe mode.
                #self._server.clear_resources()
                pass
            elif e[0] == 'iframe_leave':
                q.append(EventRenderer.iframe_close())
                q.append(EventRenderer.iframe_leave())
            elif e[0] == 'iframe_debug':
                print e[1]
            elif e[0] == 'set_title':
                q.append(EventRenderer.set_title(e[1]))
            else:
                # plain old terminal screen updating
                q.append(getattr(EventRenderer, e[0])(*e[1:]))

        # line changes
        line_q = []
        for i,line in enumerate(lines):
            if line.changed:
                line.changed = False
                line_q.append(set_line_to(i, renderline(line)))
        q.append("\n".join(line_q))

        if not self.screen.cursor.hidden and not self.screen.iframe_mode:
            # make sure our current cursor will be deleted next time
            # we update the screen
            lines.hide_cursor(self.screen.cursor.y)

        return q

    def read_and_feed_and_render(self):
        self.read_and_feed()
        return self.render_changes()

    def paste(self, data):
        """Write data into the terminals stdin.

        When in plain terminal mode, paste data and return True. When
        in iframe_mode, do nothing and return False.
        """
        if self.screen.iframe_mode:
            return False
        else:
            self.q_write(data)
            return True

    # VT100 Key    Standard    Applications     IBM Keypad
    # =====================================================
    #
    #                                           NUMLOK - On
    # Keypad:
    #
    #    0            0           ESC O p           0
    #    1            1           ESC O q           1
    #    2            2           ESC O r           2
    #    3            3           ESC O s           3
    #    4            4           ESC O t           4
    #    5            5           ESC O u           5
    #    6            6           ESC O v           6
    #    7            7           ESC O w           7
    #    8            8           ESC O x           8
    #    9            9           ESC O y           9
    #    -            -           ESC O m           -
    #    ,            ,           ESC O l      * (on PrtSc key)
    #    .            .           ESC O n           .
    # Return       Return         ESC O M           +
    #
    #
    #                                          NUMLOK - Off
    # Arrows:
    #
    #    Up        ESC [ A        ESC O A           Up
    #   Down       ESC [ B        ESC O B          Down
    #   Right      ESC [ C        ESC O C          Right
    #   Left       ESC [ D        ESC O D          Left
    #
    #    Up        ESC [ A        ESC O A          Alt 9
    #   Down       ESC [ B        ESC O B          Alt 0
    #   Right      ESC [ C        ESC O C          Alt -
    #   Left       ESC [ D        ESC O D          Alt =
    #   Note that either set of keys may be used to send VT100 arrow keys.
    #   The Alt 9,0,-, and = do not require NumLok to be off.
    #
    # Functions:
    #
    # PF1 - Gold   ESC O P        ESC O P           F1
    # PF2 - Help   ESC O Q        ESC O Q           F2
    # PF3 - Next   ESC O R        ESC O R           F3
    # PF4 - DelBrk ESC O S        ESC O S           F4

    _keycodes = {
        # gtk-keyname: (cursor-positioning-mode, applications-mode)
        # gtk-keyname: cursor-positioning-mode
        'Up'   : ("\x1b[A", "\x1bOA"),
        'Down' : ("\x1b[B", "\x1bOB"),
        'Right': ("\x1b[C", "\x1bOC"),
        'Left' : ("\x1b[D", "\x1bOD"),

        'F1'   : "\x1bOP",
        'F2'   : "\x1bOQ",
        'F3'   : "\x1bOR",
        'F4'   : "\x1bOS",
        'F5'   : "\x1b[15~",
        'F6'   : "\x1b[17~",
        'F7'   : "\x1b[18~",
        'F8'   : "\x1b[19~",
        'F9'   : "\x1b[20~",
        'F10'  : "\x1b[21~",
        'F11'  : "\x1b[23~",
        'F12'  : "\x1b[24~",

        'Insert'    : "\x1b[2~",
        'Delete'    : "\x1b[3~",
        'Home'      : "\x1bOH",
        'End'       : "\x1bOF",
        'Page_Up'   : "\x1b[5~",
        'Page_Down' : "\x1b[6~",

        # those need a mapping because gtk doesn't supply strings for
        # them:
        'BackSpace' : "\x08",
        'Tab'       : "\t"
    }

    # see: http://rtfm.etla.org/xterm/ctlseq.html, xterm behaviour
    # append ';' and this id before the final character in the escseq
    # from _keycodes to encode modifier keys
    # 2    Shift
    # 3    Alt
    # 4    Shift + Alt
    # 5    Control
    # 6    Shift + Control
    # 7    Alt + Control
    # 8    Shift + Alt + Control
    _mod_map = {
        # (shift, alt, control): id
        (True,  False, False): 2,
        (False, True,  False): 3,
        (True,  True,  False): 4,
        (False, False, True ): 5,
        (True,  False, True ): 6,
        (False, True,  True ): 7,
        (True,  True,  True ): 8,
    }

    def map_key(self, keyname, modifiers):
        """
        Map gtk keynames to vt100 keysequences.
        Return None if there os no mapping for a given key, meaning
        that the reported string value will work just fine.
        Modifiers should be a tuple of 3 booleans: (shift, alt,
        control) denoting the state of the modifier keys.
        """
        def _add_modifier(esc_seq):
            if esc_seq and any(modifiers):
                return "".join((esc_seq[:-1],
                                ";", str(self._mod_map.get(modifiers)),
                                esc_seq[-1]))
            else:
                return esc_seq

        keydef = self._keycodes.get(keyname)
        if isinstance(keydef, tuple):
            if pyte.mo.DECAPP in self.screen.mode:
                return _add_modifier(keydef[1])
            else:
                return _add_modifier(keydef[0])
        else:
            return _add_modifier(keydef)
