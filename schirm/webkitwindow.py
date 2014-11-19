import sys
import os
import pkgutil
import Queue
import StringIO
import urlparse
import mimetypes
import pkgutil

try:
    from PyQt4 import QtCore, QtGui, QtWebKit, QtNetwork
except ImportError:
    from PySide import QtCore, QtGui, QtWebKit, QtNetwork

HTTP_STATUS = {
    200: 'OK',
    301: 'Moved Permanently',
    302: 'Found',
    400: 'Bad Request',
    404: 'Not Found',
    406: 'Not Acceptable',
    500: 'Internal Server Error',
    503: 'Service Unavailable',
}

class Message():

    """An HTTP message.

    headers must be a dict of {str: str/unicode}. (unicode gets
    converted to an utf8 string)

    body must be either None, str. When unicode, convert it to an utf8
    string, else convert it to a str.
    """

    def __init__(self, headers={}, body=None):
        self.headers = {}
        for k,v in headers.items():
            assert isinstance(k, str), "header keys must be strings, not: %r" % (k, )

            if isinstance(v, unicode):
                v = v.decode('utf-8')
            elif isinstance(v, str):
                pass
            else:
                assert False, "header values must be strings or unicode, not: %r" % (v, )

            self.headers[k] = v

        if isinstance(body, unicode):
            self.body = body.encode('utf-8')
        elif isinstance(body, str):
            self.body = body
        elif body is None:
            self.body = ""
        else:
            self.body = str(body)

        self._write_fn = None
        self._close_fn = None

    # streaming response data

    def _set_streaming(self, write_fn, close_fn):
        self._write_fn = write_fn
        self._close_fn = close_fn

    def write(self, data):
        """Write data for a streaming response.

        Return True on success, False otherwise.
        """
        if not self._write_fn:
            raise Exception("not a streaming response")

        if data:
            return self._write_fn(data)

        return False

    def close(self):
        """Close the streaming response.

        Return True on success, False otherwise.
        """
        if not self._write_fn:
            raise Exception("not a streaming response")

        return self._close_fn()


def _parse_url(obj, url):
    """Parse url and add the resulting parts as url_* attrs to obj."""
    r = urlparse.urlparse(url)
    obj.url_scheme = r.scheme
    obj.url_netloc = r.netloc
    obj.url_path = r.path
    obj.url_params = r.params
    obj.url_query = r.query
    obj.url_query_dict = urlparse.parse_qs(r.query)
    obj.url_fragment = r.fragment

def guess_type(name, default="application/octet-stream"):
    """Given a path to a file, guess its mimetype."""
    guessed_type, encoding = mimetypes.guess_type(name, strict=False)
    return guessed_type or default

class Request():

    def __init__(self, method, url, message, fake_reply):
        self.message = message
        self.method = method
        self.url = url
        self.fake_reply = fake_reply
        self._streaming = False
        _parse_url(self, url)

    def respond(self, status=None, message=None, streaming=False):
        """Respond to this request with a Message.

        If streaming is True, initiate a streaming response. Stream
        data using the passed messages .write(data) method and end the
        request with .close().

        Returns True when the reply was initiated successfully, False
        if it failed (e.g. when the client has already closed the
        connection).
        """
        assert isinstance(message, Message)

        status = status or 200
        if isinstance(status, (int, long)):
            status_text = HTTP_STATUS.get(status, 'unknown')
        elif isinstance(status, (tuple, list)):
            status, status_text = status
            status = int(status or 200)
            status_text = str(status_text or 'unknown')
        else:
            raise TypeError("status must be a number or tuple of (status, text), not: %r" % (status, ))

        if streaming:
            def _write_fn(data):
                if self.fake_reply.aborted:
                    return False
                self.fake_reply.fake_response_write.emit(str(data))
                return True

            def _close_fn():
                if self.fake_reply.aborted:
                    return False
                self.fake_reply.fake_response_close.emit()
                return True

            message._set_streaming(write_fn=_write_fn, close_fn=_close_fn)

            if self.fake_reply.aborted:
                return False
            else:
                self.fake_reply.fake_response.emit(status, status_text, message, True)
                if message.body is not None:
                    message.write(message.body)
                return True

        else:
            if self.fake_reply.aborted:
                return False
            else:
                self.fake_reply.fake_response.emit(status, status_text, message, False)
                return True

    # response shortcuts

    def notfound(self, msg=""):
        """Respond with '404 Not Found' and an optional message."""
        return self.respond((404, 'Not Found'), Message({'Content-Type': 'text/plain'}, msg))

    def gone(self, msg=""):
        """Respond with a '410 Gone' and an optional message."""
        return self.respond((404, 'Not Found'), Message({'Content-Type': 'text/plain'}, msg))

    def redirect(self, url):
        """Respond with a 302 Found to url."""
        return self.respond((302, 'Found'), Message({'Location': url}))

    def found(self, body, content_type="text/plain"):
        """Respond with a 200, data and content_type."""
        return self.respond((200, 'Found'), Message({"Content-Type": content_type}, body))

    def found_resource(self, path, module_name, content_type=None, modify_fn=None):
        """Respond with a 200 and a resource file loaded using pkgutil.get_data.

        module_name and path are passed to pkgutil.get_data.
        Optionally run modify_fn on the returned string (e.g. to fill a template).

        Example to deliver a file from the webkitwindow.resources directory:

            req.found_resource(path='/styles.css',
                               module_name='webkitwindow.resources',
                               modify_fn=lambda s: s.replace('TODAY', datetime.datetime.now()))
        """
        res_string = pkgutil.get_data(module_name, path)
        if modify_fn:
            res_string = modify_fn(res_string)
        return self.found(body=res_string, content_type=content_type or guess_type(path))

    def found_file(self, path, content_type=None):
        """Respond with a 200 and the file at path, optionally using content_type."""
        with open(path) as f:
            return self.found(body=f.read(), content_type=content_type or guess_type(path))


class WebSocket():

    # create and pass this to NetworkHandler in the WebSocketBackend class

    def __init__(self, url, backend, id):
        self.url = url
        self._backend = backend
        self._id = id
        _parse_url(self, url)

    def connected(self):
        """Confirm a connection."""
        self._backend.onopen.emit(self._id)

    def send(self, data):
        """Send data over an opened connection."""
        self._backend.send_to_client(self._id, data)

    def close(self):
        """Close the connection."""
        self._backend.server_close(self._id)


class NetworkHandler():
    """A Class dealing with requests from the embedded webkit.

    Subclass or ducktype it to implement your own request/websocket
    handlers.
    """

    def startup(self, window):
        """Called after application startup.

        window is the created WebkitWindow instance.
        """
        pass

    # HTTP

    def request(self, request):
        """Incoming Request.

        Use request.respond(message) to respond.
        """
        pass

    # WebSocket

    def connect(self, websocket):
        """Incoming WebSocket conncetion.

        Call .connected() on the provided websocket object to confirm the connection
        Call .close() to close or abort the connection.
        """
        pass

    def receive(self, websocket, data):
        """Incoming WebSocket data.

        Call .send() on the provided websocket object to send data back.
        """
        pass

    def close(self, websocket):
        """Client has closed the websocket connection."""
        pass


class AnyValue(QtCore.QObject):

    def __init__(self, value):
        self.value = value


class AsyncNetworkHandler(QtCore.QObject):
    _request   = QtCore.pyqtSignal(object)
    _connect   = QtCore.pyqtSignal(object)
    _receive   = QtCore.pyqtSignal(object, str)
    _close     = QtCore.pyqtSignal(object)

    def __init__(self, network_handler):
        super(AsyncNetworkHandler, self).__init__()
        self._nh = network_handler
        self._request.connect(self.request)
        self._connect.connect(self.connect)
        self._receive.connect(self.receive)
        self._close.connect(self.close)

    # HTTP

    @QtCore.pyqtSlot(object)
    def request(self, request):
        self._nh.request(request)

    # object

    @QtCore.pyqtSlot(object)
    def connect(self, websocket):
        self._nh.connect(websocket)

    @QtCore.pyqtSlot(object, str)
    def receive(self, websocket, data):
        self._nh.receive(websocket, str(data))

    @QtCore.pyqtSlot(object)
    def close(self, websocket):
        self._nh.close(websocket)

class LocalDispatchNetworkAccessManager(QtNetwork.QNetworkAccessManager):
    """
    Custom NetworkAccessManager to intercept requests and dispatch them locally.
    """

    operation_strings = {
        QtNetwork.QNetworkAccessManager.HeadOperation: 'HEAD',
        QtNetwork.QNetworkAccessManager.GetOperation: 'GET',
        QtNetwork.QNetworkAccessManager.PutOperation: 'PUT',
        QtNetwork.QNetworkAccessManager.PostOperation: 'POST',
        QtNetwork.QNetworkAccessManager.DeleteOperation: 'DELETE',
        QtNetwork.QNetworkAccessManager.CustomOperation: None,
    }

    def set_network_handler(self, network_handler):
        # overwriting the ctor with new arguments is not allowed -> use a setter instead
        self.network_handler = network_handler

    def createRequest(self, operation, request, data):
        reply = None

        # decode operation (== request method)
        op_str = self.operation_strings[operation]
        if op_str:
            method = op_str
        else:
            # custom
            method = str(request.attribute(QNetwork.QNetworkRequest.CustomVerbAttribute).toString())

        url = str(request.url().toString())
        headers = dict((str(h),str(request.rawHeader(h))) for h in request.rawHeaderList())

        # data is a QIODevice or None
        msg = Message(headers=headers, body=data and str(data.readAll()))
        reply = FakeReply(self, request, operation)
        self.network_handler._request.emit(Request(method=method, url=url, message=msg, fake_reply=reply)) # will .set_response the FakeReply to reply
        QtCore.QTimer.singleShot(0, lambda:self.finished.emit(reply))
        return reply


class FakeReply(QtNetwork.QNetworkReply):
    """
    QNetworkReply implementation that returns a given response.
    """

    fake_response       = QtCore.pyqtSignal(int, str, object, object)
    fake_response_write = QtCore.pyqtSignal(object)
    fake_response_close = QtCore.pyqtSignal()

    def __init__(self, parent, request, operation):
        QtNetwork.QNetworkReply.__init__(self, parent)

        self.fake_response.connect(self._fake_response)
        self.fake_response_write.connect(self._fake_response_write)
        self.fake_response_close.connect(self._fake_response_close)

        self._streaming = False
        self._content = None
        self._offset = 0

        # know when to stop writing into the reply
        self.aborted = False

        self.setRequest(request)
        self.setUrl(request.url())
        self.setOperation(operation)
        self.open(self.ReadOnly | self.Unbuffered)

    @QtCore.pyqtSlot(int, str, object, object)
    def _fake_response(self, status, status_text, response, streaming):
        assert isinstance(response, Message)

        # status
        self.setAttribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute, status)
        self.setAttribute(QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute, status_text)

        # headers
        for k,v in response.headers.items():
            self.setRawHeader(QtCore.QByteArray(k), QtCore.QByteArray(v))

        if streaming:
            # streaming response, call fake_response_write and fake_response_close
            self._streaming = True
            self._content = StringIO.StringIO()

        else:
            self._content = response.body
            self._offset = 0

            # respond immediately
            if self._content and not 'Content-Length' in response.headers:
                self.setHeader(QtNetwork.QNetworkRequest.ContentLengthHeader, QtCore.QVariant(len(self._content)))

            QtCore.QTimer.singleShot(0, lambda : self.readyRead.emit())
            QtCore.QTimer.singleShot(0, lambda : self.finished.emit())

    @QtCore.pyqtSlot(object)
    def _fake_response_write(self, response):
        assert isinstance(response, basestring)
        assert self._streaming, "not a streaming response"
        self._content.write(response)
        self.readyRead.emit()

    @QtCore.pyqtSlot()
    def _fake_response_close(self):
        assert self._streaming, "not a streaming response"
        self.finished.emit()

    def abort(self):
        self.aborted = True
        self.finished.emit()

    def bytesAvailable(self):
        if isinstance(self._content, StringIO.StringIO):
            c = self._content.getvalue()
        else:
            c = self._content

        avail = long(len(c) - self._offset + super(FakeReply, self).bytesAvailable())
        return avail

    def isSequential(self):
        return True

    def readData(self, max_size):
        if isinstance(self._content, StringIO.StringIO):
            c = self._content.getvalue()
        else:
            c = self._content

        if self._offset < len(c):
            size = min(max_size, len(c)-self._offset)
            data = c[self._offset:self._offset+size]
            self._offset += size
            return data
        else:
            return None


class WebSocketBackend(QtCore.QObject):

    # javascript websocket events fo the given connection_id
    onmessage = QtCore.pyqtSignal(int, str)
    onopen    = QtCore.pyqtSignal(int)
    onclose   = QtCore.pyqtSignal(int)

    def __init__(self, network_handler):
        super(WebSocketBackend, self).__init__()
        self._connections = {}
        self._network_handler = network_handler

    @QtCore.pyqtSlot(str, result=int)
    def connect(self, url):
        """Create a websocket connection."""
        id = max(self._connections.keys() or [0]) + 1
        ws = WebSocket(str(url), self, id)
        self._connections[id] = ws
        QtCore.QTimer.singleShot(0, lambda: self._network_handler._connect.emit(ws)) #??????
        return id

    @QtCore.pyqtSlot(int)
    def client_close(self, id):
        """Close the given websocket connection, initiated from the client."""
        self._network_handler._close.emit(self._connections[id])
        del self._connections[id]

    def server_close(self, id):
        """Close the given websocket connection, initiated from the server."""
        del self._connections[id]
        self.onclose.emit(id)

    @QtCore.pyqtSlot(int, str)
    def send_to_server(self, id, data):
        """Send data on the given websocket connection to the network_handler."""
        self._network_handler._receive.emit(self._connections[id], data)

    def send_to_client(self, id, data):
        """Send data from the backend to the given websocket in the browser."""
        assert self._connections[id]
        self.onmessage.emit(id, data)


class _WebkitWindow(QtGui.QMainWindow):

    _close_window = QtCore.pyqtSignal()

    def __init__(self, network_handler, url=None):
        self.url = url or "http://localhost"
        self.network_handler = AsyncNetworkHandler(network_handler)
        QtGui.QMainWindow.__init__(self)
        self.setup()

    def setup(self):
        centralwidget = QtGui.QWidget()
        centralwidget.setObjectName("centralwidget")
        horizontalLayout = QtGui.QHBoxLayout(centralwidget)
        horizontalLayout.setObjectName("horizontalLayout")
        webView = QtWebKit.QWebView(centralwidget)
        webView.setObjectName("webView")
        webpage = QtWebKit.QWebPage()

        # set the custom NAM
        nam = LocalDispatchNetworkAccessManager()
        nam.set_network_handler(self.network_handler)
        webpage.setNetworkAccessManager(nam)

        # websocket requests do not go through the custom NAM
        # -> catch them in the javascript directly
        self.websocket_backend = WebSocketBackend(self.network_handler)
        self.setup_local_websockets(webpage)
        webView.setPage(webpage)

        horizontalLayout.addWidget(webView)
        horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(centralwidget)

        webView.setUrl(QtCore.QUrl(self.url))

        # setup webkit
        gs = QtWebKit.QWebSettings.globalSettings()
        gs.setAttribute(QtWebKit.QWebSettings.PluginsEnabled, True)
        gs.setAttribute(QtWebKit.QWebSettings.JavascriptEnabled, True)
        gs.setAttribute(QtWebKit.QWebSettings.AutoLoadImages, True)
        gs.setAttribute(QtWebKit.QWebSettings.JavascriptCanOpenWindows, True)
        gs.setAttribute(QtWebKit.QWebSettings.DeveloperExtrasEnabled, True)
        gs.setAttribute(QtWebKit.QWebSettings.LocalContentCanAccessRemoteUrls, True)

        # setup app details
        QtGui.QApplication.setApplicationName("Panel")
        QtGui.QApplication.setOrganizationName("Panel")

        # close slot
        def _close_handler():
            # without resetting the QtWebView widget, I get segfaults
            # when closing this window
            self.setCentralWidget(QtGui.QWidget())
            self.close()
        self._close_window.connect(_close_handler)

    ### Capturing Websocket Connections

    # For WebSockets, QtWebKit does not use the
    # QNetworkAccessManager. Thus we 'intercept' WebSocket connection
    # attempts by adding our own implementation of the WebSocket
    # interface to the javascript window context of each new frame.
    websocket_js = pkgutil.get_data(__name__, 'websocket.js')

    def setup_local_websockets_on_frame(self, qwebframe):
        def _load_js(f=qwebframe, js=self.websocket_js, websocket_backend=self.websocket_backend):
            # without passing arguments as default keyword arguments, I get strange errors:
            #     "NameError: free variable 'self' referenced before assignment in enclosing scope"
            # which looks like sombody is trying to null all local
            # arguments at the end of my function
            f.addToJavaScriptWindowObject("_wsExt", websocket_backend)
            f.evaluateJavaScript(js)

        # TODO: 'dispose' the websocket object when the frame is gone (e.g. after reload)
        qwebframe.javaScriptWindowObjectCleared.connect(_load_js)

    def setup_local_websockets(self, qwebpage):
        qwebpage.frameCreated.connect(lambda frame: self.setup_local_websockets_on_frame(frame))


class WebkitWindow(object):

    @classmethod
    def run(self, handler, url="http://localhost", exit=True):
        """Open a window displaying a single webkit instance.

        handler must be an object implementing the NetworkHandler
        interface (or deriving from it).

        Navigate the webkit to url after opening it.

        If exit is true, sys.exit after closing the window.
        """
        win = self(handler, url, exit)
        return win._run()

    @staticmethod
    def run_later(f, timeout=None):
        """Enqueue and run function f on the main thread."""
        QtCore.QTimer.singleShot(timeout or 0, f)

    def __init__(self, handler, url, exit):
        self._handler = handler
        self._url = url
        self._exit = exit

    def _run(self):
        app = QtGui.QApplication(sys.argv)
        self._window = _WebkitWindow(self._handler, self._url)
        self._window.show()

        if getattr(self._handler, 'startup', None):
            self.run_later(lambda:self._handler.startup(self))

        if self._exit:
            sys.exit(app.exec_())
        else:
            return app.exec_()

    def close(self):
        """Close this WebkitWindow and exit."""
        self._window._close_window.emit()
