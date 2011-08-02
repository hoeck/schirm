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

        self.screen = pyte.DiffScreen(*size)
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


### creating html to render the terminal contents

def create_class_string(chartuple):
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

def group_by_attrs(line):
    """
    Return a list of groups of _Char tuples having the same attributes.
    """
    prev_tuple = None
    groups = []
    for chartuple in line:
        if equal_attrs(prev_tuple, chartuple):
            groups[-1].append(chartuple)
        else:
            groups.append([chartuple])
        prev_tuple = chartuple

    return groups

def unicode_escape_char(c):
    return "\\u%s" % ("%x" % ord(c)).rjust(4,'0')

def group_to_span(group):
    tmpl = '<span class="{0}">{1}</span>'
    if group:
        cl = create_class_string(group[0])
        return tmpl.format(cl, cgi.escape("".join(map(lambda ch: ch.data, group))))
    else:
        return tmpl.format("", "")
        
def renderline(line):
    """
    Given a line of pyte.Chars, create a string of spans with appropriate style.
    """
    return "".join(map(group_to_span, group_by_attrs(line)))

def wrap_in_span(s):
    return '<span>{0}</span>'.format(s)

def render_all_js(screen):
    return """document.getElementById("term").innerHTML = {0};""".format(json.dumps("\n".join(map(wrap_in_span, map(renderline, screen)))))

def set_line_to(i, content):
    return """set_line({0}, {1});""".format(i, json.dumps(content))

def render_different(screen):
    ret = "\n".join(set_line_to(i, renderline(screen[i])) for i in screen.dirty if i < len(screen))
    screen.dirty.clear()
    return ret

