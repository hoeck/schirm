import os
import pwd
import struct
import fcntl
import termios
import signal
import subprocess
import logging
import select

import chan
import utils

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
            self.state = 'running'

    # interface

    def kill(self, signal=9):
        if self.state == 'running':
            self.state = 'killed'
            os.kill(self.pid, signal)

    def getpid(self):
        return self.pid

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

    def read(self, timeout=None, additional_fd=None):
        """Read data from the pty and return it.

        Optionally provide a timeout of 0 or more seconds. Return None
        if no data is available after the timeout. Return also None
        when an OSError occurs.

        If additional_fd is not None, it should be an int denoting a
        file descriptor to select on in addition of the master pty.

        Preferably return the additional_fd integer if there is data
        on it.
        """
        try:
            if additional_fd is not None:
                select_on = [self.master, additional_fd]
            else:
                select_on = [self.master]

            res, _, _  = select.select(select_on,[],[],timeout)
            if res == []:
                return None # closed???
            elif additional_fd in res:
                return additional_fd
            else:
                # read
                res = [os.read(self.master, 4096)]

                # Read more than 4k (the default unchangeble linux buffer
                # size) of data at once, to be able to deliver bigger
                # chunks to the emulator
                while select.select([self.master],[],[],0) == ([self.master],[],[]):
                    res.append(os.read(self.master, 4096))
                return "".join(res)
        except OSError, e:
            # self.master was closed or reading interrupted by a
            # signal -> application exit
            self.state = 'closed'
            return None

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
            return True

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
        self.state = 'running'

    def kill(self, signal):
        if self.state == 'running':
            self.state = 'killed'
            self.proc.kill(signal)

    def getpid(self):
        return self.proc.pid

    def write(self, data):
        if data == '\x03': # ctrl-c
            self.proc.send_signal(signal.SIGINT)
            return
        elif data == '\x04': # ctrl-d
            self.state = 'closed'
            self.proc.stdin.close()
            return
        else:
            if isinstance(data, basestring):
                self.proc.stdin.write(data)
            else:
                for x in data:
                    self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def read(self, timeout=None, additional_fd=None):
        """Read data from the pty and return it."""
        try:
            data = os.read(self.proc.stdout.fileno(), 8192)
            if data:
                return data
            else:
                self.state = 'closed'
                return None
        except OSError, e:
            # stdout was closed or reading interrupted by a
            # signal -> application exit
            self.state = 'closed'
            return None

    def set_size(self, lines, columns):
        return False


class AsyncResettableTerminal(object):

    def __init__(self, use_pty, cmd):
        self.out = chan.Chan()
        self._in = chan.Chan()

        self._use_pty = use_pty
        self._cmd = cmd

        self._client = None

        # use a pipe to send resize requests to the client_read thread,
        # to be able to select on both, this pipe and the master pty
        r,w = os.pipe()
        self._resize_read  = os.fdopen(r, 'r', 0)
        self._resize_write = os.fdopen(w, 'w', 0)

        def _in_handler():
            while True:
                self._in.get()()

        utils.create_thread(_in_handler)
        self.reset()

    def _reset(self):
        self._kill()

        self._client = create_terminal(use_pty=self._use_pty,
                                       cmd=self._cmd)

        # read from the client and push onto outgoing
        def _client_read():
            while True:

                # receive resize events from the resize pipe,
                # terminal writes from the master pty
                data = self._client.read(additional_fd=self._resize_read.fileno())

                if data == self._resize_read.fileno():
                    new_size = self._resize_read.read(10)
                    lines = int(new_size[:5])
                    cols  = int(new_size[5:])

                    # read & propagate remaining data
                    data = self._client.read(timeout=0, additional_fd=None)
                    if data is not None:
                        self.out.put(data)

                    # resize
                    if self._client.set_size(lines, cols):
                        # inform screen of the new size
                        self.out.put(('resize', lines, cols))

                elif data is None:
                    # terminal client closed
                    self.out.put(None)
                    return

                else:
                    self.out.put(data)

        utils.create_thread(_client_read)

    def _kill(self):
        if self._client:
            self._client.kill()
            self._client = None

    def _write(self, data):
        self._client.write(data)

    def _set_size(self, lines, cols):
        # write sth to the resize interrupt pipe to sync client and
        # screen resize
        assert 0 < lines and lines < 99999
        assert 0 < cols  and cols  < 99999
        self._resize_write.write('%05d%05d' % (int(lines), int(cols)))
        self._resize_write.flush()

    # API

    def reset(self):
        self._in.put(self._reset)

    def kill(self):
        self._in.put(self._kill)

    def write(self, data):
        self._in.put(lambda : self._write(data))

    def set_size(self, lines, columns):
        self._in.put(lambda : self._set_size(lines, columns))
