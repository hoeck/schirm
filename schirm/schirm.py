#!/usr/bin/env python
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

import sys
import signal
import os
import re
import time
import urllib
import mimetypes
import threading
import logging
import argparse
import warnings
import urlparse
import base64
import pkg_resources
import types
import Queue
import json
import traceback

import gtkui
import term
import terminalio

ESC = "\033"
SEP = ESC + ";"
START_REQ = ESC + "R" + "request" + SEP
END = ESC + "Q"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

def init_logger(level=logging.ERROR):
    l = logging.getLogger('schirm')
    h = logging.StreamHandler()
    f = logging.Formatter("%(name)s - %(message)s")

    h.setFormatter(f)
    l.addHandler(h)
    if level:
        l.setLevel(level)
    return l

logger = init_logger()

def init_dotschirm():
    """Create ~/.schirm/ and or missing files in it."""
    if not os.path.exists(os.path.expanduser('~')):
        return

    dotschirm = os.path.expanduser('~/.schirm/')
    if not os.path.exists(dotschirm):
        os.mkdir(dotschirm)

    user_css = os.path.join(dotschirm, 'user.css')
    if not os.path.exists(user_css):
        with open(user_css, 'w') as f:
            f.write(pkg_resources.resource_string("schirm.resources", "user.css"))

def get_config_file_path(filename):
    """Return the full path for a file in ~/.schirm/<filename>.

    If it does not exist, return the one from resources.
    """
    config = os.path.join(os.path.expanduser('~/.schirm'), filename)
    if os.path.exists(config):
        return config
    else:
        resource = pkg_resources.resource_filename('schirm.resources', filename)
        if not os.path.exists(resource):
            raise Exception("Unknown resource: %r" % (filename, ))
        return None

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

class Schirm(object):

    def __init__(self, uiproxy):
        # pty, webview, webserver -> schirm communication
        # each message on output queue is a tuple of: (typename, attrdict-value)
        # TODO: would be easier to directly enqueue functions + their arguments
        self.input_queue = Queue.Queue(1)

        self.uiproxy = uiproxy
        self.resources = {} # iframe_id -> resource name -> data

        # load the terminal ui
        self._term_uri = "http://termframe.localhost/term.html"
        self.uiproxy.execute_script("termInit();") # first to be executed after document load
        self.uiproxy.load_uri(self._term_uri)

        self.terminal_io = terminalio.PseudoTerminal(size=[80,24])

        # connect the terminal emulator with the pty and the ui
        self.emulator = term.Terminal(terminal_ui=self,
                                      terminal_io=self.terminal_io,
                                      size=[80,24])

        # start workers
        term_worker = threading.Thread(target=self.term_worker)
        term_worker.setDaemon(True)
        term_worker.start()

        # set up a default producer which os.reads from the pty
        # to get simple asyncronous/interruptible os.read without
        # dealing with signals
        read_worker = threading.Thread(target=self.term_read_worker)
        read_worker.setDaemon(True)
        read_worker.start()

    # API required to respond to requests and execute javascript

    def make_response(self, mimetype, data):
        """Return a string making up an HTML response."""
        return "\n".join(["HTTP/1.1 200 OK",
                          "Cache-Control: " + "no-cache",
                          "Connection: close",
                          "Content-Type: " + mimetype,
                          "Content-Length: " + str(len(data)),
                          "",
                          data])

    def guess_type(self, name):
        """Given a path to a file, guess its mimetype."""
        guessed_type, encoding = mimetypes.guess_type(name, strict=False)
        return guessed_type or "text/plain"

    def respond(self, req_id, data=None, close=True):
        self.uiproxy.respond(req_id, data, close)

    def respond_resource_file(self, req_id, path):
        if os.path.isabs(path):
            # external resource (e.g. user.css file in ~/.schirm/)
            f = None
            try:
                with open(path, 'r') as f:
                    data = f.read()
                self.respond(req_id, self.make_response(self.guess_type(path), data))
            except:
                self.respond(req_id)

        else:
            # internal, packaged resource
            data = pkg_resources.resource_string('schirm.resources', path)
            self.respond(req_id, self.make_response(self.guess_type(path), data))

    def execute(self, src):
        if isinstance(src, basestring):
            js = [src]
        else:
            js = []
        self.uiproxy.execute_script(src)

    def set_title(self, title):
        pass

    # ui callbacks

    def request(self, req):
        self.input_queue.put(('request', req))

    def keypress(self, key):
        self.input_queue.put(('keypress', key))

    def set_focus(self, focus):
        self.input_queue.put(('set_focus', focus))

    def resize(self, size):
        self.input_queue.put(('resize', size))

    # terminal emulation event loop

    def term_read_worker(self):
        try:
            while True:
                res = self.terminal_io.read()
                put_nowait_sleep(self.input_queue, res)
                if isinstance(res, tuple) and res[0] == 'pty_read_error':
                    return
        except:
            traceback.print_exc()
            self.uiproxy.quit()

    def term_worker(self):
        try:
            while True:
                self.emulator.advance((self.input_queue.get(),))
        except:
            traceback.print_exc()
            # todo: proper error handling:
            # do not close the whole terminal, instead, stop the
            # current tab, maybe use a red background/border to
            # indicate an error
            self.uiproxy.quit()

def create_log_filter(filter=lambda record: True):
    class _Filter(logging.Filter):

        def __init__(self, fn):
            self._f = f

        def filter(self, record):
            if f(record):
                return 1
            else:
                return 0

    return _Filter(filter)

def main():
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("-c", "--console-log", help="write all console.log messages to stdout (use -cc to include document URL and linenumber, -ccc to include schirm-internal usages of console.log)", action="count")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel([None, logging.INFO, logging.DEBUG][max(0, min(2, args.verbose))])

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    if args.console_log:
        cl = gtkui.PageProxy.console_logger
        cl.setLevel([None, logging.INFO, logging.DEBUG][max(0, min(2, args.console_log))])
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(name)s - %(message)s"))
        cl.addHandler(h)

    init_dotschirm()
    gtkui.PageProxy.start(Schirm)
    gtkui.PageProxy.new_tab()

if __name__ == '__main__':
    main()
