import sys; sys.path.append("/home/timmy-turner/src/pyte")

import os
import simplejson
import fcntl
import termios
import itertools
import cgi
import json
import struct

import pyte


def json_escape_all_u(src):
    dst = ""
    for c in src:
        dst += "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')
    return dst


class Screen(pyte.DiffScreen):
    
    def __init__(self, columns, lines):
        self.history = []
        super(Screen, self).__init__(columns, lines)

    def pop(self, index):
        # everything that gets popped from the top of the terminal
        # window is a good candidate for the scroll history
        if index == 0:
            self.history.append(self[index])

        return super(Screen, self).pop(index)
    

class Pty(object):
            
    def __init__(self, size=(80, 24)):
        pid, master = os.forkpty()
        if pid == 0:
            # child
            os.execl("/bin/bash", "bash") # todo: use the users default shell
        else:
            # parent
            pass
        self._size = [0,0]
        self._pty = master

        self.screen = Screen(*size)
        self.last_cursor_line = 0
        self.stream = pyte.Stream()
        self.stream.attach(self.screen)

        self.set_size(*size)

    def write(self, s):
        os.write(self._pty, s)

    def set_size(self, w, h): # w/columns, h/lines
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
            #print "set size is:", [_w, _h], "my size is:", [w, h], "(",[oldw, oldh],")"
            win = struct.pack('HHHH', h, w, x, y)
            fcntl.ioctl(self._pty, termios.TIOCSWINSZ, win)

            self._size = [w, h]
        self.screen.resize(h, w)
    
    def read(self):
        return os.read(self._pty, 2048)

    def read_and_feed(self):
        response = self.read()
        self.stream.feed(response.decode('utf-8','replace'))


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

    def render(self):
        """
        Return a string of javascript expressions.
        """
        ret = "\n".join(set_line_to(i,
                                    renderline(self.screen[i], 
                                               self.screen.cursor.x if (i==self.screen.cursor.y and not self.screen.cursor.hidden) else None))
                        for i in (self.screen.dirty | set([self.screen.cursor.y, self.last_cursor_line]))
                        if i < len(self.screen))
        self.screen.dirty.clear()
        self.last_cursor_line = self.screen.cursor.y
        return ret


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
    return """set_line({0}, {1});""".format(i, json.dumps(content))

def append_history_line(content):
    return """history_append({0});""".format(json.dumps(content))

def render_history(screen):
    ret = "\n".join(append_history_line(renderline(h)) for h in screen.history)
    screen.history = []
    return ret
    
# def render_different(screen):
#     ret = "\n".join(set_line_to(i,
#                                 renderline(screen[i], 
#                                            screen.cursor.x if (i==screen.cursor.y and not screen.cursor.hidden) else None))
#                     for i in (screen.dirty | set([screen.cursor.y]))
#                     if i < len(screen))
#     screen.dirty.clear()
#     return ret
