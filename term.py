import sys; sys.path.append("/home/timmy-turner/src/pyte")

import os
import simplejson
import fcntl
import termios

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

        self.screen = pyte.Screen(*size)
        self.stream = pyte.Stream()
        self.stream.attach(self.screen)

    def write(self, s):
        os.write(self._pty, s)

    def set_size(self, w, h):
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
    
    # def read(self):
    #     #return json_escape(os.read(self._pty, 1024))
    #     return json_escape_all_u(os.read(self._pty, 2048))
    #     #return simplejson.dumps(os.read(self._pty, 1024))
    def read(self):
        return os.read(self._pty, 2048)
        #return os.read(self._pty, 2048)

