
import os
import socket
import mimetypes
import threading
import base64
import time
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO


START = "\033R"
SEP = "\033;"
END = "\033Q"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, stream): #request_text
        self.rfile = stream #StringIO(request_text)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message

class Server(object):
    """
    1) A simple server which reads requests from the embedded webkit,
    enumerates them and writes them to the pty using a special ESC code:
    ESC R <id> ESC ; <base64-encoded-request-data> \033 Q
    the id is required to know which response belongs to which request.
    
    2) A function to handle responses from the pty and write them to the
    webkit socket.

    3) A function to register static resources that are automatically
    delivered.
    """

    def __init__(self, pty):
        self.pty = pty
        self.socket = socket.socket()
        self.requests = {}
        self._id = 0
        self.resources = {}
        self.listen_thread = None
        self.not_found = set(["/favicon.ico", "/"])

    def _getnextid(self):
        self._id += 1
        return self._id

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        print "Server started: localhost:{0}".format(self.getport())
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.start()
        return self

    def getport(self):
        addr, port = self.socket.getsockname()
        return port
    
    def listen(self):
        # todo: thread to close up unused connections
        while 1:
            client, address = self.socket.accept()
            self.receive(client)

    def clear_resources(self):
        self.resources = {}

    def receive(self, client):
        """
        Receive a request and ignore, serve static files or ask the
        pty to provide a response.
        """

        rfile = client.makefile()
        req = HTTPRequest(rfile)
       
        if req.error_code:
            client.sendall(req.error_message)
            client.close()

        elif req.command == 'GET' and req.path in self.resources:
            # its a known static resource, serve it!
            client.sendall(self.resources[req.path])
            client.close()

        elif req.command == 'GET' and req.path in self.not_found:
            # ignore some requests (favicon & /)
            client.sendall("HTTP/1.1 404 Not Found")
        
        elif not self.pty.screen.iframe_mode:
            # only serve dynamic requests if terminal is in iframe mode
            client.sendall("HTTP/1.1 404 Not Found")
            client.close()
        else:
            req_id = self._getnextid()
            self.requests[req_id] = client
            
            # transmitting: req_id, method, path, (k, v)*, data
            data = [str(req_id),
                    req.request_version,
                    req.command,
                    req.path]

            for k in req.headers.keys():
                data.append(k)
                data.append(req.headers[k])

            if req.headers.get("Content-Length"):
                #print "reading data:", req.headers.get("Content-Length")
                data.append(req.rfile.read(long(req.headers.get("Content-Length"))))
            else:
                data.append("")
            # print "request is:"
            # for x in data:
            #     print "  ", x

            pty_request = START + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE

            # Do only send requests when the terminals iframe document
            # is 'closed' so that requests are not echoed into the
            # document or into the terminal screen.
            # Wait for a close if its currently 'open'
            timeout = 120
            wait = 0.1
            while self.pty.screen.iframe_mode == 'open' \
                    and timeout > 0:
                timeout -= wait
                time.sleep(wait)

            #print "request is:", repr(pty_request)
            if self.pty.screen.iframe_mode == 'closed':
                self.pty.q_write_iframe(pty_request)

    def respond(self, req_id, data):
        #print "respond:", req_id, data
        rid = int(req_id)
        if rid in self.requests:
            client = self.requests[rid]
            client.sendall(data)
            client.close()

    def register_resource(self, name, data):
        """
        Add a static resource name to be served. Use the resources
        name to guess an appropriate content-type.
        """
        guessed_type, encoding = mimetypes.guess_type(name, strict=False)
        response = "\n".join(("HTTP/1.1 200 OK",
                              "Content-Type: " + guessed_type,
                              "Content-Length: " + str(len(data)),
                              "",
                              data))

        if not name.startswith("/"):
            name = "/" + name
        self.resources[name] = response
