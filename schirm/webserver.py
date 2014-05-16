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
import pkgutil
import mimetypes
import itertools
import email.parser
from BaseHTTPServer import BaseHTTPRequestHandler
from StringIO import StringIO

from hashlib import sha1
from ws4py import WS_KEY, WS_VERSION
from ws4py.exc import HandshakeError, StreamClosed
from ws4py.streaming import Stream
from ws4py.websocket import WebSocket

import chan

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
    """Websocket writing incoming data to a chan."""

    def __init__(self, *args, **kwargs):
        self.chan = kwargs.pop('chan')
        super(AsyncWebSocket, self).__init__(*args, **kwargs)

    def received_message(self, message):
        self.chan.put(str(message))

class ThreadedRequest(object):
    """A Request waiting for responses in its own thread."""

    # close the connections for requests which have been dispatched to the terminal
    # and received no response after this amount of seconds
    TIMEOUT = 30

    _websocket_protocols = [] # ???
    _websocket_extensions = [] # ???

    @classmethod
    def create(self, **kwargs):
        r = self(**kwargs)
        utils.create_thread(r._run)
        return r

    def __init__(self, id, client, address, port, chan_out):
        self.id = id

        # socket data
        self._client = client
        self._address = address
        self._port = port
        self._timeout = self.TIMEOUT

        # comm
        self._chan_out = chan_out         # a Chan to put this requests (once we received it fully) or websocket messages on
        self._response_chan = chan.Chan() # a Chan to receive response data from

        # request data such as: headers, protocol, ...
        self.data = {}

    def __repr__(self):
        url = urlparse.unquote(self.data.get('path') or '')
        return "#<ThreadedRequest %d %r>" % (self.id, url)

    def _run(self):
        # read request
        self._debugstate = 'receiving'
        self.data = self._receive()
        if not self.data:
            # fail
            self._close()
        else:
            self._chan_out.put(self)
            # get responses from the chan in req
            got_response = False
            while True:
                try:
                    if self._response_chan.get(timeout=self._timeout)():
                        # the _respond or _respond_websocket functions
                        # return False to close the connection
                        self._close()
                        return
                    got_response = True
                except chan.Timeout, e:
                    if self._timeout:
                        if not got_response:
                            self._respond(self._gateway_timeout(), close=True)
                            return

    def _close(self):
        logger.debug('(%03d) closing socket', self.id)
        self._debugstate = 'closing-socket'
        self._response_chan.close()
        try:
            sock = self._client._sock
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
            self._debugstate = 'closed'
        except Exception, e:
            logger.error('(%03d) could not close connection of request (ex: %s)', self.id, e)

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

        return {'id'              : self.id,
                'protocol'        : 'websocket',
                'path'            : path,
                'headers'         : dict(req.headers),
                'upgrade'         : True,
                'data'            : '',
                # channel to send the response to
                'chan'            : chan.Chan(),
                # a channel to receive messages from
                'in_chan'         : chan.Chan(),
                'ws_key'          : ws_key,
                'ws_version'      : ws_version,
                'ws_protocols'    : ws_protocols,
                'ws_extensions'   : ws_extensions}

    def _receive_proxy_connect(self, req):
        # proxy connection established
        # TODO: proper path parsing!
        self._debugstate = 'proxy-connect'
        if req.path.endswith('localhost:80'):
            self._client.sendall("HTTP/1.1 200 Connection established\r\n\r\n")
            return self._receive('http://%s' % req.path[:-3])
        else:
            # ignore all chromium google URLs
            if req.path in ("ssl.gstatic.com:443",
                            "www.gstatic.com:443",
                            "translate.googleapis.com:443",
                            "www.google.com:443",
                            "clients3.google.com:443",
                            "clients2.google.com:443",
                            "clients.google.com:443",
                            "safebrowsing.google.com:443",
                            "alt1-safebrowsing.google.com:443"):
                pass
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

        # ignore annoying chromium requests
        if "clients2.google.com/service" in req.path:
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
            #self._request['protocol'] = 'websocket'
            # prepare for an upgrade to a websocket connection
            return self._receive_websocket(req, path)

        else:
            # plain http
            return {'id'              : self.id,
                    'protocol'        : 'http',
                    'request_version' : req.request_version,
                    'method'          : req.command,
                    'raw_headers'     : req.headers.headers,
                    'path'            : path,
                    'headers'         : dict(req.headers),
                    'data'            : data,
                    'error_code'      : req.error_code,
                    'error_message'   : req.error_message,
                    # channel to send the response to
                    'chan'            : chan.Chan(),
                    # include the portnumber of this
                    # webserver to allow creating a
                    # direct websocket uri as
                    # websocket requests are not
                    # proxied in webkitgtk (1.8.1)
                    'proxy_port'      : self._port}

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
                "Sec-WebSocket-Version: %s" % self.data['ws_version'],
                "Sec-WebSocket-Accept: %s" % base64.b64encode(sha1(self.data['ws_key'] + WS_KEY).digest()),
                "",
                ""])
        self._client.sendall(data)

        websocket = AsyncWebSocket(sock=self._client,
                                   protocols=self.data['ws_protocols'],
                                   extensions=self.data['ws_extensions'],
                                   environ=None,
                                   chan=self.data['in_chan'])

        self.data.update({'websocket': websocket})

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

        return websocket

    def _respond_websocket(self, data, close=False):
        """close or send data over the websocket.

        possible combinations of data and close and their reactions:
          (None, True)  - close (without updgrading)
          (None, False) - upgrade if required
          (str,  False) - upgrade if required, send str
          (str,  True)  - upgrade if required, send str, close
        """
        ws = self.data.get('websocket')

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

        if close:
            return True

    def _respond(self, data, close):
        # return true to close the request thread loop
        self._debugstate = 'responding'
        if self.data['protocol'] == 'http':
            return self._respond_http(data, close)
        else:
            return self._respond_websocket(data, close)

    # public API

    def disable_timeout(self):
        """Disable the default gateway timeout."""
        self._timeout = None

    def respond(self, data, close=True):
        """Respond using data, optionally closing the connection.

        If close is False, keep the connection open and wait for more data.

        Responding with nonempty data to a websocket upgrade requests
        always responds with an upgrade before sending data.
        """
        self._response_chan.put(lambda : self._respond(data, close))

    # respond helpers

    def notfound(self, msg=""):
        """Respond with a 404 Not Found and close the connection."""
        response = '\r\n'.join(
            ["HTTP/1.1 404 Not Found",
             "Content-Length: " + str(len(msg)),
             "Connection: close",
             "",
             msg.encode('utf-8') if isinstance(msg, unicode) else msg
         ])
        self.respond(response)

    def found(self, body, content_type):
        """Respond with a 200 and data and content_type."""
        assert self.data['protocol'] == 'http'
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
        self.respond(response)

    def gone(self, msg=""):
        """Respond with a 410 Gone and close the connection."""
        response = '\r\n'.join([
            "HTTP/1.1 410 Gone",
            "Content-Length: " + str(len(msg)),
            "Connection: close",
            "",
            msg
        ])
        self.respond(response)

    def done(self, msg=""):
        """Respond with a 200 Done and close the connection."""
        assert self.data['protocol'] == 'http'
        response = '\r\n'.join([
            "HTTP/1.1 200 Done",
            "Content-Length: " + str(len(msg)),
            "Connection: close",
            "",
            msg
        ])
        self.respond(response)

    def redirect(self, url):
        """Respond with a 302 Found to url."""
        assert self.data['protocol'] == 'http'
        response = '\r\n'.join([
            "HTTP/1.1 302 Found",
            "Location: %s" % url,
            "Connection: close",
            "",
        ])
        self.respond(response)

    def found_resource(self, path, resource_module_name='schirm.resources', modify_fn=None):
        """Respond with a 200 to a request with a resource file."""
        res_string = pkgutil.get_data(resource_module_name, path)
        if modify_fn:
            res_string = modify_fn(res_string)
        self.found(body=res_string,
                   content_type=guess_type(path))

    def found_file(self, path, content_type=None):
        """Respond with a 200 and the file at path, optionally using content_type."""
        with open(path) as f:
            self.found(body=f.read(),
                       content_type=content_type or guess_type(path))

    def websocket_upgrade(self):
        """Upgrade response to a websocket request."""
        assert self.data['protocol'] == 'websocket'
        self.respond(data='', close=False)

class Server(object):
    """Websocket enabled proxy-webserver."""

    def __init__(self):
        self.socket = socket.socket()
        self.chan = chan.Chan() # a Chan to put incoming requests on,
                                # to be read by an external dispatch thread
        self.port = None

    def start(self):
        backlog = 5
        self.socket.bind(('localhost',0))
        self.socket.listen(backlog)
        utils.create_thread(self.listen, name="listen_thread")
        addr, port = self.socket.getsockname()
        self.port = port
        return self

    def listen(self):
        logger.info("Schirm HTTP proxy server listening on localhost:%s" % (self.port,))
        ids = itertools.count()
        while 1:
            self.receive(ids.next(), *self.socket.accept())

    def receive(self, id, client, address):
        ThreadedRequest.create(id=id,
                               client=client,
                               address=address,
                               port=self.port,
                               chan_out=self.chan)
