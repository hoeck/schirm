import os
import base64
import Queue
import logging
import threading
import subprocess
import traceback

try:
    import cProfile as profile_lib
except:
    import profile as profile_lib

logger = logging.getLogger(__name__)

def put_nowait_sleep(queue, data):
    """Given a limited queue and an object, try to put object on the queue.

    If the queue is Full, wait an increasing fraction of a second
    until trying again. Return when the data has been put on the queue.
    """
    times = 0
    wait_f = lambda x: 0.01 * (2 ** x) if x < 9 else 1.28
    while True:
        try:
            queue.put_nowait(data)
            return
        except Queue.Full:
            time.sleep(wait_f(times))
            times += 1

def get_xselection():
    try:
        return subprocess.check_output(['xsel', '-o'])
    except OSError, e:
        if e.errno == 2:
            logger.error("Install xsel to use the 'paste x selection' feature")
            return ""
        else:
            raise e

class Profile(object):

    def __init__(self, path):
        self.path = path
        self.prof = profile_lib.Profile()

    @staticmethod
    def get_create_path(path):
        """Normalize and create (if necessary) the path to the given file."""
        full_path = os.path.abspath(os.path.expanduser(path))
        path = os.path.dirname(full_path)
        if not os.path.exists(path):
            os.makedirs(path)
        return full_path

    @staticmethod
    def pimp_profile_data(profile_file, output_file):
        """
        Generates nice callgraph image (PNG) from a pstats file using gprof2dot.py
        and dot. Make sure those two are in your $PATH.
        """
        try:
            subprocess.call("gprof2dot.py -f pstats %s | dot -Tpng -o %s" % (profile_file, output_file), shell=True)
        except:
            print >> sys.stderr, "Failed to create profile data graph image, make sure gprof2dot and graphwiz are installed on your system."

    def done(self):
        full_path = self.get_create_path(self.path)
        pstats_file = full_path + ".pstats"
        png_file = full_path + ".png"
        self.prof.dump_stats(pstats_file)
        self.pimp_profile_data(pstats_file, png_file)

    def run(self, f):
        self.prof.runcall(f)

    def enable(self):
        self.prof.enable()

    def disable(self):
        self.prof.disable()

def create_thread(target, name=None, daemon=True):
    t = threading.Thread(target=target, name=name)
    if daemon:
        t.setDaemon(True)
    t.start()
    return t

def shorten(s, max=40, more='...'):
    if len(s) > max:
        return "%s%s" % (s[:max-len(more)], more)
    else:
        return s

def shorttrace():
    """Return a line:fn traceback for the bottom 3 stackframes."""
    return ' > '.join('%s:%s' % (line,fn) for file, line, fn, code in traceback.extract_stack()[-4:][:-1])

def roll_id(size=8):
    """Return a base64 encoded random number of size bytes."""
    return base64.b32encode(os.urandom(size)).lower().strip('=')
