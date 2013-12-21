import re
import json
import urlparse
import logging
import base64
import pkg_resources
import email.parser
import email.Message

import htmlterm
import utils

logger = logging.getLogger(__name__)

STR_START = "\x1bX"
STR_END = "\x1b\\"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

class Iframes(object):

    def __init__(self, client):
        self.iframes = {}
        self.iframe_websocket_chans = {} # map websocket chans to iframe objects
        self.client = client

    def request(self, req):

        # http://<iframe-id>.localhost
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.data['path'])

        # use the subdomain to sandbox iframes and separate requests
        m = re.match("(?P<iframe_id>.+)\.localhost", netloc)
        iframe_id = m.group('iframe_id') if m else None
        if iframe_id:
            # transform the iframe path from a proxy path to a normal one
            root = "http://%s.localhost" % iframe_id
            req.data['path'] = req['path'][len(root):]

        logger.debug('iframe %(iframe_id)r %(method)s %(path)r ' %
                     {'iframe_id':iframe_id,
                      'method':req.data['method'],
                      'path':req.data['path']})

        # dispatch
        if iframe_id in self.iframes and req.data['path']:
            # may return messages to the calling terminal
            res = self.iframes[iframe_id].request(req)
            if isinstance(res, chan.Chan):
                self.iframe_websockets[res] = self.iframes[iframe_id]
            return res
        else:
            if req.data['method'] == 'HEAD' and \
               re.match("http://[a-z]{10}/", req.data['path']):
                # looks like a chromium HEAD request trying to determine
                # whether the network is up -> ignore
                return True
            else:
                return False

        req.notfound()

    def websocket(self, ch, val):
        iframe = self.iframe_websockets.get(ch)
        if iframe:
            iframe.websocket(ch, val)
        else:
            ch.close()

    # dispatch events produced by the termscreen state machine
    def dispatch(self, event):
        # Create iframes and relay the iframe events to each iframe
        # object using the iframe_id.
        # Return a javascript snippet just like methods in htmlterm.Events or None.

        name, iframe_id = event[:2]
        args = event[2:]

        if name == 'iframe_enter':
            # create a new iframe, switch terminal into 'iframe_document_mode'
            logger.debug("iframe_enter %r", event)
            self.iframes[iframe_id] = Iframe(iframe_id, self.client)
        else:
            f = self.iframes.get(iframe_id)
            if f:
                event_method = getattr(f, name)
                if event_method:
                    return event_method(*args)
                else:
                    logger.error('Unknown iframe event method: %r', name)
            else:
                logger.warn('No iframe with id %r', iframe_id)

class Iframe(object):
    """Represents an iframe line created inside a schirm terminal emulation."""

    static_resources = {
        #'/schirm.js': "schirm.js",   # schirm client lib
        '/schirm.css': "schirm.css", # schirm iframe mode styles
    }

    def __init__(self, iframe_id, client):
        self.id = iframe_id
        self.resources = {}
        self.requests = {} # map of requests, waiting for responses from the client
        self.state = 'open'

        self.root_document_req = None
        self.send_chan = None # schirm -> iframe
        self.pending_commands = [] # enqueue commands made by the client before establishing the websocket connection with the iframe

        self.client = client

        # uri to send commands from the iframe to the emulator (via POST), e.g. resize
        self.comm_path = '/schirm'
        # websocket to communicate events
        self.websocket_uri = 'ws://%s.localhost/schirm' % self.id

    def _command_send(self, command):
        if self.send_chan:
            # connection established!

            # send pending comands first
            while self.pending_commands:
                c = self.comm_commands_pending.pop(0)
                self.send_chan.put(json.dumps(c))

            self.send_chan.put(json.dumps(command))
        else:
            self.pending_commands.append(command)

    def _command_respond(self, response_data):
        # todo:
        # self.client.write("ESC codes"+response_data)
        pass

    # iframe terminal methods

    def iframe_resize(self, height):
        logger.debug("iframe_resize %s" % height)
        # send some js to the terminal hosting this iframe
        return htmlterm.Events.iframe_resize(self.id, height)

    def iframe_write(self, data):
        if self.state in ('open', 'close'):
            self.resources.setdefault(None, []).append(data)
        elif self.state == 'document_requested':
            self.resources.setdefault(None, []).append(data)
            # write more data
            self.root_document_req.respond(data.encode('utf-8'), close=False)

    def iframe_close(self):
        if self.state == 'document_requested':
            self.root_document_req.respond('', close=True)
        self.state = 'close'

    def iframe_leave(self):
        # back to terminal mode

        # ensure the iframes document is closed (TODO: this rule
        # should be implemented in the terminal emulator statemachine
        # instead)
        self.iframe_close()

        self.state = None
        if self.send_chan:
            # close open websockets
            self.send_chan.close()
        return "term.screen.iframeLeave();"

    def _send_message(self, data):
        """Send data to the iframe using the iframes websocket connection."""
        if self.send_chan:
            self.send_chan.put(data)
        else:
            self.pre_open_queue.append(data)

    def _register_resource(self, name, mimetype, data):
        """Add a static resource name to be served.

        Use the resources name to guess an appropriate Content-Type if
        no mimetype is provided.
        """
        if not name.strip().startswith("/"):
            name = "/" + name

        self.resources[name] = {'body': data, 'content_type': mimetype}

    def _respond(self, header, body):
        req_id = header.get('x-schirm-request-id')
        req = self.requests.get(int(req_id))

        if not req:
            # error, how to respond?
            logger.error("Unknown request id: %r" % (header.get('x-schirm-request-id'), ))
            return

        m = email.Message.Message()

        # cgi-like: use the 'status' header to indicate which status
        # the webserver should respond with
        http_status = "HTTP/1.1 %s\n" % header.get('Status', header.get('status', '200'))

        for k,v in header.items():
            if k.lower() == 'status':
                pass
            elif k.lower().startswith('x-schirm'):
                # x-schirm headers are used to communicate with the
                # terminal
                pass
            else:
                m[k] = v
        m.set_payload(body)

        req.respond(http_status + m.as_string()) # close ????

    def _debug(self, msg):
        # todo: this should go directly somewhere into the terminal
        # window like other schirm error messages
        print msg

    def _unknown(self, data):
        logger.error("unknown iframe request: %r" % (data,))

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

            if header_end_pos > 0:
                try:
                    header = json.loads(data[:header_end_pos])
                except ValueError, e:
                    logger.debug("Error while parsing JSON header in iframe %s:\n%s" % (self.iframe_id, str(e)))
                    header = {}
            else:
                header = {}

            return header, data[header_end_pos+1:]

        else:
            # RFC 821 Message
            fp = email.parser.FeedParser()
            fp.parse(data)
            m = fp.close()
            return dict(m.items()), m.get_payload()

    def iframe_string(self, data):
        # decode a string coming from the client, interpret it according to the current state
        header, raw_body = self._parse_string_request(data)
        body = base64.b64decode(raw_body)

        # valid headers:
        # x-schirm-path .. path for static resources
        # x-schirm-request-id .. request id to identify the response
        # x-schirm-send .. send this string or the body via the schirm websocket
        # x-schirm-debug .. write this string or the body to the emulators process stdout
        if 'x-schirm-path' in header:
            self._register_resource(name=header['x-schirm-path'],
                                    mimetype=header.get('content-type', header.get('Content-Type')),
                                    data=body)
        elif 'x-schirm-request-id' in header:
            self._respond(int(header['x-schirm-request']), header, body)
        elif 'x-schirm-message' in header:
            self._send_message(header['x-schirm-message'] or body)
        elif 'x-schirm-debug' in header:
            self._debug(header['x-schirm-debug'] or body)
        else:
            self._unknown(data)

    # methods called by webserver to respond to http requests to the iframes subdomain ???
    def request(self, req):
        GET  = (req.data['method'] == 'GET')
        POST = (req.data['method'] == 'POST')
        path = req.data['path']

        # routing
        if GET and req['path'] == '/':
            # serve the root document regardless of the iframes state
            self.root_document_req = req

            if self.state == 'open':
                self.state = 'document_requested'

            data = ''.join(self.resources.get(None, []))

            logger.debug("getting iframe root document: %s", repr((self.state, utils.shorten(data))))
            req.respond(data="\r\n".join(["HTTP/1.1 200 OK",
                                          "Cache-Control: no-cache",
                                          "Content-Type: text/html; charset=utf-8",
                                          "",
                                          data.encode('utf-8')]),
                        close=(self.state != 'document_requested'))
            return True

        # static and iframe-specific resources
        elif GET and req['path'] in self.static_resources:
            req.found_resource(self.static_resources[req['path']])

        elif GET and req['path'] in self.resources:
            req.found(**self.resources[req['path']])

        # schirm websocket
        ### TODO: what is in req['path'] ????
        elif GET and req['protocol'] == 'websocket' and req.data['path'] == '/schirm':
            if self.state != None and not self.send_chan:
                req.websocket_upgrade() # upgrade
                self.send_chan = req['data']['chan']
                return req['data']['in_chan'] # select from this channel
            else:
                # already established a schirm websocket
                req.gone()

        elif GET and req['protocol'] == 'websocket':
            # other websockets
            req.notfound()

        elif POST and req['path'] == self.comm_path:
            # receive commands from the iframe via plain plain HTTP
            try:
                data = json.loads(req['data'])
            except ValueError:
                data = {}

            if isinstance(data, dict):
                cmd = data.get('command')
                req.done()

                if cmd == 'resize':
                    if data.get('height') == 'fullscreen':
                        height = 'fullscreen'
                    else:
                        # resize iframe to height
                        try:
                            height = int(data.get('height'))
                        except:
                            height = 'fullscreen'
                    return {'name': 'iframe_resize', 'id': self.id, 'height':height}
                elif cmd == 'control-c': # TODO: return a 'msg' and decode in terminal.handlers.request
                    #self.webserver.keypress({'name': 'C', 'control': True})
                    pass
                elif cmd == 'control-d':
                    #self.webserver.keypress({'name': 'D', 'control': True})
                    pass
                elif cmd == 'control-z':
                    #self.webserver.keypress({'name': 'Z', 'control': True})
                    pass
                else:
                    #self.webserver.respond(req['id'])
                    pass # ????
            else:
                req.notfound()

        else:
            if self.state == 'close':
                # write the response wrapped as an ECMA-48 string back
                # to the terminal and keep the req around, waiting for
                # a response from the terminal

                header = dict(req['headers'])
                header.update({'x-schirm-request-id': str(req.id),
                               'x-schirm-request-path': req.data['path'],
                               'x-schirm-request-method': req.data['method']})

                term_req = ''.join([STR_START,
                                    json.dumps(header),
                                    NEWLINE, NEWLINE,
                                    req['data'] or "",
                                    STR_END,
                                    # trailing newline required for flushing
                                    NEWLINE])
                self.client.write(term_req)
                self.requests[req.id] = req

            else:
                req.notfound()

    def websocket(self, ch, val):
        # ???????????????????????????????????????
        if ch == self.recv_chan:
            self.client.write(''.join((START_MSG,
                                       base64.b64encode(req['val']),
                                       END, NEWLINE)))
        else:
            assert False # ?????
