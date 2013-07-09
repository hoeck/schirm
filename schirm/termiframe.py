import re
import json
import urlparse
import logging
import base64
import pkg_resources
import email.parser
import email.Message

import htmlterm
import webserver
import utils

logger = logging.getLogger(__name__)

STR_START = "\x1bX"
STR_END = "\x1b\\"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

class Iframes(object):
    """
    State machine receiving a subset of the generated events from
    Terminal.advance, tracking http-related state for iframes.
    """

    def __init__(self, client, webserver):
        self.iframes = {}
        self.iframe_websockets = {} # map request ids to iframe objects
        self.terminal_io = client
        self.webserver = webserver

    def request(self, req):

        # http://<iframe-id>.localhost
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req['path'])

        # use the subdomain to sandbox iframes and separate requests
        m = re.match("(?P<iframe_id>.+)\.localhost", netloc)
        iframe_id = m.group('iframe_id') if m else None
        if iframe_id:
            # transform the iframe path from a proxy path to a normal one
            root = "http://%s.localhost" % iframe_id
            req['path'] = req['path'][len(root):]

        logger.debug('iframe %(iframe_id)r request %(id)r: %(method)s %(path)r ' %
                     {'iframe_id':iframe_id,
                      'id':req['id'],
                      'method':req['protocol'],
                      'path':req['path']})

        if req['protocol'] == 'http':
            # may return messages to the calling terminal
            if iframe_id in self.iframes and req['path']:
                # dispatch
                # may return messages to the calling terminal
                return self.iframes[iframe_id].request(req)
            else:
                self.webserver.notfound(req['id'])

        elif req['protocol'] == 'websocket' and 'upgrade' in req:

            upgraded = self.iframes[iframe_id].websocket_upgrade(req)
            if upgraded:
                self.iframe_websockets[req['id']] = self.iframes[iframe_id]
            return upgraded

        elif req['id'] in self.iframe_websockets:
            self.iframe_websockets[req['id']].websocket_request(req)
            return True

        else:
            assert False # dont know how to deal with req

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
            self.iframes[iframe_id] = Iframe(iframe_id, self.terminal_io, self.webserver)
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

    def __init__(self, iframe_id, terminal_io, webserver):
        self.id = iframe_id
        self.resources = {}
        self.state = 'open'
        self.root_document_req_id = None

        self.terminal_io = terminal_io
        self.webserver = webserver

        # communication url
        # use to send execute_iframe commands
        self.comm_path = '/schirm'
        self.websocket_uri = 'ws://%s.localhost/schirm' % self.id
        self.comm_uri = 'http://%s.localhost/schirm' % self.id
        self.websocket_req_id = None
        self.pre_open_queue = []

    def _command_send(self, command):

        def respond_w_cmd(cmd):
            self.webserver.respond(self.comm_req_id,
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
        logger.debug("iframe_resize %s" % height)
        # send some js to the terminal hosting this iframe
        return htmlterm.Events.iframe_resize(self.id, height)

    def iframe_write(self, data):
        if self.state in ('open', 'close'):
            self.resources.setdefault(None, []).append(data)
        elif self.state == 'document_requested':
            self.resources.setdefault(None, []).append(data)
            # write more data
            self.webserver.respond(self.root_document_req_id, data.encode('utf-8'), close=False)

    def iframe_close(self):
        if self.state == 'document_requested':
            self.webserver.respond(self.root_document_req_id, '', close=True)
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
            self.webserver.respond(self.websocket_req_id)
        return "term.screen.iframeLeave();"

    def _send_message(self, data):
        """Send data to the iframe using the iframes websocket connection."""
        if self.websocket_req_id:
            self.webserver.respond(self.websocket_req_id,
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

        self.resources[name] = {'body': data,
                                'content_type': mimetype or webserver.guess_type(name)}

    def _respond(self, header, body):
        # todo: test that req_id indeed belongs to a request
        # originating from this iframe

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

        self.webserver.respond(header.get('x-schirm-request-id'), http_status + m.as_string())

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
        # decode a string request, interpret it according to the current state
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
            self._respond(header, body)
        elif 'x-schirm-message' in header:
            self._send_message(header['x-schirm-message'] or body)
        elif 'x-schirm-debug' in header:
            self._debug(header['x-schirm-debug'] or body)
        else:
            self._unknown(data)

    # methods called by webserver to respond to http requests to the iframes subdomain ???
    def request(self, req):
        GET  = (req['method'] == 'GET')
        POST = (req['method'] == 'POST')

        # routing
        if GET and req['path'] == '/':
            # serve the root document regardless of the iframes state
            self.root_document_req_id = req['id']

            if self.state == 'open':
                self.state = 'document_requested'

            data = ''.join(self.resources.get(None, []))

            logger.debug("getting iframe root document: %s", repr((self.state, utils.shorten(data))))
            self.webserver.respond(req['id'],
                                   data="\r\n".join(["HTTP/1.1 200 OK",
                                                     "Cache-Control: no-cache",
                                                     "Content-Type: text/html; charset=utf-8",
                                                     "",
                                                     data.encode('utf-8')]),
                                   close=(self.state != 'document_requested'))
            return True

        elif GET and req['path'] == '/schirm.js':
            # TODO: find a central place to define (the websocket) URIs
            self.webserver.found_resource(req['id'],
                                          path='schirm.js',
                                          resource_module_name='schirm.resources',
                                          modify_fn=lambda s: (s % {'websocket_uri': self.websocket_uri,
                                                                    'comm_uri': self.comm_uri}))
        elif GET and req['path'] in self.static_resources:
            logger.debug('serving static resource %r to iframe %r', req['path'], self.id)
            self.webserver.respond_resource_file(req['id'], self.static_resources[req['path']])

        elif GET and req['path'] in self.resources:
            self.webserver.found(req['id'], **self.resources[req['path']])

        elif POST and req['path'] == self.comm_path:
            # receive commands from the iframe
            try:
                data = json.loads(req['data'])
            except ValueError:
                data = {}

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
                    self.webserver.done(req['id'])
                    return {'name': 'iframe_resize', 'id': self.id, 'height':height}
                elif cmd == 'control-c': # TODO: return a 'msg' and decode in terminal.handlers.request
                    self.webserver.keypress({'name': 'C', 'control': True})
                elif cmd == 'control-d':
                    self.webserver.keypress({'name': 'D', 'control': True})
                elif cmd == 'control-z':
                    self.webserver.keypress({'name': 'Z', 'control': True})
                else:
                    self.webserver.respond(req['id'])
            else:
                self.webserver.respond(req['id'])

        else:
            if self.state == 'close':
                # write the response wrapped as an ECMA-48 string back
                # to the terminal

                header = dict(req['headers'])
                header.update({'x-schirm-request-id': str(req['id']),
                               'x-schirm-request-path': req['path'],
                               'x-schirm-request-method': req['method']})

                term_req = ''.join([STR_START,
                                    json.dumps(header),
                                    NEWLINE, NEWLINE,
                                    req['data'] or "",
                                    STR_END,
                                    # trailing newline required for flushing
                                    NEWLINE])
                self.terminal_io.write(term_req)

            else:
                self.webserver.notfound(req['id'])

    def websocket_upgrade(self, req):
        if self.state != None and not self.websocket_req_id:
            self.webserver.respond(req['id']) # upgrade
            self.websocket_req_id = req['id']
            # send queued data
            for data in self.pre_open_queue:
                self.webserver.respond(req['id'], data)
            return True
        else:
            # close the websocket
            self.webserver.respond(req['id'], data=None, close=True)
            return False

    def websocket_request(self, req):
        if req['id'] == self.websocket_req_id:
            self.terminal_io.write(''.join((START_MSG,
                                            base64.b64encode(req['data']),
                                            END, NEWLINE)))
        else:
            self.webserver.notfound(req['id'])
