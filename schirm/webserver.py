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
import threading
import base64
import time
import logging
import urlparse
import pkg_resources
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO

from hashlib import sha1
from ws4py import WS_KEY, WS_VERSION
from ws4py.exc import HandshakeError, StreamClosed
from ws4py.streaming import Stream
from ws4py.websocket import WebSocket

logger = logging.getLogger(__name__)

class attrdict(dict):
    def __getattr__(self, k):
        return self[k]

class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, stream): #request_text
        self.rfile = stream #StringIO(request_text)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message

class AsyncWebSocket(WebSocket):
    """Websocket with a configurable receive callback function."""

    def __init__(self, *args, **kwargs):

        self.onreceive = kwargs.pop('onreceive', lambda _: None)
        super(AsyncWebSocket, self).__init__(*args, **kwargs)

        self.recv_thread = None

    def received_message(self, message):
        self.onreceive(message)

    def run_in_bg(self):
        # thread for reading from the websocket
        self.recv_thread = threading.Thread(target=self.run)
        self.recv_thread.setDaemon(True)
        self.recv_thread.start()

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

    def __init__(self, schirm): # queue to put received requests on
        self.socket = socket.socket()
        # the terminal process will receive the request data and a
        # connection-id and its response must contain the
        # connection-id to determine which connection to use for
        # sending the response
        self.requests = {}
        self._requests_lock = threading.RLock() # aquire before touching self.requests
        self._id = 0 # last request id

        self.listen_thread = None
        self.schirm = schirm
        self.start()

        self.websocket_protocols = [] # ???
        self.websocket_extensions = [] # ???

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
        logger.debug("Schirm HTTP proxy server listening on localhost:%s" % (self.getport(),))
        # todo: create a threaded server and fix logging!
        while 1:
            client, address = self.socket.accept()
            self.receive(client)

    def prune_old_requests(self):
        # simple request gc
        while True:
            with self._requests_lock:
                current_time = time.time()
                for rid in self.requests.keys():
                    req = self.requests.get(rid)
                    if req['type'] == 'websocket':
                        # TODO: ignore connected websockets
                        pass
                    else:
                        t = req['time']
                        if t and current_time - t > self.REQUEST_TIMEOUT:
                            req = self.requests.pop(rid, None)
                            req['client'].sendall(self.make_status404())
                            self._close_conn(req['client'])
                            logger.info("request %(rid)s timed out" % {'rid':rid})
            time.sleep(3)

    @staticmethod
    def _close_conn(client):
        client._sock.close()

    # websockets

    def respond_websocket_upgrade(self, req_id):
        # websocket upgrade response
        # must be called as a response to a 'type':'websocket' request
        # to establish a websocket connection
        req = self.requests[req_id]
        data = "\r\n".join([
                "HTTP/1.1 101 WebSocket Handshake",
                "Upgrade: websocket",
                "Connection: Upgrade",
                "Sec-WebSocket-Version: %s" % req['ws_version'],
                "Sec-WebSocket-Accept: %s" % base64.b64encode(sha1(req['ws_key'] + WS_KEY).digest()),
                "",
                ""])
        req['client'].sendall(data)

        def recv(msg):
            req_message = attrdict({'id'              : req_id,
                                    'type'            : 'websocket',
                                    'data'            : str(msg)})
            self.schirm.request(req_message)

        websocket = AsyncWebSocket(sock=req['client'],
                                   protocols=req['ws_protocols'],
                                   extensions=req['ws_extensions'],
                                   environ=None,
                                   onreceive=recv)

        websocket.run_in_bg() # starts a thread, blocks a lot

        with self._requests_lock:
            self.requests[int(req_id)].update({'websocket':websocket})

    def make_status400(self, msg):
        return '\r\n'.join(["HTTP/1.1 400 Bad Handshake",
                            "Content-Length: " + str(len(msg)),
                            "",
                            msg])

    def _receive_websocket(self, req_id, req):

        # example websocket request
        # GET /chat HTTP/1.1
        # Host: server.example.com
        # Upgrade: websocket
        # Connection: Upgrade
        # Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
        # Origin: http://example.com
        # Sec-WebSocket-Protocol: chat, superchat
        # Sec-WebSocket-Version: 13

        ws_key = req.headers.get('Sec-WebSocket-Key','')
        if len(base64.b64decode(ws_key)) != 16:
            self.respond(req_id, self.make_status400('Invalid Websocket key length'))
            return None

        ws_version = int(req.headers.get('Sec-WebSocket-Version'))
        if ws_version not in WS_VERSION:
            self.respond(req_id, self.make_status400('Unsupported Websocket version'))
            return None

        # collect supported protocols and extensions
        subprotocols = req.headers.get('Sec-WebSocket-Protocol', '')
        ws_protocols = [p.strip()
                        for p
                        in subprotocols.split(',')
                        if p.strip() in self.websocket_protocols]

        extensions = req.headers.get('Sec-WebSocket-Extensions', '')
        ws_extensions = [e.strip()
                         for e
                         in extensions
                         if e.strip() in self.websocket_extensions]

        # self.respond(req_id, resp_data, close=False)

        with self._requests_lock:
            self.requests[req_id].update({'type': 'websocket',
                                          'ws_key': ws_key,
                                          'ws_version': ws_version,
                                          'ws_protocols': ws_protocols,
                                          'ws_extensions': ws_extensions})

        req_message = attrdict({'id'              : req_id,
                                'type'            : 'websocket',
                                'path'            : req.path,
                                'headers'         : dict(req.headers),
                                'upgrade'         : True,
                                'data'            : ''})

        return req_message

    def _proxy_connect(self, req_id, req):
        # proxy connection established
        if req.path == 'termframe.localhost:80': # TODO: proper path parsing!
            # TODO: locking
            client = self.requests[req_id]['client']
            client.sendall("HTTP/1.1 200 Connection established\r\n\r\n")
            # start reading the incoming data
            self.requests.pop(req_id)
            self.receive(client)

    def receive(self, client):
        """
        Receive a request and ignore, serve static files or ask the
        pty to provide a response.
        """
        rfile = client.makefile()
        req = HTTPRequest(rfile)

        if not req.requestline:
            # ignore 'empty' google chrome requests
            # TODO: debug
            return

        with self._requests_lock:
            req_id = self._getnextid()
            self.requests[req_id] = {'type':'http',
                                     'client': client,
                                     'time': time.time()}

        if req.headers.get("Content-Length"):
            data = req.rfile.read(long(req.headers.get("Content-Length")))
        else:
            data = None

        logger.info("%s - %s", req.command, req.path)
        
        if req.command == 'CONNECT':
            # proxy connection (for websockets or https)
            self._proxy_connect(req_id, req)

        elif req.headers.get('Upgrade') == 'websocket':
            # prepare for an upgrade to a websocket connection
            msg = self._receive_websocket(req_id, req)
            if msg:
                self.schirm.request(msg)

        else:
            # plain http
            req_message = attrdict({'id'              : req_id,
                                    'type'            : 'http',
                                    'request_version' : req.request_version,
                                    'method'          : req.command,
                                    'path'            : req.path,
                                    'headers'         : dict(req.headers),
                                    'data'            : data,
                                    'error_code'      : req.error_code,
                                    'error_message'   : req.error_message,
                                    # include the portnumber of this
                                    # webserver to allow creating a
                                    # direct websocket uri as
                                    # websocket requests are not
                                    # proxied in webkitgtk (1.8.1)
                                    'proxy_port'      : self.getport()})

            self.schirm.request(req_message)

    def make_status404(self):
        data = "not found"
        return '\r\n'.join(["HTTP/1.1 404 Not Found",
                            "Content-Type: text/plain",
                            "Content-Length: " + str(len(data)),
                            "Connection: close",
                            "",
                            data])

    def _respond_http(self, req_id, data, close):
        with self._requests_lock:
            req = self.requests.pop(int(req_id), None)

        logger.debug("responding to %s with %s%s" % (req_id, repr(data)[:60], '...' if len(repr(data)) > 60 else ''))
        client = req['client']
        client.sendall(data if data != None else self.make_status404())
        if close or data == None:
            self._close_conn(client)
        else:
            # keep the connection around
            with self._requests_lock:
                self.requests[req_id] = {'type': 'http',
                                         'client': client,
                                         'time': time.time()}

    def _respond_websocket(self, req_id, data, close):
        if data != None:
            with self._requests_lock:
                req = self.requests.get(int(req_id), None)

                if not req.get('opened'):
                    logger.debug("websocket %r: upgrade" % (req_id, ))
                    self.respond_websocket_upgrade(req_id)
                    req = self.requests.get(int(req_id), None)
                    req['opened'] = True

                if data == True:
                    # true indicates to only complete the handshake, without sending any data
                    pass
                else:
                    logger.debug("websocket %r: send %r" % (req_id, data[:50]))
                    req['websocket'].send(data)

                if close:
                    req['websocket'].close()
        else:
            with self._requests_lock:
                req = self.requests.get(int(req_id), None)
                logger.debug("responding to %s with 404" % req_id)
                client = req['client']
                client.sendall(self.make_status404())
                self._close_conn(client)

    def respond(self, req_id, data=None, close=True):
        req = self.requests.get(int(req_id))

        if req:
            if req['type'] == 'http':
                self._respond_http(req_id, data, close)
            else:
                self._respond_websocket(req_id, data, close)
        else:
            logger.error("unknown request id: %r" % (req_id, ))
