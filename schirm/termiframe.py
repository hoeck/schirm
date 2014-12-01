import re
import json
import urlparse
import logging
import base64
import email.parser
import email.Message
import traceback

import chan
import webkitwindow

import utils

logger = logging.getLogger(__name__)

STR_START = "\x1bX"
STR_END = "\x1b\\"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

def get_iframe_id(req_or_ws):
    # url: http://<iframe-id>.localhost
    m = re.match("(?P<iframe_id>.+)\.localhost", req_or_ws.url_netloc)
    return m.group('iframe_id') if m else None


class Iframes(object):

    def __init__(self, client):
        self.iframes = {}
        self.iframe_websocket_chans = {} # map websocket chans to iframe objects
        self.client = client

    def request(self, req):

        # use the subdomain to sandbox iframes and separate requests
        iframe = self.iframes.get(get_iframe_id(req))

        # dispatch
        if iframe:
            # may return messages to the calling terminal
            res = iframe.request(req)
            if isinstance(res, dict):
                # message for the terminal emulator
                return res
            elif res == None:
                # request has been handled
                return True
            elif res == False:
                # notfound
                return None
            else:
                assert False # invalid return value from Iframe.request
        else:
            req.notfound()

    def websocket_connect(self, ws):
        iframe = self.iframes.get(get_iframe_id(ws))
        if iframe:
            iframe.websocket_connect(ws)
        else:
            # unknown websocket
            ws.close()

    def websocket_receive(self, ws, data):
        iframe = self.iframe_websockets.get(ws)
        if iframe:
            iframe.websocket_receive(ws, data)
        else:
            # unknown websocket
            ws.close()

    # dispatch events produced by the termscreen state machine
    def dispatch(self, event):
        """Relay the iframe events from the emulator to each iframe object.

        Use the iframe_id o identify the iframe objects

        May return a list of tuples denoting one or more term screen
        client event or None
        """
        name, iframe_id = event[:2]
        args = event[2:]

        if name == 'iframe-enter':
            # create a new iframe, switch terminal into 'iframe_document_mode'
            logger.debug("iframe-enter %r", event)
            self.iframes[iframe_id] = Iframe(iframe_id, self.client)
            return [event]
        elif name == 'iframe-resize':
            return [event]
        else:
            f = self.iframes.get(iframe_id)
            if f:
                event_method = getattr(f, name.replace('-', '_'))
                if event_method:
                    try:
                        return event_method(*args)
                    except:
                        print "Error while calling iframe method %r, args: %r" % (event_method, args)
                        traceback.print_stack()
                        traceback.print_exc()

                else:
                    logger.error('Unknown iframe event method: %r', name)
            else:
                logger.warn('No iframe with id %r', iframe_id)
            return None


class Iframe(object):
    """Represents an iframe line created inside a schirm terminal emulation."""

    static_resources = {
        '/schirm.js': "schirm.js",   # schirm client lib
        '/schirm.css': "schirm.css", # schirm iframe mode styles
    }

    def __init__(self, iframe_id, client):
        self.id = iframe_id
        self.resources = {}
        self.requests = {} # map of requests, waiting for responses from the client
        self.state = 'open'

        self._root_document = None # a streaming response for the root document
        self._websocket = None # schirm -> iframe websocket
        self.pending_commands = [] # enqueue commands made by the client before establishing the websocket connection with the iframe

        self.client = client

        # uri to send commands from the iframe to the emulator (via POST), e.g. resize
        self.comm_path = '/schirm'
        # websocket to communicate events
        self.websocket_uri = 'ws://%s.localhost/schirm' % self.id

    def _command_send(self, command):
        if self._websocket:
            # connection established!

            # send pending comands first
            while self.pending_commands:
                c = self.comm_commands_pending.pop(0)
                self._websocket.send(json.dumps(c))

            self._websocket.put(json.dumps(command))
        else:
            self.pending_commands.append(command)

    def _command_respond(self, response_data):
        # todo:
        # self.client.write("ESC codes"+response_data)
        pass

    # iframe terminal methods

    def iframe_write(self, data):
        if self.state in ('open', 'close'):
            self.resources.setdefault(None, []).append(data)
        elif self.state == 'document_requested':
            self.resources.setdefault(None, []).append(data)
            # respond immediately
            self._root_document.write(data.encode('utf-8'))

    def iframe_close(self):
        if self.state == 'document_requested':
            self._root_document.close()
        self.state = 'close'

    def iframe_leave(self):
        # back to terminal mode

        # ensure the iframes document is closed (TODO: this rule
        # should be implemented in the terminal emulator statemachine
        # instead)
        self.iframe_close()

        self.state = None
        if self._websocket:
            # close open websockets
            self._websocket.close()
        # must the screen keep the iframe-mode state too???
        #return "term.screen.iframeLeave();"

    def _send_message(self, data):
        """Send data to the iframe using the iframes websocket connection."""
        if self._websocket:
            self._websocket.send(data)
        else:
            self.pre_open_queue.append(data)

    def _register_resource(self, name, mimetype, data):
        """Add a static resource name to be served.

        Use the resources name to guess an appropriate Content-Type if
        no mimetype is provided.
        """
        if not name.strip().startswith("/"):
            name = "/" + name

        if mimetype is None:
            mimetype = webkitwindow.guess_type(name)

        self.resources[name] = {'body': data, 'content_type': mimetype}

    def _respond(self, header, body):
        req_id = int(header.pop('x-schirm-request-id'))
        req = self.requests.get(req_id)

        if not req:
            # error, how to respond?
            logger.error("Unknown request id: %r" % (req_id, ))
            return

        # cgi-like: use the 'status' header to indicate which status
        # the we should respond with
        status = header.pop('Status', None) or header.pop('status', '200')

        req.respond(status, webkitwindow.Message(header, body))

    def _debug(self, msg):
        # todo: this should go directly somewhere into the terminal
        # window like other schirm error messages
        print msg

    def _set_frame_options(self, args):
        # set iframe options (e.g. resizing, url)
        assert isinstance(args, dict)

        screen_commands = []

        # change the frames URL
        if 'url' in args and self.state == 'close':
            url = urlparse.urlsplit(args['url'])
            iframe_url = urlparse.urlunsplit((
                'http://',
                '%s.localhost' % self.id,
                url.path,
                url.query,
                url.fragment
            ))
            screen_commands.append(('iframe-set-url', self.id, iframe_url))

        return screen_commands

    def _unknown(self, data):
        logger.error("unknown iframe request: %r" % (data,))

    def _lowercase_headers(self, header_pairs):
        """Lowercase all x-schirm-* keys of the header pairs (key, value)."""
        return dict((k.lower() if k.lower().startswith('x-schirm') else k, v)
                     for k,v
                     in header_pairs)

    def _parse_string_request(self, data):
        # the request
        if data.lstrip().startswith("{"):
            # JSON + body string
            header_end_pos = 0
            _p = data.find("\n\n")
            if _p > 0:
                header_end_pos = _p
            else:
                _p = data.find('\r\n\r\n')
                if _p > 0:
                    header_end_pos = _p
                else:
                    header_end_pos = len(data)

            if header_end_pos > 0:
                try:
                    header = json.loads(data[:header_end_pos])
                except ValueError, e:
                    logger.debug("Error while parsing JSON header in iframe %s:\n%s" % (self.iframe_id, str(e)))
                    header = {}
            else:
                header = {}

            return self._lowercase_headers(header.items()), data[header_end_pos+1:]

        else:
            # RFC 821 Message
            fp = email.parser.FeedParser()
            fp.parse(data)
            m = fp.close()
            return self._lowercase_headers(m.items()), m.get_payload()

    def iframe_string(self, data):
        # decode a string coming from the client, interpret it according to the current state
        header, raw_body = self._parse_string_request(data)
        body = base64.b64decode(raw_body)

        # valid headers:
        # x-schirm-path .. path for static resources
        # x-schirm-request-id .. request id to identify the response
        # x-schirm-send .. send this string or the body via the schirm websocket
        # x-schirm-debug .. write this string or the body to the emulators process stdout
        # x-schirm-frame-options .. set iframe options (resizing, url, )
        if 'x-schirm-path' in header:
            self._register_resource(name=header['x-schirm-path'],
                                    mimetype=header.get('content-type', header.get('Content-Type')),
                                    data=body)
        elif 'x-schirm-request-id' in header:
            self._respond(header, body)
        elif 'x-schirm-message' in header:
            self._send_message(header['x-schirm-message'] or body)
        elif 'x-schirm-debug' in header:
            self._debug(header['x-schirm-debug'] or body)
        elif 'x-schirm-frame-options' in header:
            # may return commands to the screen in the browser
            return self._set_frame_options(json.loads(body))
        else:
            self._unknown(data)

    # methods called by parent terminal to respond to http requests to the iframes subdomain ???
    def request(self, req):
        GET  = (req.method == 'GET')
        POST = (req.method == 'POST')

        # routing
        if GET and req.url_path == '/':
            # serve the root document regardless of the iframes state
            if self.state == 'open':
                self.state = 'document_requested'

            data = ''.join(self.resources.get(None, []))

            logger.debug("getting iframe root document: %s", repr((self.state, utils.shorten(data))))
            msg = webkitwindow.Message(headers={'Cache-Control': 'no-cache',
                                                'Content-Type': 'text/html; charset=utf-8'},
                                       body=data)
            req.respond(status=(200, 'OK'),
                        message=msg,
                        streaming=(self.state == 'document_requested'))

            self._root_document = msg # use _root_document.write/.close when streaming

        # static and iframe-specific resources
        elif GET and req.url_path in self.static_resources:
            req.found_resource(self.static_resources[req.url_path],
                               module_name='schirm.resources',
                               modify_fn=lambda s: s % {'websocket_uri': self.websocket_uri,
                                                        'comm_uri': self.comm_path})

        elif GET and req.url_path in self.resources:
            req.found(**self.resources[req.url_path])

        elif POST and req.url_path == self.comm_path:
            # receive commands from the iframe via plain plain HTTP
            req_bad = lambda msg="": req.respond((400, 'Bad Request'), webkitwindow.Message(body=msg))
            req_ok  = lambda: req.respond((200, 'OK'), webkitwindow.Message())

            try:
                data = json.loads(req.message.body)
            except ValueError, e:
                req_bad("Invalid JSON: %r" % str(e))
                return None

            if isinstance(data, dict):
                cmd = data.get('command')

                if cmd == 'resize':
                    if data.get('height') == 'fullscreen':
                        height = 'fullscreen'
                    else:
                        # resize iframe to height
                        try:
                            height = int(data.get('height'))
                        except:
                            height = 'fullscreen'
                    req_ok()
                    return {'name': 'iframe_resize', 'iframe_id': self.id, 'height':height}
                elif cmd == 'control-c': # TODO: return a 'msg' and decode in terminal.handlers.request
                    #terminal.keypress({'name': 'C', 'control': True})
                    req_ok()
                elif cmd == 'control-d':
                    #terminal.keypress({'name': 'D', 'control': True})
                    req_ok()
                elif cmd == 'control-z':
                    #terminal.keypress({'name': 'Z', 'control': True})
                    req_ok()
                else:
                    req_bad("Invalid command: %r" % (cmd, ))
            else:
                req_bad("Not a dictionary: %r" % (data, ))

        else:
            if self.state == 'close':
                # write the response wrapped as an ECMA-48 string back
                # to the terminal and keep the req around, waiting for
                # a response from the terminal

                header = dict(req.message.headers)
                header.update({'X-Schirm-Request-Id': str(req.id),
                               'X-Schirm-Request-Path': req.url_path,
                               'X-Schirm-Request-Method': req.method})

                term_req = ''.join([STR_START,
                                    json.dumps(header),
                                    NEWLINE, NEWLINE,
                                    req.message.body or "",
                                    STR_END,
                                    # trailing newline required for flushing
                                    NEWLINE])
                self.client.write(term_req)
                self.requests[req.id] = req

            else:
                req.notfound()
                return False

    def websocket_connect(self, ws):
        # schirm websocket
        if ws.url_path == '/schirm':
            if self.state != None and not self._websocket:
                ws.connected()
                self._websocket = ws
            else:
                # already established a schirm websocket
                ws.close()

        else:
            # other websockets: TODO implement
            ws.close()

    def websocket_receive(self, ws, data):
        TODO

    def websocket(self, ch, val):
        # ???????????????????????????????????????
        if ch == self.recv_chan:
            self.client.write(''.join((START_MSG,
                                       base64.b64encode(req.data['val']),
                                       END, NEWLINE)))
        else:
            assert False # ?????
