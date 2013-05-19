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

# TODO: check out: http://asyncoro.sourceforge.net/concurrent.html

import os
import re
import socket
import threading
import base64
import time
import logging
import urlparse
import pkg_resources
import Queue
import itertools
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO

from hashlib import sha1
from ws4py import WS_KEY, WS_VERSION
from ws4py.exc import HandshakeError, StreamClosed
from ws4py.streaming import Stream
from ws4py.websocket import WebSocket

# logging

logger = logging.getLogger(__name__)

# utils

def create_thread(target, name=None):
    t = threading.Thread(target, name=name)
    t.setDaemon(True)
    t.start()
    return t

class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, stream): #request_text
        self.rfile = stream #StringIO(request_text)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()

class AsyncWebSocket(WebSocket):
    """Websocket with a configurable receive callback function."""

    def __init__(self, *args, **kwargs):
        self.receive_cb = kwargs.pop('receive_cb', lambda *_: None)
        self.close-cb   = kwargs.pop('close_cb',   lambda *_: None)
        super(AsyncWebSocket, self).__init__(*args, **kwargs)

    def received_message(self, message):
        self.receive_cb(message)

    def closed(self, code, reason=None):
        self.close_cb()

class ThreadedRequest(object):
    """A Request waiting for responses in its own thread."""

    # close the connections for requests which have been dispatched to the terminal
    # and received no response after this amount of seconds
    TIMEOUT = 30

    _websocket_protocols = [] # ???
    _websocket_extensions = [] # ???

    def __init__(self, id, client, address, serverport, request_cb, close_cb):
        self.id = id                  # unique id to identify this request in the terminal client
        self._client = client         # client socket
        self._address = address       # client address
        self._serverport = serverport # port of the http server, to be able to parse proxy requests
        self._queue = Queue.Queue()   # external input, popped in the worker thread
        self._worker = None           # thread
        self._request_cb = request_cb # called with the request data when the r has been parsed
                                      # or when new websocket data is available
        self._close_cb = close_cb     # called when the request connection has been closed
        self._request = {}            # internal request data

    def handle(self):
        self._worker = create_thread(self._run, name='request_%s' % self.id)

    def _run(self):
        # read request
        req = self._receive()
        if not req:
            # fail
            self._close()
        else:
            # enqueue the request data
            self._request_cb(req)
            # wait for responses
            while True:
                try:
                    if self._queue.get(timeout=self.TIMEOUT)():
                        self._close()
                        return
                except Queue.Empty, e:
                    if not self._request.get('response_in_progress'):
                        self._respond(self._gateway_timeout(), close=True)
                        return

    def _close(self):
        try:
            sock = self._client._sock
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        except Exception, e:
            logger.error('Could not close connection of request %s (ex: %s)' % (self.id, e))
        self._close_cb()

    @staticmethod
    def _bad_handshake(msg):
        return '\r\n'.join(["HTTP/1.1 400 Bad Handshake",
                            "Content-Length: " + str(len(msg)),
                            "Connection: close",
                            "",
                            msg])

    @staticmethod
    def _gateway_timeout(msg):
        return '\r\n'.join(["HTTP/1.1 504 Gateway Timeout",
                            "Content-Length: " + str(len(msg)),
                            "Connection: close",
                            "",
                            msg])

    # decode incoming requests

    def _receive_websocket(self, req):
        """Read a websocket upgrade request.

        req must be a HTTPRequest.
        """

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
            self._respond(self._bad_handshake('Invalid Websocket key length'), close=True)
            return None

        ws_version = int(req.headers.get('Sec-WebSocket-Version'))
        if ws_version not in WS_VERSION:
            self._respond(self._bad_handshake('Unsupported Websocket version'), close=True)
            return None

        # collect supported protocols and extensions
        subprotocols = req.headers.get('Sec-WebSocket-Protocol', '')
        ws_protocols = [p.strip()
                        for p
                        in subprotocols.split(',')
                        if p.strip() in self._websocket_protocols]

        extensions = req.headers.get('Sec-WebSocket-Extensions', '')
        ws_extensions = [e.strip()
                         for e
                         in extensions
                         if e.strip() in self._websocket_extensions]

        self.request.update({'protocol': 'websocket',
                             'ws_key': ws_key,
                             'ws_version': ws_version,
                             'ws_protocols': ws_protocols,
                             'ws_extensions': ws_extensions})

        return {'id'              : self.id,
                'protocol'        : 'websocket',
                'path'            : req.path,
                'headers'         : dict(req.headers),
                'upgrade'         : True,
                'data'            : ''}

    def _receive_proxy_connect(self, req):
        # proxy connection established
        # TODO: proper path parsing!
        if (req.path in 'termframe.localhost:80' or
            req.path in 'localhost:%s' % self.serverport):
            self._client.sendall("HTTP/1.1 200 Connection established\r\n\r\n")
            return self._receive()
        else:
            logger.error('invalid connect path: %r' % req.path)
            return None

    def _receive(self):
        """Receive a request.

        Store all request related data into the request attribute.
        Return a dictionary describing the request or None if the
        request is invalid for whatever reasons.
        """

        rfile = self._client.makefile()
        req = HTTPRequest(rfile)

        if not req.requestline:
            # ignore 'empty' google chrome requests
            # TODO: debug
            return None

        if req.headers.get("Content-Length"):
            data = req.rfile.read(long(req.headers.get("Content-Length")))
        else:
            data = None

        logger.info("%s - %s", req.command, req.path)

        if req.command == 'CONNECT':
            # proxy connection (for websockets or https)
            return self._receive_proxy_connect(req_id, req)

        elif req.headers.get('Upgrade') == 'websocket':
            # prepare for an upgrade to a websocket connection
            return self._receive_websocket(req)

        else:
            # plain http
            return {'type'            : 'request',
                    'id'              : req_id,
                    'protocol'        : 'http',
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
                    'proxy_port'      : self._serverport}

    # responses

    def _websocket_upgrade(self):
        """Send a websocket upgrade response if necessary."""

        # websocket upgrade response
        # must be called as a response to a 'protocol':'websocket' request
        # to establish a websocket connection
        data = "\r\n".join([
                "HTTP/1.1 101 WebSocket Handshake",
                "Upgrade: websocket",
                "Connection: Upgrade",
                "Sec-WebSocket-Version: %s" % self._request['ws_version'],
                "Sec-WebSocket-Accept: %s" % base64.b64encode(sha1(self._request['ws_key'] + WS_KEY).digest()),
                "",
                ""])
        self._client.sendall(data)
        self._request['response_in_progress'] = True

        def _recv(msg):
            req_message = {'id'              : self.id,
                           'protocol'        : 'websocket',
                           'data'            : str(msg)}
            self._enqueue_request(req_message)

        def _close_cb():
            self.respond(None, close=True)

        websocket = AsyncWebSocket(sock=req['client'],
                                   protocols=req['ws_protocols'],
                                   extensions=req['ws_extensions'],
                                   environ=None,
                                   receive_cb=_recv,
                                   close_cb=_close_cb)

        self._request.update({'websocket': websocket})

        # read from the websocket in a separate thread
        create_thread(websocket.run)

    def _respond_websocket(self, data, close=False):
        """close or send data over the websocket.

        possible combinations of data and close and their reactions:
          (None, True)  - close (without updgrading)
          (None, False) - upgrade if required
          (str,  False) - upgrade if required, send str
          (str,  True)  - upgrade if required, send str, close
        """
        ws = self._request.get('websocket')

        if data is None:
            if close:
                if ws:
                    ws.close()
                return True

            else:
                if not ws:
                    self._websocket_upgrade()
        else:
            if not ws:
               ws = self._websocket_upgrade()

            ws.send(data)

            if close:
                ws.close()
                return True

    def _respond_http(self, data, close):
        """Append response data to an http connection.

        If close is True, close the connection. Otherwise leave it open.
        """
        if data:
            logger.debug("responding to %s with %s%s" % (self.id, repr(data)[:60], '...' if len(repr(data)) > 60 else ''))
            self._client.sendall(data)
            self._request['response_in_progress'] = True

        if close:
            logger.debug("closing %s", self.id)
            self._close()
            return True

    def _respond(self, data, close):
        # return true to close the request thread loop
        if self.request['protocol'] == 'http':
            return self._respond_http(data, close)
        else:
            return self._respond_websocket(data, close)

    def respond_async(self, data, close):
        """Enqueue a response"""
        self._queue.put(self.respond, data, close)

class Server(object):
    """
    Websocket enabled proxy-webserver.

    Receives incoming requests in a single thread, stores connection
    state and puts messages of type 'request' onto the receive_queue.
    Responses to these requests are made by calling one of the
    response methods using the provided request id.
    """

    # close the connections for requests which have been dispatched to the terminal
    # and received no response after this amount of seconds
    REQUEST_TIMEOUT = 30

    def __init__(self, request_cb):
        self.socket = socket.socket()
        # the terminal process will receive the request data and a
        # connection-id and its response must contain the
        # connection-id to determine which connection to use for
        # sending the response
        self.requests = {}
        self.request_cb = request_cb
        self._request_ids = itertools.count()

        self.listen_thread = None
        self.start()

        self.websocket_protocols = [] # ???
        self.websocket_extensions = [] # ???

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        self.listen_thread = create_thread(self.listen, name="listen_thread")
        return self

    def set_receive_queue(self, queue):
        self.receive_queue = queue

    def getport(self):
        addr, port = self.socket.getsockname()
        return port

    def listen(self):
        logger.info("Schirm HTTP proxy server listening on localhost:%s" % (self.getport(),))
        while 1:
            self.receive(*self.socket.accept())

    def _close_request(self, id):
        self.requests.pop(id, None)

    def receive(self, client, address):
        self.requests[req.id] = ThreadedRequest(id=self._request_ids.next(),
                                                client=client,
                                                address=address,
                                                serverport=self.getport(),
                                                request_cb=self.request_cb,
                                                close_cb=self._close_request)
        self.requests[req.id].handle()

    # (public) method to respond to requests

    def respond(self, id, data=None, close=False):
        """Respond to request id using data, optionally closing the connection.

        If close is False, keep the connection open and wait for more data.

        Responding with nonempty data to a websocket upgrade requests
        always responds with an upgrade before sending data.
        """
        if id in self.requests:
            self.requests.get(id).respond(data, close)
        else:
            logger.error("Invalid request id: %s" % (id, ))
