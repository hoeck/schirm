# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import signal

import schirm
import webserver

def start_chromium(proxy_port):

    def is_available(cmd):
        try:
            subprocess.check_output([cmd, '-version'])
            return True
        except OSError:
            return False

    commands = ['chromium-browser', 'google-chrome']
    available = filter(is_available, commands)

    # use a process group to kill all the browsers processes at
    # once on exit
    os.setpgid(os.getpid(), os.getpid())

    if available:
        cmd = available[0]
        args = ['--temp-profile', # temp-profile must come first!
                '--proxy-server=localhost:%s' % proxy_port,
                '--app=http://termframe.localhost/term.html']
        return subprocess.Popen([cmd] + args)
    else:
        raise Exception("No suitable browser found!")

class UIProxy(object):

    def __init__(self, quit_cb=None):
        self.quit_cb = quit_cb

    def execute_script(self, src):
        print "execute script", repr(src)

    def load_uri(self, uri):
        print "load_uri", uri

    def respond(self, requestid, data, close=True):
        ws.respond(requestid, data, close)

    def set_title(self, title):
        print "uh oh"

    def close(self):
        # close the tab
        print "close"

    def quit(self):
        if self.quit_cb:
            self.quit_cb()

# TODO: sort this out
ws = None

def start(use_pty=True, cmd=None):
    global ws

    p = None
    def _quit():
        os.killpg(os.getpid(), signal.SIGTERM)

    s = schirm.Schirm(UIProxy(_quit),
                      websocket_proxy_hack=False,
                      use_pty=use_pty,
                      cmd=cmd)
    ws = webserver.Server(s)
    p = start_chromium(ws.getport())
    p.wait()
