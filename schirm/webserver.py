# -*- coding: utf-8 -*-

# Schirm - a linux compatible terminal emulator providing html modes.
# Copyright (C) 2011  Erik Soehnel
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import re
import socket
import mimetypes
import threading
import base64
import time
import logging
import urlparse
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO


ESC = "\033"
SEP = ESC + ";"
START_REQ = ESC + "R" + "request" + SEP
END = ESC + "Q"
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
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.start()
        return self

    def getport(self):
        addr, port = self.socket.getsockname()
        return port

    def listen(self):
        # todo: thread to close unused connections
        logging.debug("Server listening on localhost:{}".format(self.getport()))
        while 1:
            client, address = self.socket.accept()
            self.receive(client)

    def clear_resources(self):
        #self.resources = {}
        pass

    def receive(self, client):
        """
        Receive a request and ignore, serve static files or ask the
        pty to provide a response.
        """
        rfile = client.makefile()
        req = HTTPRequest(rfile)
        logging.info("request: {r.command} {r.path}".format(r=req))
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)
        m = re.match("(.+)\.localhost", netloc)
        if m:
            iframe_id = m.group(1)
        else:
            iframe_id = None

        if req.error_code:
            client.sendall(req.error_message)
            client.close()

        elif req.command == 'GET' \
                and iframe_id \
                and iframe_id in self.resources \
                and path in self.resources[iframe_id]:
            # its a known static resource, serve it!
            logging.debug("serving static resource {} for iframe {}".format(path, iframe_id))
            client.sendall(self.resources[iframe_id][path])
            client.close()

        elif req.command == 'GET' and path in self.not_found:
            # ignore some requests (e.g. favicon)
            client.sendall("HTTP/1.1 404 Not Found")

        elif not self.pty.screen.iframe_mode:
            # only serve non-static requests if terminal is in iframe mode
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
                data.append(req.rfile.read(long(req.headers.get("Content-Length"))))
            else:
                data.append("")

            pty_request = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE

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

            if self.pty.screen.iframe_mode == 'closed':
                self.pty.q_write_iframe(pty_request)

    def respond(self, req_id, data):
        logging.debug("server responding to {} with {}...".format(req_id, data[:60]))
        rid = int(req_id)
        if rid in self.requests:
            client = self.requests[rid]
            client.sendall(data)
            client.close()

    def register_resource(self, frame_id, name, data):
        """
        Add a static resource name to be served. Use the resources
        name to guess an appropriate content-type.
        """
        guessed_type, encoding = mimetypes.guess_type(name, strict=False)
        if not guessed_type:
            guessed_type = "text/plain"
        response = "\n".join(("HTTP/1.1 200 OK",
                              "Content-Type: " + guessed_type,
                              "Content-Length: " + str(len(data)),
                              "",
                              data))

        if not name.startswith("/"):
            name = "/" + name
        if frame_id not in self.resources:
            self.resources[frame_id] = {}
        self.resources[frame_id][name] = response
