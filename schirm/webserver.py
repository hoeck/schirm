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
import pkg_resources
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

    # close the connections for requests which have been dispatched to the terminal
    # and received no response after this amount of seconds
    REQUEST_TIMEOUT = 30

    def __init__(self, pty, user_css='user.css'):
        self.pty = pty
        self.socket = socket.socket()
        # the terminal process will receive the request data and a
        # connection-id and its response must contain the
        # connection-id to determine which connection to use for
        # sending the response
        self.requests = {}
        self._requests_lock = threading.RLock() # aquire before touching self.requests
        self._id = 0 # last request id
        self.resources = {}

        # default static resources:
        # - relative paths are looked up in schirm.resources module
        #   using pkg_resources.
        # - absolute paths are loaded from the filesystem
        self.schirm_resources = {'/schirm.js': "schirm.js",   # schirm client lib
                                 '/schirm.css': "schirm.css", # schirm iframe mode styles
                                 # terminal emulator files
                                 '/term.html': 'term.html',
                                 '/term.js': 'term.js',
                                 '/term.css': 'term.css',
                                 '/user.css': user_css,
                                 }

        self.listen_thread = None
        self.not_found = set(["/favicon.ico", "/"])

    def _getnextid(self):
        self._id += 1
        return self._id

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        # listen to connections and write things to the terminal process
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.start()
        # close the connections for requests the terminal process has
        # not responded in REQUEST_TIMEOUT time
        self.prune_old_request_thread = threading.Thread(target=self.prune_old_requests)
        self.prune_old_request_thread.start()
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

    def prune_old_requests(self):
        while True:
            with self._requests_lock:
                current_time = time.time()
                for rid in self.requests.keys():
                    req = self.requests.get(rid)
                    t = req['time']
                    if t and current_time - t > self.REQUEST_TIMEOUT:
                        req = self.requests.pop(rid, None)
                        req['client'].sendall(self.make_status404())
                        self._close_conn(req['client'])
                        logging.info("request {rid} timed out".format(rid=rid))
            time.sleep(1)

    def clear_resources(self):
        #self.resources = {}
        pass

    @staticmethod
    def _close_conn(client):
        client._sock.close()

    def receive(self, client):
        """
        Receive a request and ignore, serve static files or ask the
        pty to provide a response.
        """
        rfile = client.makefile()
        req = HTTPRequest(rfile)

        logging.info("request: {command} {path}".format(command=getattr(req, 'command', None),
                                                        path=getattr(req, 'path', None)))
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)
        m = re.match("(.+)\.localhost", netloc)
        if m:
            iframe_id = m.group(1)
        else:
            iframe_id = None

        if req.error_code:
            logging.debug(req.error_message)
            client.sendall(req.error_message)
            self._close_conn(client)

        elif req.command == 'GET' \
                and iframe_id \
                and iframe_id in self.resources \
                and path in self.resources[iframe_id]:
            # its a known static resource, serve it!
            logging.debug("serving static resource {} for iframe {}".format(path, iframe_id))
            client.sendall(self.resources[iframe_id][path])
            self._close_conn(client)

        elif req.command == 'GET' \
                and path in self.schirm_resources:
            # builtin static resource, serve it!
            res = self.schirm_resources[path]
            if os.path.isabs(res):
                # external resource (e.g. user.css file in ~/.schirm/)
                f = None
                try:
                    with open(res, 'r') as f:
                        data = f.read()
                    logging.debug("serving builtin static resource {} from external path {}.".format(path, res))
                    client.sendall(self.make_response(self.guess_type(path), data))
                except:
                    logging.error("failed to load static resource {} from path {}.".format(path, res))
                    client.sendall(self.make_status404())
            else:
                # internal resource
                logging.debug("serving builtin static resource {}.".format(path))
                data = pkg_resources.resource_string('schirm.resources', res)
                client.sendall(self.make_response(self.guess_type(path), data))

            self._close_conn(client)

        elif iframe_id and req.command == 'GET' and path in self.not_found:
            logging.debug("Ignoring request ({})".format(path))
            # ignore some requests (e.g. favicon)
            client.sendall(self.make_status404())
            self._close_conn(client)

        elif self.pty.screen.iframe_mode == 'closed':
            # Write requests into stdin of the current terminal process.
            # Only if all document data has already been sent to the iframe.
            # So that requests are not echoed into the document or
            # into the terminal screen.

            with self._requests_lock:
                req_id = self._getnextid()
                self.requests[req_id] = {'client': client, 'time': time.time()}

            def clear_path(path):
                # transform the iframe path from a proxy path to a normal one
                root = "http://{}.localhost".format(iframe_id)
                if root in path:
                    return path[len(root):]
                else:
                    return path

            # transmitting: req_id, method, path, (k, v)*, data
            data = [str(req_id),
                    req.request_version,
                    req.command,
                    clear_path(req.path)]

            for k in req.headers.keys():
                data.append(k)
                data.append(req.headers[k])

            if req.headers.get("Content-Length"):
                data.append(req.rfile.read(long(req.headers.get("Content-Length"))))
            else:
                data.append("")

            pty_request = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE
            if self.pty.screen.iframe_mode == 'closed':
                self.pty.q_write_iframe(pty_request)

        else:
            # only serve non-static requests if terminal is in iframe_mode == 'open'
            if self.pty.screen.iframe_mode == 'open':
                logging.debug("unknown resource: '{}' - responding with 404".format(path))
            else:
                logging.debug("Not in iframe mode - responding with 404")

            client.sendall(self.make_status404())
            self._close_conn(client)

    def respond(self, req_id, data):
        logging.debug("server responding to {} with {}...".format(req_id, data[:60]))
        with self._requests_lock:
            req = self.requests.pop(int(req_id), None) # atomic
        if req:
            client = req
            client.sendall(data)
            self._close_conn(client)

    def make_status404(self):
        data = "not found"
        return '\r\n'.join(["HTTP/1.1 404 Not Found",
                            "Content-Type: text/plain",
                            "Content-Length: " + str(len(data)),
                            "Connection: close",
                            "",
                            data])

    def make_response(self, mimetype, data):
        """Return a string making up an HTML response."""
        return "\n".join(["HTTP/1.1 200 OK",
                          "Cache-Control: " + "no-cache",
                          "Connection: close",
                          "Content-Type: " + mimetype,
                          "Content-Length: " + str(len(data)),
                          "",
                          data])

    def guess_type(self, name):
        """Given a path to a file, guess its mimetype."""
        guessed_type, encoding = mimetypes.guess_type(name, strict=False)
        return guessed_type or "text/plain"

    def register_resource(self, frame_id, name, mimetype, data):
        """
        Add a static resource name to be served. Use the resources
        name to guess an appropriate content-type if no mimetype is
        provided.
        """
        if not name.startswith("/"):
            name = "/" + name
        if frame_id not in self.resources:
            self.resources[frame_id] = {}

        # todo: cleanup old resources:
        # need timeout and old iframe to decide whether to delete
        self.resources[frame_id][name] = self.make_response(mimetype or self.guess_type(name), data)
