
import os
import json
import base64
import Queue
import logging
import socket
import subprocess
import time

import pyte
import utils
import termkey
import termscreen
import termiframe
import proxyconnection

logger = logging.getLogger(__name__)

def get_config_file_contents(filename):
    """Return the contents of ~/.schirm/<filename> or None."""
    config = os.path.join(os.path.expanduser('~/.schirm'), filename)
    if os.path.exists(config):
        with open(config) as f:
            return f.read()

def roll_id():
    return base64.b32encode(os.urandom(35)).lower()

class Terminal(object):

    clojurescript_repl_url = 'http://localhost:9000'

    static_resources = {
        '/term.html': 'term.html',
        '/term.js': 'term.js',
        '/term.css': 'term.css',
        '/default-user.css': 'user.css',
        '/favicon.ico': 'schirm.png',
    }

    @classmethod
    def create_url(self, id=None):
        """Return a non-guessable localhost subdomain url for this terminal."""
        return "http://%s.localhost" % (id or roll_id())

    def __init__(self, client, size=(80,25), url=None, start_clojurescript_repl=False):
        self.client = client
        self.size = size
        self._start_clojurescript_repl = start_clojurescript_repl
        self.reset()

        # unique random id to hide the terminals url
        self.url = url or self.create_url()

    def reset(self):
        # set up the terminal emulation:
        self.screen = termscreen.TermScreen(*self.size)
        self.stream = termscreen.SchirmStream()
        self.stream.attach(self.screen)
        self.iframes = termiframe.Iframes(self.client)

        # terminal websocket
        self.websocket = None
        self.state = None # None -> 'ready' -> 'closed'

        if self._start_clojurescript_repl:
            self.screen.start_clojurescript_repl()

    # helpers

    def send_js(self, js):
        if isinstance(src, basestring):
            js = [src]
        else:
            js = src

        data = ''.join(js)
        self.websocket.send(data)

    def respond_document(self, req):
        """Respond to requests to the main terminal root url."""
        logger.info("respond-document: %r %r" % (req.id, req.url))

        if req.url_path in self.static_resources:
            req.found_resource(self.static_resources[req.url_path], module_name='schirm.resources')
        elif req.url_path == '/user.css':
            req.found(get_config_file_contents('user.css') or "", content_type="text/css")
        elif req.url_path.startswith('/localfont/') and (req.url_path.endswith('.ttf') or req.url_path.endswith('.otf')):
            # serve font files to allow using any local font in user.css via @font-face
            req.found_file(req.url_path[len('/localfont'):])
        elif req.url_path in ('', '/'):
            req.redirect(url='/term.html')
        else:
            req.notfound()

    def decode_keypress(self, key):
        """Decode a keypress into terminal escape-codes.

        Expect a namedtuple in data with .name, .shift, .alt, .control
        and .string attribs.

        Return a (possibly empty) string to feed into the terminal.
        """
        key['string'] = key.get('string', '').encode('utf-8')

        # compute the terminal key
        k = termkey.map_key(keyname=key.get('name'),
                            modifiers=(key.get('shift'), key.get('alt'), key.get('control')),
                            app_key_mode=(pyte.mo.DECAPPKEYS in self.screen.mode))

        if not k:
            if key.get('alt'):
                k = "\033%s" % key['string']
            else:
                k = key['string']

        if self.screen.iframe_mode:
            # in iframe mode, only write some ctrl-* events to the
            # terminal process
            if k and \
                    key.get('control') and \
                    (key.get('name') or '').lower() in "dcz":
                return k
        else:
            if k:
                return k

        return ''

    # websocket IPC

    def keypress(self, key):
        keycode = self.decode_keypress(key)
        self.client.write(keycode)

    def resize(self, cols, lines):
        # enforce sensible bounds
        # It looks like my bash prompt will get corrupted once I
        # resize it to 10 cols or below and then back to a normal
        # size. The same happens on other emulators too (xterm,
        # gnome-terminal).
        w = min(2**14, max(11, int(cols)))
        h = min(2**14, max(1, int(lines)))
        # The client will put a special 'resize' message on its
        # output channel after the receive happened.
        # Once we receive this, we will resize the client too.
        self.client.set_size(h, w)

    def paste_selection(self, string=None):
        """Unless None, write the given string to the client.

        When None, try to use utils.get_xselection to grab the primary
        X selection.
        """
        if string is None:
            s = utils.get_xselection()
            if s:
                self.client.write(s)
        else:
            self.client.write(string)

    def render(self, msg=None):

        # text-cursor TODO: turn that into an EVENT to toggle the cursor display
        # if not self.screen.cursor.hidden and not self.screen.iframe_mode:
        #     # make sure the terminal cursor is drawn
        #     self.screen.linecontainer.show_cursor(
        #         self.screen.cursor.y,
        #         self.screen.cursor.x,
        #         'cursor' if self.focus else 'cursor-inactive'
        #     )

        # ??????????
        if self.state != 'ready':
            logger.debug('not rendering - terminal state != ready')
            return

        # capture render events
        events = self.screen.pop_events()
        if not events:
            return

        # dispatch iframe-* events
        term_events = []
        for e in events:
            if e[0].startswith("iframe-"):
                res = self.iframes.dispatch(e)
                if res is not None:
                    term_events.append(res)
            else:
                term_events.append(e)

        self.websocket.send(json.dumps(term_events))

        return

    # handlers

    def websocket_connect(self, ws):
        # open exactly one websocket request for webkit <-> schirm communication

        if ('http://' + ws.url_netloc).startswith(self.url):
            if not self.websocket:
                ws.connected()
                self.websocket = ws
                # communication set up, render the emulator state
                self.state = 'ready'
                self.render()
            else:
                # ???
                ws.close()
        else:
            # dispatch to self.iframes
            self.iframes.websocket_connect(ws)

    def websocket_receive(self, ws, data):
        if ws == self.websocket:
            # termframe websocket connection, used for RPC
            try:
                msg = json.loads(data)
            except Exception, e:
                logger.error("JSON decode error in websocket message: %r" % (data,))
                return

            return self.dispatch_msg(msg)
        else:
            # dispatch to self.iframes
            return self.iframes.websocket_receive(ws, data)

    def request(self, req):

        logger.info("%s %s", req.method, req.url)

        # todo: A GET of the main terminal page when state != None should result in a terminal reset
        if req.url.startswith(self.url):
            if self.state == 'ready' and req.url_path == '/term.html':
                # main terminal url loaded a second time - reset terminal
                self.websocket.close()
                self.state = 'reloading'
                return 'reload' # quit, TODO: reload
            else:
                self.respond_document(req)

        elif req.url.startswith(self.clojurescript_repl_url):
            # proxy to the clojurescript repl
            proxy_args = {
                'host':'localhost',
                'port':9000,
                'url': self.clojurescript_repl_url,
                'req':req,
            }
            if proxyconnection.probe(**proxy_args):
                self.clojurescript_proxy_connection = proxyconnection.ProxyTcpConnection(**proxy_args)
            else:
                # start clojurescript repl and try again
                print "starting clojurescript repl"
                subprocess.Popen('rlwrap lein trampoline cljsbuild repl-listen', cwd=os.path.join(os.path.dirname(__file__), '../cljs'), shell=True)
                for i in range(32):
                    if proxyconnection.probe(**proxy_args):
                        self.clojurescript_proxy_connection = proxyconnection.ProxyTcpConnection(**proxy_args)
                        print "\nconnected!"
                        break
                    time.sleep(1)

        else:
            # dispatch the request to an iframe and provide a channel
            # for communication with this terminal instance via
            # returning commands as dicts
            res = self.iframes.request(req)
            if isinstance(res, dict):
                self.dispatch_msg(res)
            elif res:
                return res
            else:
                logger.error("Could not handle request %r (%s %s)." % (req, req.method, req.url))

        return True

    def input(self, data):
        # input or resize events from the terminal process
        if isinstance(data, basestring):
            self.stream.feed(data)
            self.render()
            return True
        elif isinstance(data, tuple) and data[0] == 'resize':
            self.screen.resize(lines=data[1], columns=data[2])
            self.render()
        elif data is None:
            return False # quit
        else:
            assert False

    def iframe_resize(self, iframe_id, height):
        self.screen.iframe_resize(iframe_id, height)
        self.render()

    valid_msg_names = set(['keypress',
                           'resize',
                           'paste_selection',
                           'iframe_resize'])

    def dispatch_msg(self, msg):
        """Dispatch websocket messages."""
        name = msg.get('name')
        if name in self.valid_msg_names:
            msg.pop('name')
            getattr(self, name)(**msg)
        else:
            logger.error("Unknown name: %r in message %r" % (name, msg))
