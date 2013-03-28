# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import signal
import logging
import shutil
import tempfile
import uuid
import atexit
import json

import schirm
import webserver

logger = logging.getLogger(__name__)

def ensure_dir(dir):
    dir = os.path.expanduser(dir)
    if not os.path.exists(dir):
        os.mkdir(dir)

def is_available(cmd):
    try:
        subprocess.check_output([cmd, '--version'])
        return True
    except OSError:
        return False

def firefox_profile_set_proxy(config_dir, host, port):
    # set the proxy in prefs.js
    prefs_js = subprocess.check_output("find -name 'prefs.js'", shell=True, cwd=config_dir).strip()
    if not prefs_js:
        raise Exception("Cannot find prefs.js in firefox profile %r" % config_dir)

    with open(os.path.join(config_dir, prefs_js), "a") as f:
        f.write('user_pref("network.proxy.http", %s);\n' % json.dumps(host))
        f.write('user_pref("network.proxy.http_port", %s);\n' % json.dumps(port))
        f.write('user_pref("network.proxy.type", 1);\n') # 1 .. use manual proxy settings
        f.write('user_pref("network.proxy.no_proxies_on","");\n') # use proxy on localhost too

def start_browser(proxy_port):

    commands = ['chromium-browser', 'google-chrome', 'firefox', 'firefox-bin']
    available = (filter(is_available, commands) or [None])[0]

    # use a process group to kill all the browsers processes at
    # once on exit
    os.setpgid(os.getpid(), os.getpid())

    proxy = 'localhost:%s' % proxy_port
    url = 'http://termframe.localhost/term.html'

    ensure_dir('~/.schirm')

    if available and 'chrom' in available:
        # chrome-like browser
        # setup a temporary profile for each browser
        config_dir = tempfile.mkdtemp(prefix='chrome_profile',
                                      dir=os.path.join(os.path.expanduser('~/.schirmm')))
        atexit.register(lambda: shutil.rmtree(config_dir))

        args = ['--user-data-dir=%s' % config_dir, # google-chrome has no --temp-profile option
                '--proxy-server=%s' % proxy,
                '--app=%s' % url]
        cmd = [available] + args
        logger.info("starting browser: %s", ' '.join(cmd))
        p = subprocess.Popen(cmd)
        return p

    elif available and 'fire' in available:
        # firefox
        config_dir = tempfile.mkdtemp(prefix='firefox_profile',
                                      dir=os.path.join(os.path.expanduser('~/.schirm')))
        atexit.register(lambda: shutil.rmtree(config_dir))

        # create a temporary profile in .schirm to be able to find and manipulate it
        profile = "schirm-%s" %  uuid.uuid4()
        subprocess.check_call([available] + ['-CreateProfile', "%s %s" % (profile, config_dir)])
        firefox_profile_set_proxy(config_dir, host='localhost', port=proxy_port)

        cmd = [available] + ['-profile', config_dir,
                             '-new-window', url]
        logger.info("starting browser: %s" % cmd)
        p = subprocess.Popen(cmd)
        return p

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
        p.kill()

    s = schirm.Schirm(UIProxy(_quit),
                      websocket_proxy_hack=False,
                      use_pty=use_pty,
                      cmd=cmd)
    ws = webserver.Server(s)
    p = start_browser(ws.getport())
    p.wait()
