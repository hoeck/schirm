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

    def __init__(self, output_queue): # queue to put received requests on
        self.socket = socket.socket()
        # the terminal process will receive the request data and a
        # connection-id and its response must contain the
        # connection-id to determine which connection to use for
        # sending the response
        self.requests = {}
        self._requests_lock = threading.RLock() # aquire before touching self.requests
        self._id = 0 # last request id

        self.listen_thread = None
        self.output_queue = output_queue
        self.start()

    def _getnextid(self):
        self._id += 1
        return self._id

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        # listen to connections and write things to the terminal process
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.setDaemon(True)
        self.listen_thread.start()
        # close the connections for requests the terminal process has
        # not responded in REQUEST_TIMEOUT time
        self.prune_old_request_thread = threading.Thread(target=self.prune_old_requests)
        self.prune_old_request_thread.setDaemon(True)
        self.prune_old_request_thread.start()
        return self

    def getport(self):
        addr, port = self.socket.getsockname()
        return port

    def listen(self):
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

        with self._requests_lock:
            req_id = self._getnextid()
            self.requests[req_id] = {'client': client, 'time': time.time()}

        if req.headers.get("Content-Length"):
            data = req.rfile.read(long(req.headers.get("Content-Length")))
        else:
            data = None

        req_message = {'type'   : 'request',
                       'value'  : {'id'              : req_id,
                                   'request_version' : req.request_version,
                                   'method'          : req.command,
                                   'path'            : req.path,
                                   'headers'         : dict(req.headers),
                                   'data'            : data,
                                   'error_code'      : req.error_code,
                                   'error_message'   : req.error_message}}

        self.output_queue.put(req_message)

    def make_status404(self):
        data = "not found"
        return '\r\n'.join(["HTTP/1.1 404 Not Found",
                            "Content-Type: text/plain",
                            "Content-Length: " + str(len(data)),
                            "Connection: close",
                            "",
                            data])

    def respond(self, req_id, data=None):
        # todo: data=None -> 404
        logging.debug("server responding to {} with {}...".format(req_id, data[:60]))
        with self._requests_lock:
            req = self.requests.pop(int(req_id), None) # atomic
        if req:
            client = req['client']
            client.sendall(data if data != None else self.make_status404())
            self._close_conn(client)
