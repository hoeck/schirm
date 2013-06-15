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
import time

__all__ = ('start_browser', )

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

def firefox_configure_profile(config_dir, host, port):
    # set the proxy in prefs.js
    prefs_js = subprocess.check_output("find -name 'prefs.js'", shell=True, cwd=config_dir).strip()
    if not prefs_js:
        raise Exception("Cannot find prefs.js in firefox profile %r" % config_dir)

    with open(os.path.join(config_dir, prefs_js), "a") as f:
        f.write('user_pref("network.proxy.http", %s);\n' % json.dumps(host))
        f.write('user_pref("network.proxy.http_port", %s);\n' % json.dumps(port))
        f.write('user_pref("network.proxy.type", 1);\n') # 1 .. use manual proxy settings
        f.write('user_pref("network.proxy.no_proxies_on","");\n') # use proxy on localhost too

        # other ff customizations:
        f.write('user_pref("browser.tabs.autoHide", true);\n')
        f.write('user_pref("browser.rights.3.shown", true);\n')

    # hide the address and menubars
    # not sure how well this will work across different ff versions
    with open(os.path.join(config_dir, 'localstore.rdf'), "w") as f:
        f.write("""<?xml version="1.0"?>
<RDF:RDF xmlns:NC="http://home.netscape.com/NC-rdf#"
         xmlns:RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <RDF:Description RDF:about="chrome://browser/content/browser.xul">
    <NC:persist RDF:resource="chrome://browser/content/browser.xul#toolbar-menubar"/>
    <NC:persist RDF:resource="chrome://browser/content/browser.xul#nav-bar"/>
  </RDF:Description>
  <RDF:Description RDF:about="chrome://browser/content/browser.xul#toolbar-menubar"
                   autohide="true" />
  <RDF:Description RDF:about="chrome://browser/content/browser.xul#nav-bar"
                   collapsed="true" />
</RDF:RDF>
""")

class BrowserProcess(object):

    def __init__(self, proc, profilepath):
        self.proc = proc
        self.profilepath = profilepath
        self.state = 'running'

    def kill(self, *args, **kwargs):
        if self.state != 'killed':
            self.state = 'killed'
            self.proc.kill(*args, **kwargs)

    def wait_and_cleanup(self):
        try:
            self.proc.wait()
        except KeyboardInterrupt, e:
            pass

        logger.debug('removing profile: %r', self.profilepath)
        for _ in range(10):
            try:
                shutil.rmtree(self.profilepath)
                logger.debug('removing profile: done')
                return
            except OSError, e:
                logger.debug('removing profile: error (%s)', e)
                time.sleep(0.1)

def start_browser(url,
                  proxy_host,
                  proxy_port):
    """Start firefox, chromium or google-chrome.

    Use a temporary profile, set proxy host and port and try to run the browser
    in a minimal-chrome configuration.
    """

    commands = ['chromium-browser', 'google-chrome', 'firefox', 'firefox-bin']
    available = (filter(is_available, commands) or [None])[0]

    # use a process group to kill all the browsers processes at
    # once on exit
    os.setpgid(os.getpid(), os.getpid())

    proxy_url = '%s:%s' % (proxy_host, proxy_port)
    url = 'http://termframe.localhost/term.html'

    ensure_dir('~/.schirm')

    if available and 'chrom' in available:
        # chrome-like browser
        # setup a temporary profile for each browser
        config_dir = tempfile.mkdtemp(prefix='chrome_profile',
                                      dir=os.path.join(os.path.expanduser('~/.schirm')))
        #atexit.register(lambda: shutil.rmtree(config_dir))

        args = ['--user-data-dir=%s' % config_dir, # google-chrome has no --temp-profile option
                '--proxy-server=%s' % proxy_url,
                '--app=%s' % url]
        cmd = [available] + args
        logger.info("starting browser: %s", ' '.join(cmd))
        p = subprocess.Popen(cmd)
        return BrowserProcess(proc=p, profilepath=config_dir)

    elif available and 'fire' in available:
        # firefox
        config_dir = tempfile.mkdtemp(prefix='firefox_profile',
                                      dir=os.path.join(os.path.expanduser('~/.schirm')))
        #atexit.register(lambda: shutil.rmtree(config_dir))

        # create a temporary profile in .schirm to be able to find and manipulate it
        profile = "schirm-%s" %  uuid.uuid4()
        subprocess.check_call([available] + ['-no-remote', '-CreateProfile', "%s %s" % (profile, config_dir)])
        firefox_configure_profile(config_dir, host=proxy_host, port=proxy_port)

        cmd = [available] + ['-no-remote',
                             '-profile', config_dir,
                             '-new-window', url]
        logger.info("starting browser: %s" % cmd)
        p = subprocess.Popen(cmd)
        return BrowserProcess(proc=p, profilepath=config_dir)

    else:
        raise Exception("No suitable browser found!")
