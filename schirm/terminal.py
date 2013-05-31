
import os
import Queue
import logging

import utils
import termkey
import termscreen
import termiframe
import htmlterm

logger = logging.getLogger(__name__)

def get_config_file_contents(filename):
    """Return the contents of ~/.schirm/<filename> or None."""
    config = os.path.join(os.path.expanduser('~/.schirm'), filename)
    if os.path.exists(config):
        with open(config) as f:
            return f.read()

class Terminal(object):

    def __init__(self,
                 # the client process
                 # must have non-blocking .write, .signal and .set_size methods
                 client,
                 # running webserver,
                 # must provide a non-blocking .response method
                 webserver,
                 # queue to put other outgoing messages onto
                 messages_out,
                 # terminal emulation options:
                 size=(80,25),
                 term_id='terminal0',
             ):
        self.client = client
        self.webserver = webserver
        self.messages_out = messages_out

        # set up the terminal emulation:
        self.screen = termscreen.TermScreen(*size)
        self.stream = termscreen.SchirmStream()
        self.stream.attach(self.screen)
        self.iframes = termiframe.Iframes(client, webserver)

        self.focus = False

        # request id of the terminal comm websocket
        self.websocket_id = None
        self.state = None # None -> 'ready' -> 'closed'

    class handlers(object):

        @staticmethod
        def keypress(term, msg):
            keycode = term.decode_keypress(msg['key'])
            term.client.write(keycode)

        @staticmethod
        def resize(term, msg):
            w = int(msg.get('width'))
            h = int(msg.get('height'))
            term.screen.resize(h, w)
            term.client.set_size(h, w)

        @staticmethod
        def iframeresize(term, msg):
            height = int(msg['height'])
            logger.debug("Iframe resize request to %s", height)
            term.screen.linecontainer.iframe_resize(msg.get('id') or
                                                    term.screen.iframe_id, height)

        @staticmethod
        def remove_history(term, msg):
            n = int(msg['n'])
            term.screen.linecontainer.remove_history(n)

        @staticmethod
        def paste_xsel(term, msg):
            term.client.write(utils.get_xselection())

        @staticmethod
        def set_focus(term, msg):
            term.focus = bool(msg.get('focus'))

        @staticmethod
        def request(term, msg):
            # todo: A GET of the main terminal page when state != None should result in a terminal reset
            term_root = 'http://termframe.localhost'
            rid      = msg.get('id')
            protocol = msg.get('protocol')
            path     = msg.get('path', '')

            if path.startswith(term_root):
                if protocol == 'http':
                    if self.state == 'ready' and path == (term_root + '/term.html'):
                        # main terminal url loaded a second time - reset terminal ??
                        messages_out.put({'name':'reload', 'request_id': rid})
                    else:
                        term.respond_document(rid, path[len(term_root):])

                elif protocol == 'websocket':
                    if msg.get('upgrade'):
                        # open exactly one websocket request for webkit <-> schirm communication
                        if not term.websocket_id:
                            term.websocket_id = rid
                            term.webserver.respond(rid) # empty response to upgrade
                            # communication set up, render the emulator state
                            term.state == 'ready'
                            term.handlers.render(term)
                        else:
                            term.webserver.notfound(rid)
                else:
                    assert False

            elif rid == term.websocket_id:
                # termframe websocket connection, used for RPC
                term.handle(json.loads(msg.data))

            else:
                # dispatch the request to an iframe
                handled = term.iframes.request(msg)
                if not handled:
                    logger.error("Could not handle request.")

        @staticmethod
        def client_output(term, msg):
            # terminal client got some data
            term.stream.feed(msg['data'])
            term.handlers.render(term)

        @staticmethod
        def client_close(term, msg): # pty_read_error
            # terminal client process closed its out stream
            # cleanup and quit terminal
            term.stream.close()
            term.client.kill()
            term.state = 'closed'
            # TODO:
            messages_out.put({'name': 'close'})

        @staticmethod
        def hide_cursor(term, msg):
            # turn off the cursor
            term.screen.linecontainer.hide_cursor(term.screen.cursor.y)

        @staticmethod
        def show_cursor(term, msg):
            if not term.screen.cursor.hidden and not term.screen.iframe_mode:
                # make sure the terminal cursor is drawn
                term.screen.linecontainer.show_cursor(
                    term.screen.cursor.y,
                    term.screen.cursor.x,
                    'cursor' if term.focus else 'cursor-inactive')

        @staticmethod
        def render(term, msg=None):

            if term.state != 'ready':
                logger.debug('not rendering - terminal state != ready')
                return

            # capture render events
            events = term.screen.linecontainer.get_and_clear_events()
            if not events:
                return

            # group javascript in chunks for performance
            js = [[]]
            def js_flush():
                if js[0]:
                    self.terminal_ui.execute(js[0])
                js[0] = []

            def js_append(x):
                if x:
                    js[0].append(x)

            # issue the screen0 as the last event
            screen0 = None

            for e in events:

                name = e[0]
                args = e[1:]

                if name.startswith('iframe_'):
                    # iframes:
                    js_flush()
                    js_append(self.iframes.dispatch(e))
                elif name == 'set_title':
                    js_flush()
                    self.terminal_ui.set_title(args[0])
                elif name == 'set_screen0':
                    screen0 = args[0]
                elif name == 'close_stream':
                    raise Exception('terminal exit')
                elif self.inspect_iframes and name == 'set_iframe':
                    # insert an iframe using the same domain as the main term frame
                    js_append(htmlterm.Events.set_iframe(*args, same_origin=True))
                elif name in htmlterm.Events.__dict__:
                    # sth. to be translated to js
                    js_append(getattr(htmlterm.Events,name)(*args))
                else:
                    logger.error('unknown event: %r', name)

            if screen0 is not None:
                js_append(htmlterm.Events.set_screen0(screen0))

            js_flush()

        @staticmethod
        def unknown(term, msg):
            logger.error('no handler for msg: %r' % (msg, ))

    def handle(self, msg):
        getattr(self.handlers, msg.get('name'), self.handlers.unknown)(self, msg['msg'])

    # helpers

    def send_js(self, js):
        if isinstance(src, basestring):
            js = [src]
        else:
            js = src

        data = ''.join(js)
        self.webserver.respond(self.websocket_id, data)

    static_resources = {
        '/term.html': 'term.html',
        '/term.js': 'term.js',
        '/term.css': 'term.css',
        '/default-user.css': 'user.css',
        '/favicon.ico': 'schirm.png',
    }

    def respond_document(self, rid, path):
        """Respond to requests to the main terminal root url."""
        if path in self.static_resources:
            self.webserver.found_resource(rid, self.static_resources[path])
        elif path == '/user.css':
            self.webserver.found(rid, get_config_file_contents('user.css') or "", 'text/css')
        elif path.startswith('/localfont/') and path.endswith('.ttf') or path.endswith('.otf'):
            # serve font files to allow using any local font in user.css via @font-face
            self.webserver.found_file(rid, path[len('/localfont'):])
        elif self.inspect_iframes and path.startswith('/iframe/'):
            # Ask for iframes content using the same domain
            # as the main terminal frame to be able to debug
            # iframe contents with the webkit-inspector.

            # modify the path into a iframe path
            #TODO
            #frag = path[len('/iframe/'):]
            #iframe_id = frag[:frag.index('/')]
            #iframe_path = frag[frag.index('/'):]
            #req['path'] = ('http://%(iframe_id)s.localhost%(iframe_path)s'
            #               % {'iframe_id':iframe_id,
            #                  'iframe_path':iframe_path})
            #self.input_queue.put(('request', req))
            pass
        else:
            self.webserver.notfound(rid)

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
