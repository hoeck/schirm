import socket

import utils

class ProxyTcpConnection():

    def __init__(self, req, port, host):
        self.req = req
        self.port = port
        self.host = host
        self.closed = False
        self._connect_and_listen()

    def _connect_and_listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((self.host, self.port))
        self._s = s
        utils.create_thread(self._listen)

    def _listen(self):
        while True:
            data = self._s.recv(1024)
            if data:
                self.req.respond(data, close=False)
            else:
                self.closed = True
                self.req.respond(None, close=True)
                return

    def send(self, data):
        if not self.closed:
            self._s.sendall(data)
        else:
            pass

    def close(self):
        self._s.close()
