import re
import json
import urlparse
import logging
import base64
import pkg_resources
import email.parser

import htmlterm

logger = logging.getLogger(__name__)

ESC = "\033"
SEP = ESC + ";"
START_REQ = ESC + "R" + "request" + SEP
START_MSG = ESC + "R" + "message" + SEP
END = ESC + "Q"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

class Iframes(object):
    """
    State machine receiving a subset of the generated events from
    Terminal.advance, tracking http-related state for iframes.
    """

    def __init__(self, terminal_io, terminal_ui):
        self.iframes = {}
        self.iframe_websockets = {} # map request ids to iframe objects
        self.terminal_io = terminal_io
        self.terminal_ui = terminal_ui

    def request(self, req):

        if req.type == 'http':
            self._request_http(req)
        elif req.type == 'websocket' and 'upgrade' in req:
            # upgrade requests

            # extract path (iframe_id) from the websocket req path
            # (hint: depends whether using an external browser or the non-websocket-proxy gtkwebview) - only the latter is implemented right now
            m = re.match("/(?P<iframe_id>.+)", req.path)
            iframe_id = m.groups('iframe_id')[0] if m else None

            logger.debug('iframe %(iframe_id)r websocket request %(id)r %(path)r ' %
                         {'iframe_id':iframe_id,
                          'id':req.id,
                          'path':req.path})

            if iframe_id in self.iframes and req.get('path'):
                # dispatch
                upgraded = self.iframes[iframe_id].websocket_upgrade(req)
                if upgraded:
                    self.iframe_websockets[req.id] = self.iframes[iframe_id]
            else:
                # 404
                self.terminal_ui.respond(req.id, close=True)

        elif req.id in self.iframe_websockets:
            self.iframe_websockets[req.id].websocket_request(req)

        else:
            assert False # dont know how to deal with req

    def _request_http(self, req):

        # http://<iframe-id>.localhost
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)

        # use the subdomain to sandbox iframes and separate requests
        m = re.match("(?P<iframe_id>.+)\.localhost", netloc)
        iframe_id = m.group('iframe_id') if m else None
        if iframe_id:
            # transform the iframe path from a proxy path to a normal one
            root = "http://%s.localhost" % iframe_id
            req['path'] = req['path'][len(root):]

        logger.debug('iframe %(iframe_id)r request %(id)r: %(method)s %(path)r ' %
                     {'iframe_id':iframe_id,
                      'id':req.id,
                      'method':req.method,
                      'path':req.path})

        if iframe_id in self.iframes and req.get('path'):
            # dispatch
            self.iframes[iframe_id].request(req)
        else:
            # 404
            self.terminal_ui.respond(req.id, close=True)

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
            self.iframes[iframe_id] = Iframe(iframe_id, self.terminal_io, self.terminal_ui)
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

    static_resources = {#'/schirm.js': "schirm.js",   # schirm client lib
                        '/schirm.css': "schirm.css", # schirm iframe mode styles
                       }

    def __init__(self, iframe_id, terminal_io, terminal_ui):
        self.id = iframe_id
        self.resources = {}
        self.state = 'open'
        self.root_document_req_id = None

        self.terminal_io = terminal_io
        self.terminal_ui = terminal_ui

        # communication url
        # use to send execute_iframe commands
        self.comm_path = '/schirm'
        self.websocket_req_id = None
        self.pre_open_queue = []

    def _command_send(self, command):

        def respond_w_cmd(cmd):
            self.terminal_ui.respond(self.comm_req_id,
                                     json.dumps(cmd),
                                     close=True)

        if self.comm_req_id:
            if self.comm_commands_pending:
                # work on existing commands first
                self.comm_commands_pending.append(command)
                respond_w_cmd(self.comm_commands_pending.pop(0))
            else:
                respond_w_cmd(command)
        else:
            self.comm_commands_pending.append(command)

    def _command_respond(self, response_data):
        # todo:
        # self.terminal_io.write("ESC codes"+response_data)
        pass

    # iframe terminal methods

    def iframe_resize(self, height):
        logger.debug("iframe_resize", height)
        # send some js to the terminal hosting this iframe
        self.terminal_ui.execute(htmlterm.Events.iframe_resize(self.id, height))

    def iframe_write(self, data):
        if self.state in ('open', 'close'):
            self.resources.setdefault(None, []).append(data)
        elif self.state == 'document_requested':
            self.resources.setdefault(None, []).append(data)
            # write more data
            self.terminal_ui.respond(self.root_document_req_id, data, close=False)

    def iframe_close(self):
        if self.state == 'document_requested':
            self.terminal_ui.respond(self.root_document_req_id, '', close=True)
        self.state = 'close'

    def iframe_leave(self):
        # back to terminal mode

        # ensure the iframes document is closed (TODO: this rule
        # should be implemented in the terminal emulator statemachine
        # instead)
        self.iframe_close()

        self.state = None
        if self.websocket_req_id:
            # close open websockets
            self.terminal_ui.respond(self.websocket_req_id)
        return "term.iframeLeave();"

    def iframe_send(self, data):
        """Send data to the iframe using the iframes websocket connection."""
        if self.websocket_req_id:
            self.terminal_ui.respond(self.websocket_req_id,
                                     data,
                                     close=False)
        else:
            self.pre_open_queue.append(data)

    def _register_resource(self, name, mimetype, data):
        """Add a static resource name to be served.

        Use the resources name to guess an appropriate Content-Type if
        no mimetype is provided.
        """
        if not name.strip().startswith("/"):
            name = "/" + name

        self.resources[name] = self.terminal_ui.make_response(mimetype or self.terminal_ui.guess_type(name), data)

    def _respond(self, header, body):
        # todo: test that req_id indeed belongs to a request
        # originating from this iframe

        m = Message()
        for k,v in header:
            m[k] = v
        m.set_payload(body)
        self.terminal_ui.respond(header.get('x-schirm-request-id'), m.as_string())

    def _debug(self, msg):
        # todo: this should go directly somewhere into the terminal
        # window like other schirm error messages
        print msg

    def _parse_string_request(self, data):
        # the request
        if data.lstrip().startswith("{"):
            # JSON + body string
            header_end_pos = data.find("\n\n")
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
        # decode a string request, interpret it according to the current state
        header, raw_body = self._parse_string_request(data)
        body = base64.b64decode(raw_body)

        # valid headers:
        # x-schirm-url .. url for static resources
        # x-schirm-request-id .. request id to identify the response
        # x-schirm-send .. send this string or the body via the schirm websocket
        # x-schirm-debug .. write this string or the body to the emulators process stdout
        if 'x-schirm-url' in header:
            self._register_resource(name=header['x-schirm-url'],
                                    mimetype=header.get('content-type'),
                                    data=body)
        elif 'x-schirm-request-id' in header:
            self._respond(header, body)
        elif 'x-schirm-send' in header:
            self._send(header['x-schirm-send'] or body)
        elif 'x-schirm-debug' in header:
            self._debug(header['x-schirm-debug'] or body)
        else:
            self._unknown(data)

    # methods called by terminal_ui to respond to http requests to the iframes subdomain ???
    def request(self, req):
        GET  = (req.method == 'GET')
        POST = (req.method == 'POST')

        # routing
        if GET and req.path == '/':
            # serve the root document regardless of the iframes state
            self.root_document_req_id = req.id

            if self.state == 'open':
                self.state = 'document_requested'

            data = ''.join(self.resources.get(None, []))

            logger.debug("getting iframe root document: %s", repr((self.state, data)))
            self.terminal_ui.respond(req.id,
                                     data="\r\n".join(["HTTP/1.1 200 OK",
                                                       "Cache-Control: no-cache",
                                                       "Content-Type: text/html",
                                                       "",
                                                       data]),
                                     close=(self.state != 'document_requested'))

        elif GET and req.path == '/schirm.js':
            # hack to get a websocket uri for embedded terminals as
            # proxying websocket connections does not work in the
            # current webkitgtk
            # TODO: find a central place to define the websocket URIs
            uri = "ws://localhost:%(port)s/%(id)s" % {'port': req.proxy_port,
                                                      'id': self.id} # TODO: urlencode!
            data = pkg_resources.resource_string('schirm.resources', 'schirm.js')
            self.terminal_ui.respond(req.id,
                                     self.terminal_ui.make_response('text/javascript',
                                                                    data % {'websocket_uri':uri}))
        elif GET and req.path in self.static_resources:
            logger.debug('serving static resource %r to iframe %r', req.path, self.id)
            self.terminal_ui.respond_resource_file(req.id, self.static_resources[req.path])

        elif GET and req.path in self.resources:
            data = self.resources[req.path]
            self.terminal_ui.respond(req.id, data) # data in resources is already in http-request form

        elif POST and req.path == self.comm_path:
            # receive commands from the iframe
            try:
                data = json.loads(req.data)
            except ValueError:
                data = {}

            if isinstance(data, dict):
                cmd = data.get('command')
                if cmd == 'resize':
                    # iframeresize
                    try:
                        height = int(data.get('height'))
                    except:
                        height = 25
                    self.iframe_resize(height)
                    self.terminal_ui.respond(req.id, 'HTTP/1.1 200 done\r\n\r\n')
                elif cmd == 'control-c':
                    self.terminal_ui.keypress({'name': 'C', 'control': True})
                elif cmd == 'control-d':
                    self.terminal_ui.keypress({'name': 'D', 'control': True})
                elif cmd == 'control-z':
                    self.terminal_ui.keypress({'name': 'Z', 'control': True})
                else:
                    self.terminal_ui.respond(req.id)
            else:
                self.terminal_ui.respond(req.id)

        else:
            if self.state == 'close':
                # write the response back to the terminal

                # transmitting: req_id, method, path, (k, v)*, data
                data = [str(req.id),
                        req.request_version,
                        req.method,
                        req.path]

                for k in req.headers.keys():
                    data.append(k)
                    data.append(req.headers[k])
                data.append(req.data or "")
                term_req = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE
                self.terminal_io.write(term_req)
            else:
                # return a 404
                self.terminal_ui.respond(req.id)

    def websocket_upgrade(self, req):
        if self.state != None and not self.websocket_req_id:
            self.terminal_ui.respond(req.id, True, close=False) # upgrade
            self.websocket_req_id = req.id
            # send queued data
            for data in self.pre_open_queue:
                self.terminal_ui.respond(req.id, data, close=False)
            return True
        else:
            self.terminal_ui.respond(req.id, close=True) # 404
            return False

    def websocket_request(self, req):
        if req.id == self.websocket_req_id:
            # todo: instead of terminal_io, use terminal_ui and the
            # input_queue to keep data written to the PTYs in stream
            # in sync !!!
            print "iframe websocket: %r" % req
            self.terminal_io.write(''.join((START_MSG,
                                            base64.b64encode(req.data),
                                            END, NEWLINE)))
        else:
            self.terminal_ui.respond(req.id, close=True) # 404
