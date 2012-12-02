# -*- coding: utf-8 -*-

import subprocess

import schirm
import webserver

def start_chromium(proxy_port):
    cmd = ' '.join(('chromium-browser',
                    '--temp-profile', # temp-profile must come first!
                    '--proxy-server="localhost:%s"' % proxy_port,
                    '--app="http://termframe.localhost/term.html"',
                    ))
    return subprocess.Popen(cmd, shell=True)

class UIProxy(object):
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
        print "QUIT"

# TODO: sort this out
ws = None

def start():
    global ws
    s = schirm.Schirm(UIProxy(), websocket_proxy_hack=False)
    ws = webserver.Server(s)
    p = start_chromium(ws.getport())
    p.wait()
