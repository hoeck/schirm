import re
import urlparse
import logging
import base64

import htmlterm

logger = logging.getLogger(__name__)

ESC = "\033"
SEP = ESC + ";"
START_REQ = ESC + "R" + "request" + SEP
END = ESC + "Q"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

class Iframes(object):
    """
    State machine receiving a subset of the generated events from
    Terminal.advance, tracking http-related state for iframes.
    """

    def __init__(self, terminal_io, terminal_ui):
        self.iframes = {}
        self.terminal_io = terminal_io
        self.terminal_ui = terminal_ui

    def request(self, req):

        # http://<iframe-id>.localhost
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)

        # use the subdomain to sandbox iframes and separate requests
        m = re.match("(.+)\.localhost", netloc)
        if m:
            try:
                iframe_id = m.group(1)
                # transform the iframe path from a proxy path to a normal one
                root = "http://%s.localhost" % iframe_id
                req['path'] = req['path'][len(root):]

            except:
                iframe_id = None
        else:
            iframe_id = None

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
        # create iframes and relay the iframe events to each iframe
        # object using the iframe_id

        name, iframe_id = event[:2]
        args = event[2:]

        if name == 'iframe_enter':
            logger.debug("iframe_enter %r", event)
            self.iframes[iframe_id] = Iframe(iframe_id, self.terminal_io, self.terminal_ui)
        else:
            f = self.iframes.get(iframe_id)
            if f:
                event_method = getattr(f, name)
                if event_method:
                    event_method(*args)
                else:
                    logger.error('Unknown iframe event method: %r', name)
            else:
                logger.warn('No iframe with id %r', iframe_id)

class Iframe(object):
    """Represents an iframe line created inside a schirm terminal emulation."""

    static_resources = {'/schirm.js': "schirm.js",   # schirm client lib
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
        self.comm_path = '__comm__'
        self.comm_req_id = None
        self.comm_commands_pending = [] # queue up commands, send one at a time

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
        # back to terminal mode:
        self.state = None

    def iframe_execute(self, script):
        """Execute some javascript in the iframe document.

        Requires the iframe to have loaded the terminal_ui.js lib.
        """
        self._command_send({'name':'execute',
                            'value': script})

    def iframe_register_resource(self, name, mimetype, data):
        """Add a static resource name to be served.

        Use the resources name to guess an appropriate Content-Type if
        no mimetype is provided.
        """
        if not name.startswith("/"):
            name = "/" + name
        self.resources[name] = self.terminal_ui.make_response(mimetype or self.terminal_ui.guess_type(name), data)

    def iframe_respond(self, req_id, data):
        # todo: test that req_id indeed belongs to a request
        # originating from ths iframe
        self.terminal_ui.respond(req_id, data)

    def iframe_debug(self, msg):
        print msg

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

        elif GET and req.path in self.static_resources:
            # todo: write this function, should serve the file
            # named in path from the internal terminal_ui.resources
            # directory
            logger.debug('serving static resource %r to iframe %r', req.path, self.id)
            self.terminal_ui.respond_resource_file(req.id, self.static_resources[req.path])

        elif GET and req.path in self.resources:
            data = self.resources[req.path]
            self.terminal_ui.respond(req.id, data) # data in resources is already in http-request form

        elif POST and req.path == self.comm_path and self.state == 'open':
            if req.data:
                self._command_respond(req.data)
            self.comm_req_id = req.id # there may only be one open request at a time

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
