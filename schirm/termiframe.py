import re
import urlparse

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
            except:
                iframe_id = None
        else:
            iframe_id = None
        
        if iframe_id in self.iframes:
            # dispatch
            iframes[iframe_id].request(req, path)
        else:
            # 404
            self.terminal_ui.respond(req.id, close=True)

    # dispatch events produced by the termscreen state machine
    def dispatch(self, event):
        # create iframes and relay the iframe events to each iframe
        # object using the iframe_id

        name, iframe_id = event[0:1]
        args = event[2:]

        if name == 'iframe_enter':
            self.iframes[iframe_id] = Iframe(iframe_id, self.terminal_io, self.terminal_ui)
        elif name == 'iframe_resize':
            # todo:
            # send some js to the main terminal
            pass
        else:
            f = self.iframes.get(iframe_id)
            if f:
                getattr(f, name, *args)
            else:
                warn('no iframe with id %r' % iframe_id)

class Iframe(object):
    """Represents an iframe line created inside a schirm terminal emulation."""

    def __init__(self, iframe_id, terminal_io, terminal_ui):
        self.id = iframe_id
        self.resources = {}
        self.state = 'open'
        self.req_id = None

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

    def iframe_write(self, data):
        if self.state in ('open', 'close'):
            self.resources.setdefault(None, []).append(data)
        elif self.state == 'document_requested':
            self.resources.setdefault(None, []).append(data)
            # write more data
            self.terminal_ui.respond(self.req_id, data, close=False)

    def iframe_close(self):
        if self.state == 'document_requested':
            self.terminal_ui.respond(self.req_id, '', close=True)
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
    def request(self, req, path):
        GET  = (req.method == GET)
        POST = (req.method == POST)

        # routing
        if GET and path == '/':
            # serve the root document regardless of the iframes state

            if self.state == 'open':
                self.state = 'document_requested'
                data = ''.join(self.resources.get(None, []))
            else:
                data = ''

            self.terminal_ui.respond(req.id,
                                data="\r\n".join(["HTTP/1.1 200 OK",
                                                  "Cache-Control: no-cache",
                                                  "Content-Type: text/html",
                                                  "",
                                                  data]),
                                close=(self.state == 'close'))
        elif GET and path in self.static_resources:
            # todo: write this function, should serve the file
            # named in path from the internal terminal_ui.resources
            # directory
            self.terminal_ui.respond_resource_file(req_id, path)

        elif GET and path in self.resources:
            data = self.resources[path]
            self.terminal_ui.respond(req_id, data) # data in resources is already in http-request form

        elif POST and path == self.comm_path and self.state == 'open':
            if req.data:
                self._command_respond(req.data)
            self.comm_req_id = req.id # there may only be one open request at a time

        else:
            if self.state == 'close':
                # write the response back to the terminal
                def clear_path(path):
                    # transform the iframe path from a proxy path to a normal one
                    root = "http://{}.localhost".format(iframe_id)
                    if root in path:
                        return path[len(root):]
                    else:
                        return path

                # transmitting: req_id, method, path, (k, v)*, data
                data = [str(req.id),
                        req.request_version,
                        req.method,
                        clear_path(req.path)]

                for k in req.headers.keys():
                    data.append(k)
                    data.append(req.headers[k])
                data.append(req.data or "")
                term_req = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE
                self.terminal_io.write(term_req)
            else:
                # return a 404
                self.terminal_ui.respond(req.id)
