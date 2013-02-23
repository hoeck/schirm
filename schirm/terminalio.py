import os
import pwd
import struct
import fcntl
import termios
import signal
import subprocess

def _debug(s):
    print "IO:", repr(s.replace("\x1b[", '<CSI>').replace("\x1b", '<ESC>'))
    return s

def create_terminal(size=(80,25), use_pty=True, cmd=None):
    if not cmd:
        # start the current users default login shell
        cmd = pwd.getpwuid(os.getuid()).pw_shell

    env = {'TERM': 'xterm',
           'COLORTERM': 'Terminal',
           'COLUMNS': str(size[0]),
           'LINES': str(size[1])}

    if use_pty:
        return PseudoTerminal(cmd, size, env)
    else:
        return SubprocessTerminal(cmd, size, env)

class PseudoTerminal(object):

    def __init__(self, cmd, size, env):
        self.size = size

        # args
        if isinstance(cmd, basestring):
            cmd = cmd.split()

        executable = cmd[0]
        args = [os.path.basename(cmd[0])] + cmd[1:]

        # start the pty
        pid, master = os.forkpty()
        if pid == 0:
            # child
            for k,v in env.items():
                os.putenv(k, v)

            os.execl(executable, *args)
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

class SubprocessTerminal(object):

    def __init__(self, cmd, size, env):
        # just connect the terminal to a process without using a
        # pty device
        p = subprocess.Popen(cmd,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             shell=True,
                             env=env)
        self.proc = p

    def write(self, data):
        if data == '\x03': # ctrl-c
            self.proc.send_signal(signal.SIGINT)
            return
        elif data == '\x04': # ctrl-d
            self.proc.stdin.close()
            return
        else:
            if isinstance(data, basestring):
                self.proc.stdin.write(data)
            else:
                for x in data:
                    self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def read(self):
        """Read data from the pty and return it."""
        try:
            data = self.proc.stdout.read()
            if data:
                return data
            else:
                return ('pty_read_error', None)
        except OSError, e:
            # stdout was closed or reading interrupted by a
            # signal -> application exit
            return ('pty_read_error', None)

    def set_size(self, lines, columns):
        pass
