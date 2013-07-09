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
import mimetypes
import Queue
import itertools
import email.parser
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO

from hashlib import sha1
from ws4py import WS_KEY, WS_VERSION
from ws4py.exc import HandshakeError, StreamClosed
from ws4py.streaming import Stream
from ws4py.websocket import WebSocket

import utils

# logging

logger = logging.getLogger(__name__)

# utils

# chrome complains when using 'application/octet-stream' for fonts
if not '.ttf' in mimetypes.types_map:
    mimetypes.types_map['.ttf'] = "application/x-font-ttf"
if not '.otf' in mimetypes.types_map:
    mimetypes.types_map['.otf'] = "application/x-opentype"

def guess_type(name, default="application/octet-stream"):
    """Given a path to a file, guess its mimetype."""
    guessed_type, encoding = mimetypes.guess_type(name, strict=False)
    return guessed_type or default

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
        self.close_cb   = kwargs.pop('close_cb',   lambda *_: None)
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

    def __init__(self, id, client, address, serverport, queue, close_cb):
        self.id = id                  # unique id to identify this request in the terminal client
        self._client = client         # client socket
        self._address = address       # client address
        self._serverport = serverport # port of the http server, to be able to parse proxy requests
        self._queue = Queue.Queue()   # external input, popped in the worker thread
        self._queue_out = queue       # a Queue to put incoming requests or websocket data on (in the form of messages)
        self._worker = None           # thread
        self._close_cb = close_cb     # called when the request connection has been closed
        self._got_request = False     # set to True after the request has been parsed
        self._response_in_progress = False # set to True after receiving the first request response via the queue

        # debugdata
        self._request = {}            # internal request data
        self._debugstate = "init"     # current state

    def __repr__(self):
        state = ' '.join(filter(None, [self._debugstate,
                                       self._request.get('method'),
                                       self._request.get('path')]))
        return "#<ThreadedRequest %03d %s>" % (self.id, state)

    def handle(self):
        self._worker = utils.create_thread(self._run, name='request_%s' % self.id)

    def _run(self):
        # read request
        self._debugstate = 'receiving'
        req = self._receive()
        if not req:
            # fail
            self._close()
        else:
            self._got_request = True
            self._debugstate = 'enqueueing-request'
            # enqueue the request data
            self._queue_out.put({'name':'request', 'msg':req})
            self._debugstate = 'waiting-for-response'
            # wait for responses
            while True:
                try:
                    if self._queue.get(timeout=self.TIMEOUT)():
                        self._close()
                        return
                except Queue.Empty, e:
                    if not self._response_in_progress:
                        self._respond(self._gateway_timeout(), close=True)
                        return

    def _close(self):
        logger.debug('(%03d) closing socket', self.id)
        self._debugstate = 'closing-socket'
        try:
            sock = self._client._sock
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
            self._debugstate = 'closed'
        except Exception, e:
            logger.error('(%03d) could not close connection of request (ex: %s)', self.id, e)
        self._close_cb()

    @staticmethod
    def _bad_handshake(msg):
        return '\r\n'.join(["HTTP/1.1 400 Bad Handshake",
                            "Content-Length: " + str(len(msg)),
                            "Connection: close",
                            "",
                            msg])

    @staticmethod
    def _gateway_timeout(msg=''):
        return '\r\n'.join(["HTTP/1.1 504 Gateway Timeout",
                            "Content-Length: " + str(len(msg)),
                            "Connection: close",
                            "",
                            msg])

    # decode incoming requests

    def _receive_websocket(self, req, path):
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

        self._request.update({'protocol': 'websocket',
                              'ws_key': ws_key,
                              'ws_version': ws_version,
                              'ws_protocols': ws_protocols,
                              'ws_extensions': ws_extensions})

        return {'id'              : self.id,
                'protocol'        : 'websocket',
                'path'            : path,
                'headers'         : dict(req.headers),
                'upgrade'         : True,
                'data'            : ''}

    def _receive_proxy_connect(self, req):
        # proxy connection established
        # TODO: proper path parsing!
        self._debugstate = 'proxy-connect'
        if req.path.endswith('localhost:80'):
            self._client.sendall("HTTP/1.1 200 Connection established\r\n\r\n")
            return self._receive('http://%s' % req.path[:-3])
        else:
            logger.error('(%03d) invalid connect path: %r', self.id, req.path)
            return None

    def _receive(self, host=''):
        """Receive a request.

        Store all request related data into the request attribute.
        Return a dictionary describing the request or None if the
        request is invalid for whatever reasons.
        """

        rfile = self._client.makefile()
        req = HTTPRequest(rfile)
        path = host + getattr(req, 'path', '')

        if not req.requestline:
            # ignore 'empty' google chrome requests
            # TODO: debug
            return None

        if req.headers.get("Content-Length"):
            data = req.rfile.read(long(req.headers.get("Content-Length")))
        else:
            data = None

        logger.info("(%03d) %s %s", self.id, req.command, path)

        if req.command == 'CONNECT':
            # proxy connection (for websockets or https)
            return self._receive_proxy_connect(req)

        elif req.headers.get('Upgrade') == 'websocket':
            self._request['protocol'] = 'websocket'
            # prepare for an upgrade to a websocket connection
            return self._receive_websocket(req, path)

        else:
            self._request['protocol'] = 'http'
            self._request['path'] = path
            self._request['method'] = req.command
            # plain http
            return {'id'              : self.id,
                    'protocol'        : 'http',
                    'request_version' : req.request_version,
                    'method'          : req.command,
                    'path'            : path,
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
        self._debugstate = 'websocket-upgrade'
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
        self._response_in_progress = True

        def _recv(msg):
            req_message = {'id'              : self.id,
                           'protocol'        : 'websocket',
                           'data'            : str(msg)}
            self._queue_out.put({'name':'request', 'msg': req_message})

        def _close_cb():
            self._respond(None, close=True)

        websocket = AsyncWebSocket(sock=self._client,
                                   protocols=self._request['ws_protocols'],
                                   extensions=self._request['ws_extensions'],
                                   environ=None,
                                   receive_cb=_recv,
                                   close_cb=_close_cb)

        self._request.update({'websocket': websocket})

        # read from the websocket in a separate thread
        def _run():
            try:
                websocket.run()
            except socket.error, e:
                if e.errno == 104: # "Connection reset by peer"
                    # remote processs was killed
                    logger.debug('(%03d) - socket.error: %s', self.id, e)
                    pass
                else:
                    raise e

        utils.create_thread(_run)

        self._debugstate = 'websocket'

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
            if logger.getEffectiveLevel() <= logging.INFO:
                if data:
                    try:
                        # try to parse a to be able to
                        fp = email.parser.FeedParser()
                        reqline, message = data.split('\n', 1)
                        status, status_msg = re.match("HTTP/1\\.[01] ([0-9]+) ?(.*)", reqline.strip()).groups()
                        # RFC 821 Message
                        fp.feed(message)
                        m = fp.close()
                        header = dict(m.items())
                        body = m.get_payload()
                        logmsg = "%(status)s (%(content_type)s) %(body)r" % {'status': status,
                                                                             'content_type': header.get('Content-Type', '<unknown>'),
                                                                             'body': utils.shorten(body)}
                    except:
                        logmsg = '<error decoding response:> %s' % repr(utils.shorten(data))

                logger.debug("(%03d) - %s", self.id, logmsg)

            self._client.sendall(data)

        self._response_in_progress = True
        if close:
            return True

    def _respond(self, data, close):
        # return true to close the request thread loop
        self._debugstate = 'responding'
        if self._request['protocol'] == 'http':
            return self._respond_http(data, close)
        else:
            return self._respond_websocket(data, close)

    # public API

    def got_request(self):
        return self._got_request

    def respond_async(self, data, close):
        """Enqueue a response"""
        self._queue.put(lambda: self._respond(data, close))

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

    def __init__(self, queue):
        self.socket = socket.socket()
        # the terminal process will receive the request data and a
        # connection-id and its response must contain the
        # connection-id to determine which connection to use for
        # sending the response
        self.requests = {}
        self._request_ids = itertools.count()

        # a Queue to put incoming request messages on
        self.queue = queue

        self.listen_thread = None
        self.start()

        self.websocket_protocols = [] # ???
        self.websocket_extensions = [] # ???

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        self.listen_thread = utils.create_thread(self.listen, name="listen_thread")
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
        req_id = self._request_ids.next()
        self.requests[req_id] = ThreadedRequest(id=req_id,
                                                client=client,
                                                address=address,
                                                serverport=self.getport(),
                                                queue=self.queue,
                                                close_cb=lambda: self._close_request(req_id))
        self.requests[req_id].handle()

    # (public) method to respond to requests

    def handle(self, msg):
        id = msg.pop('id')
        method = msg.pop('method')
        if method == 'respond':
            self.respond(id, **msg)
        elif method == 'notfound':
            self.notfound(id, **msg)
        elif method == 'found':
            self.found(id, **msg)
        elif method == 'gone':
            self.gone(id, **msg)
        elif method == 'done':
            self.done(id, **msg)
        elif method == 'redirect':
            self.redirect(id, **msg)
        else:
            logger.error('invalid method in message: %r', method)

    def respond(self, id, data=None, close=False):
        """Respond to request id using data, optionally closing the connection.

        If close is False, keep the connection open and wait for more data.

        Responding with nonempty data to a websocket upgrade requests
        always responds with an upgrade before sending data.
        """
        if id in self.requests:
            self.requests[id].respond_async(data, close)
        else:
            logger.error("Invalid request id: %r", id)

    def abort_pending_requests(self, except_id):
        """Close all requests that wait for a response except the given one."""
        reqs = [r for r in self.requests.values() if r.got_request() and r.id != except_id]
        logger.debug('ABORT:\n%s', '\n'.join(repr(r) for r in reqs))
        for r in reqs:
            self.gone(r.id)

    # respond helpers

    def notfound(self, id, msg=""):
        """Respond to a request with a 404 Not Found and close the connection."""
        response = '\r\n'.join(
            ["HTTP/1.1 404 Not Found",
             "Content-Length: " + str(len(msg)),
             "Connection: close",
             "",
             msg.encode('utf-8') if isinstance(msg, unicode) else msg
         ])
        self.respond(id, response, close=True)

    def found(self, id, body, content_type):
        """Respond to a request with a 200 and data and content_type."""
        response = "\r\n".join([
            "HTTP/1.1 200 OK",
            "Cache-Control: " + "no-cache",
            "Connection: close",
            "Content-Type: " + (content_type.encode('utf-8')
                                if isinstance(content_type, unicode)
                                else content_type),
            "Content-Length: " + str(len(body)),
            "",
            body.encode('utf-8') if isinstance(body, unicode) else body
        ])
        self.respond(id, response, close=True)

    def gone(self, id, msg=""):
        """Respond to a request with a 410 Gone and close the connection."""
        response = '\r\n'.join([
            "HTTP/1.1 410 Gone",
            "Content-Length: " + str(len(msg)),
            "Connection: close",
            "",
            msg
        ])
        self.respond(id, response, close=True)

    def done(self, id, msg=""):
        """Respond to a request with a 200 Done and close the connection."""
        response = '\r\n'.join([
            "HTTP/1.1 200 Done",
            "Content-Length: " + str(len(msg)),
            "Connection: close",
            "",
            msg
        ])
        self.respond(id, response, close=True)

    def redirect(self, id, url):
        """Respond to a request with a 302 Found to url."""
        response = '\r\n'.join([
            "HTTP/1.1 302 Found",
            "Location: %s" % url,
            "Connection: close",
            "",
        ])
        self.respond(id, response, close=True)

class AsyncHttp(object):
    """Webserver Response API putting messages on a Queue for debuggable async communication.


    See the respective methods of the Server class for more documentation.
    """

    def __init__(self, queue):
        self.queue = queue

    def _put_msg(self, msg):
        self.queue.put({'name':'webserver', 'msg':msg})

    def respond(self, id, data=None, close=False):
        """Respond to request id using data, optionally closing the connection."""
        self._put_msg({'method':'respond', 'id': id, 'data': data, 'close': close})

    def notfound(self, id, msg=""):
        """Respond to a request with a 404 Not Found and close the connection."""
        self._put_msg({'method':'notfound', 'id':id, 'msg':msg})

    def found(self, id, body, content_type):
        """Respond to a request with a 200 and data and content_type."""
        self._put_msg({'method':'found', 'id':id, 'content_type':content_type, 'body':body})

    def gone(self, id):
        """Respond to a request with a 410 Gone and close the connection."""
        self._put_msg({'method':'gone', 'id':id})

    def done(self, id):
        """Respond to a request with a 200 Done and close the connection."""
        self._put_msg({'method':'done', 'id':id})

    def redirect(self, id, url):
        """Respond to a request with a 302 Found to url."""
        self._put_msg({'method':'redirect', 'id':id, 'url':url})

    # extensions for files and resources

    def found_resource(self, id, path, resource_module_name='schirm.resources', modify_fn=None):
        """Respond with a 200 to a request with a resource file."""
        res_string = pkg_resources.resource_string(resource_module_name, path)
        if modify_fn:
            res_string = modify_fn(res_string)
        self.found(id,
                   body=res_string,
                   content_type=guess_type(path))

    def found_file(self, id, path, content_type=None):
        with open(path) as f:
            self.found(id,
                       body=f.read(),
                       content_type=content_type or guess_type(path))
