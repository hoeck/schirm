
import socket
import mimetypes
import threading

class Server(object):
    """
    1) A simple server which reads requests from the embedded webkit,
    enumerates them and writes them to the pty using a special ESC code:
    ESC R <id> ; <escaped-request-data> \033 Q
    the id is required to know which response belongs to which request.
    Escape all escape-bytes ('\033') in request-data with an escape ('\033').
    
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
        print "listening!"
        while 1:
            client, address = self.socket.accept()
            print "connected!!!!"
            self.receive(client)            
            
    def receive(self, client):
        print "webserver: receiving"

        # is it a known static resource?
        data = client.recv(8192)
        head = data[:data.index("\n")]
        print "request:", head
        method, path, protocol = head.split()
        if method == 'GET' and path in self.resources:
            # serve it
            print "serving static resource:", path
            #print self.resources[path]
            client.sendall(self.resources[path])
            client.close()
            return
        elif method == 'GET' and path in self.not_found:
            # ignore some requests (favicon & /)
            print "not_found"
            client.sendall("HTTP/1.1 404 Not Found")
            return

        else:
            print "No static resource found -> asking pty"
            req_id = self._getnextid()
            self.requests[req_id] = client
            pty_request = ["\033R",
                           str(req_id),
                           ";",
                           data.replace('\033', '\033\033')]
            while 1:
                data = client.recv(8192)
                if not data:
                    break
                pty_request.append(data.replace('\033', '\033\033'))
            pty_request.append('\033Q')
            self.pty.q_write("".join(data))

    def respond(self, req_id, data):
        if req_id in self.requests:
            client = self.requests[req_id]
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
