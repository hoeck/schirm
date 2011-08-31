# -*- coding: utf-8 -*-
import sys; sys.path.append("/home/timmy-turner/src/pyte")

import os
import simplejson
import fcntl
import termios
import itertools
import cgi
import json
import struct

from itertools import cycle
from UserList import UserList

import pyte

import termscreen
from termscreen import TermScreen

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
        if fg != 'default':
            c.append("f-{0}".format(bg))
        if bg != 'default':
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
    def __init__(self, ch):
        self.char = ch

def group_by_attrs(line, cursorpos=None):
    """
    Return a list of groups of _Char tuples having the same attributes.
    """
    prev_tuple = None
    groups = []
    for i, chartuple in enumerate(line):
        if cursorpos and cursorpos==i:
            groups.append(CursorMarker(chartuple))
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
    tmpl = '<span class="{0}">{1}</span>'
    if isinstance(group, list):
        cl = create_class_string(group[0])
        return tmpl.format(cl, cgi.escape("".join(map(lambda ch: ch.data, group))))
    elif isinstance(group, CursorMarker):
        cl = create_class_string(group.char, ["cursor"])
        return tmpl.format(cl, cgi.escape(group.char.data))
    else:
        return tmpl.format("", "")

def renderline(line, cursorpos=None):
    """
    Given a line of pyte.Chars, create a string of spans with appropriate style.
    """
    return "".join(map(create_span, group_by_attrs(line, cursorpos)))

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
            return "term.reset();\n{}" \
                .format("\n".join([set_line_to(i,renderline(l))
                                   for i,l in enumerate(lines)]))
        else:
            return "term.reset();"

    @staticmethod
    def pop(index, line):
        if index == 0:
            # do not remove, let it become part of the history, but
            # apply its chages first
            return set_line_to(index, renderline(line))
        else:
            return "term.removeLine({});".format(index)

    @staticmethod
    def pop_bottom():
        return "term.removeLastLine();"

    @staticmethod
    def append(line):
        content = renderline(line)
        return "term.appendLine({});".format(json.dumps(content))

    @staticmethod
    def insert(index, line):
        if isinstance(line, termscreen.IframeLine):
            return 'term.insertIframe({}); '.format(index)
        else:
            content = renderline(line)
            return "term.insertLine({}, {});".format(index, json.dumps(content))

    @staticmethod
    def iframe(content):
        return 'term.iframeWrite({})'.format(json.dumps(content))


class Pty(object):
            
    def __init__(self, size=(80, 24)):
        pid, master = os.forkpty()
        if pid == 0:
            # child
            os.putenv('TERM', 'linux')
            os.execl("/bin/bash", "bash") # todo: use the users default shell
        else:
            # parent
            pass
        self._size = [0,0]
        self._pty = master

        self.screen = TermScreen(*size)
        self.last_cursor_line = 0
        self.stream = pyte.Stream()
        self.stream.attach(self.screen)

        self.set_size(*size)

    def write(self, s):
        os.write(self._pty, s)

    def set_size(self, h, w): # h/lines, w/columns
        """
        Use the TIOCSWINSZ ioctl to change the size of _pty if neccessary.
        """
        oldw, oldh = self._size
        if oldw != w or oldh != h and w > 0 and h > 0:
            # TIOCSSIZE
            #win = struct.pack('HHHH',0,0,0,0)
            #fcntl.ioctl(pty, termios.TIOCGSIZE, win)
            #w,h,x,y = struct.unpack('HHHH', win)
            #win = struct.pack('HHHH', widht, height, x, y)
            #fcntl.ioctl(pty, termios.TIOCSSIZE, win)

            # TIOCGWINSZ
            empty_win = struct.pack('HHHH',0,0,0,0)
            win = fcntl.ioctl(self._pty, termios.TIOCGWINSZ, empty_win)
            _h,_w,x,y = struct.unpack('HHHH', win)
            win = struct.pack('HHHH', h, w, x, y)
            fcntl.ioctl(self._pty, termios.TIOCSWINSZ, win)

            self._size = [w, h]

    def resize(self, lines, cols):
        self.screen.resize(lines, cols)

        # don't emit sigwinch when in normal mode, because it makes
        # bash (any shell?) redraw the (unchanged) prompt to be at the
        # top of the terminal, but we want it to stay where it
        # currently is
        #if self.screen._application_mode():
        self.set_size(lines, cols)


    def read(self):
        return os.read(self._pty, 2048)

    def read_and_feed(self):
        response = self.read()
        self.stream.feed(response.decode('utf-8','replace'))       

    def render_changes(self):
        js = []
        lines = self.screen.linecontainer
        events = lines.get_and_clear_events()

        for e in events:
            js.append(getattr(EventRenderer, e[0])(*e[1:]))
            
        for i,line in enumerate(lines):
            if line.changed:
                line.changed = False
                js.append(set_line_to(i, renderline(line)))

        return js


    def read_and_feed_and_render(self):
        self.read_and_feed()
        return self.render_changes()


# VT100 Key    Standard    Applications     IBM Keypad
# =====================================================

#                                           NUMLOK - On
# Keypad:

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


#                                          NUMLOK - Off
# Arrows:

#    Up        ESC [ A        ESC O A           Up
#   Down       ESC [ B        ESC O B          Down
#   Right      ESC [ C        ESC O C          Right
#   Left       ESC [ D        ESC O D          Left

#    Up        ESC [ A        ESC O A          Alt 9
#   Down       ESC [ B        ESC O B          Alt 0
#   Right      ESC [ C        ESC O C          Alt -
#   Left       ESC [ D        ESC O D          Alt =
#   Note that either set of keys may be used to send VT100 arrow keys.
#   The Alt 9,0,-, and = do not require NumLok to be off.

# Functions:

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

    def map_key(self, keyname):
        """
        Map gtk keynames to vt100 keysequences.
        Return None if there os no mapping for a given key, meaning
        that the reported string value will work just fine.
        """
        keydef = self._keycodes.get(keyname)
        if isinstance(keydef, tuple):
            if pyte.mo.DECAPP in self.screen.mode:
                return keydef[1]
            else:
                return keydef[0]
        else:
            return keydef

