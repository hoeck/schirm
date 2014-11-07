/**
 * Provide a Websocket interface that uses a QT object (_wsExt)
 * instead of the network to be able to proxy the websocket
 * communication.
 */
(function() {

    // pass the local interfacing object via window globals
    var wsExt = window._wsExt;
    window._wsExt = undefined;

    window.WebSocket = function(url) {
        var self = this, connId;

        self.CONNECTING = 0; // The connection has not yet been established.
        self.OPEN       = 1; // The WebSocket connection is established and communication is possible.
        self.CLOSING    = 2; // The connection is going through the closing handshake.
        self.CLOSED     = 4; // The connection has been closed or could not be opened.

        self.url = url;
        self.readyState = self.CONNECTING;
        self.extensions = "";
        self.protocol = "";

        self.onopen = undefined;
        self.onmessage = undefined;
        self.onerror = undefined;
        self.onclose = undefined;

        self.send = function(data) {
            wsExt.send_to_server(connId, data);
        };

        self.close = function(code, reason) {
            if (self.readyState === self.CLOSING || self.readyState === self.CLOSED) {
                // nothing
            } else if (self.readyState === self.OPEN) {
                self.readyState = self.CLOSING;
                wsExt.close(connId);
                if (self.onclose) {
                    self.onclose();
                }
            } else {
                self.readyState == CLOSED;
            }
        };

        // register callbacks on the Qt side

        wsExt.onopen.connect(function(id) {
            if (id === connId) {
                self.readyState = self.OPEN;
                if (self.onopen) {
                    self.onopen();
                }
            }
        });

        wsExt.onmessage.connect(function(id, data) {
            if (id === connId) {
                if (self.onmessage) {
                    self.onmessage({data:data});
                }
            }
        });

        wsExt.onclose.connect(function(id) {
            if (id === connId) {
                self.readyState = self.CLOSED;
                if (self.onclose) {
                    self.onclose();
                }
            }
        });

        // init
        connId = wsExt.connect(url);
    };
})();
