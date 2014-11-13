import socket
import urllib
import urlparse
import errno
import re
import email.parser

import webkitwindow
import utils


def probe(host, port, **ignore):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
        return True
    except socket.error, e:
        if e.errno == errno.ECONNREFUSED:
            pass
    finally:
        s.close()

    return False


class ProxyTcpConnection():

    """Send a webkitwindow.Request to host:port and deal with the response.

    Remove the url component from the requested path and add
    a 'Host: <url.netloc>' header to the request.
    """

    def __init__(self, req, port, host, url):
        self.req = req
        self.port = port
        self.host = host
        self.url = url
        self._url_netloc = urlparse.urlparse(self.url).netloc
        self.closed = False
        self._connect_and_listen()

    def _connect_and_listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((self.host, self.port))
        self._s = s
        utils.create_thread(self._run)

    def _parse_and_respond(self, data, force=False):
        """Try parsing the HTTP response in data.

        When data contains all the whole response up to the headers,
        respond to self.req in streaming mode and return the used
        webkitwindow.message object.

        When the response seems to contain more headers, return None
        without responding to self.req. Use force=True to force
        parsing data and responding to self.req.
        """
        if not '\r\n\r\n' in data:
            if force:
                pass
            else:
                return None

        firstline, rest = data.split('\r\n', 1)
        m = re.match('^HTTP/1.1 ([0-9]{3}) (.*)$', firstline)
        if not m:
            raise Exception("Cannot parse HTTP response: %r" % (firstline, ))
        status = int(m.group(1))
        status_text = m.group(2)

        fp = email.parser.FeedParser()
        fp.feed(rest)
        msg = fp.close()

        response_msg = webkitwindow.Message(headers=dict(msg.items()), body=msg.get_payload())
        self.req.respond(status=(status, status_text), message=response_msg, streaming=True)

        return response_msg

    def _listen(self):
        """Receive data from the socket self._s and respond to self.req."""
        buf = []
        msg = None
        data = 'ignore'
        while msg is None or not data:
            data = self._s.recv(2**16) or ''
            buf.append(data)
            # try parsing what has been received,
            # send and return it on success
            msg = self._parse_and_respond(''.join(buf))

        if not msg:
            self._parse_and_respond(''.join(buf), force=True)
            return

        if not data:
            msg.close()
            return

        # stream the remaining body data
        while True:
            data = self._s.recv(2**16) or ''
            if data:
                msg.write(data)
            else:
                msg.close()
                return

    def _run(self):
        """Send the request in self.req and deal with the response."""
        self._send()
        self._listen()
        self.closed = True

    def _send(self):
        """Send the request in self.req via self._s."""
        if self.closed:
            pass

        self.req.message.headers['Host'] = self._url_netloc

        buf = ["%s %s HTTP 1/1\r\n" % (self.req.method, urllib.quote(self.req.url[len(self.url):]))]
        buf.extend('%s: %s\r\n' % x for x in self.req.message.headers.items())
        buf.append('\r\n')
        buf.append(self.req.message.body or '')

        self._s.sendall(''.join(buf))

    def close(self):
        self._s.close()
