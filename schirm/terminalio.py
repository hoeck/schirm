import os
import pwd
import struct
import fcntl
import termios

class PseudoTerminal(object):

    def __init__(self, size=(80,25)):
        self.size = size

        # start the pty
        shell = pwd.getpwuid(os.getuid()).pw_shell
        shell_name = os.path.basename(shell)
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
            self.pid = pid
            self.master = master

    # interface

    def write(self, data):
        """Immediately write data to the terminals filedescriptor.

        Data can be a string or a list of strings.
        """
        if isinstance(data, basestring):
            os.write(self.master, data)
        else:
            for x in data:
                os.write(self.master, data)
        # flush???

    def read(self):
        """Read data from the pty and return it."""
        try:
            return os.read(self.master, 8192)
        except OSError, e:
            # self.master was closed or reading interrupted by a
            # signal -> application exit
            return ('pty_read_error', None)

    def set_size(self, lines, columns):
        """Use the TIOCSWINSZ ioctl to change the size of this pty."""
        l, c = lines, columns
        oldc, oldl = self.size
        if oldl != l or oldc != c and l > 0 and c > 0:
            empty_win = struct.pack('HHHH',0,0,0,0)
            win = fcntl.ioctl(self.master, termios.TIOCGWINSZ, empty_win)
            _l,_c,x,y = struct.unpack('HHHH', win)
            win = struct.pack('HHHH', l, c, x, y)
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, win)
            self.size = [c, l]
