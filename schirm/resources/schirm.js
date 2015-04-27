// schirm client module (use within terminal iframes)

var schirm = (function(schirm) {

    // IPC
    var webSocketUri = "%(websocket_uri)s";
    var commUri = "%(comm_uri)s";
    var preOpenQueue = [];
    var send = function(data) {
        // enqueue all messages sent before the websocket is ready
        preOpenQueue.push(data);
    };
    schirm.send = send;

    var socket = new WebSocket(webSocketUri);
    socket.onopen = function (event) {
        // send enqueued messages
        for (var i=0; i<preOpenQueue.length; i++) {
            socket.send(preOpenQueue[i]);
        }
        preOpenQueue = undefined;

        schirm.send = function(data) { socket.send(data); };
    };

    // socket.onerror =
    // socket.onclose =

    // receiving messages
    var onmessageQueue = []
    socket.onmessage = function (event) {
        if (schirm.onmessage) {
            schirm.onmessage(event.data);
        } else {
            // queue all messages until an onmessage handler is set
            onmessageQueue.push(event.data);
        }
    }

    // message handler:
    // watch on set-'events' of schirm.onmessage, and flush the queue
    // of alread received messages before continuing
    schirm._onmessage = undefined;
    Object.defineProperty(schirm, 'onmessage', {
        set: function(v) {
            if (typeof(v) === "function") {
                // flush the messagequeue
                for (var i=0; i<onmessageQueue.length; i++) {
                    v(onmessageQueue[i]);
                }
                onmessageQueue = [];
                schirm._onmessage = v;
            }
        },
        get: function() {
            return schirm._onmessage;
        }
    });

    // Determine and cache the height of a vertical scrollbar
    var __vscrollbarheight;
    var getVScrollbarHeight = function() {
        var compute = function() {
            var div = document.createElement("div");
            div.style.width = "100px";
            div.style.height = "100px";
            div.style.overflowX = "scroll";
            div.style.overflowY = "scroll";

            var content = document.createElement("div");
            content.style.width = "200px";
            content.style.height = "200px";

            div.appendChild(content);
            document.body.appendChild(div);

            var height = 100 - div.clientHeight;

            document.body.removeChild(div);

            if (height > 0) {
                return height;
            } else {
                return 0;
            }
        };

        if (__vscrollbarheight === undefined) {
            __vscrollbarheight = compute();
        }
        return __vscrollbarheight;
    }
    schirm.getVScrollbarHeight = getVScrollbarHeight;

    // return true if el will render with a vertical scrollbar
    var vScrollbarRequired = function(el, bodyMargin) {
        return el.scrollWidth > (el.clientWidth + bodyMargin);
    }

    // simple get and post
    var request = function(method, uri, data, success) {
        var req = new XMLHttpRequest();
        req.open(method, uri, true);
        req.send(data);
        req.onreadystatechange = function (oEvent) {
            if (req.readyState === 4) {
                if (req.status === 200) {
                    (success || function() {})(req.responseText);
                } else {
                    // nothing
                }
            }
        };
    }

    schirm.GET  = function (uri, data, success) { request('GET', uri, data, success); };
    schirm.POST = function (uri, data, success) { request('POST', uri, data, success); };

    function getElementHeight(e) {
        var style = getComputedStyle(e);
        var margin = parseInt(style.marginTop) + parseInt(style.marginBottom);
        return Math.max(e.scrollHeight, e.clientHeight) + margin;
    }
    schirm.getElementHeight = getElementHeight;

    // ask the iframes parent to resize the current iframe
    var resizePrevHeight;
    schirm.resize = function(height) {

        // fullscreen option
        if (height === 'fullscreen') {
            // either use console.log or POST to a special URL
            if (0) {
                console.log("iframeresize"+newHeight); // IPC
            } else {
                schirm.POST(commUri,
                            JSON.stringify({command:"resize",
                                            height:"fullscreen"}));
            }
            return
        }

        // pixel height options

        // todo: what happens if the style is not using px?
        var bodyStyle = getComputedStyle(document.body);
        var bodyMargin = parseInt(bodyStyle.marginTop) + parseInt(bodyStyle.marginBottom);

        var vScrollbarHeight = 0;
        if (vScrollbarRequired(document.body, bodyMargin)) {
            vScrollbarHeight = getVScrollbarHeight();
        }

        var newHeight;
        if ((typeof height) === 'number') {
            newHeight = height + vScrollbarHeight + bodyMargin;
        } else if ((typeof height) === 'object') {
            newHeight = getElementHeight(height) + vScrollbarHeight + bodyMargin;
        } else if (height === undefined) {
            // auto-resize the body
            newHeight = document.body.scrollHeight + vScrollbarHeight + bodyMargin;
        }

        if (resizePrevHeight !== newHeight) {
            resizePrevHeight = newHeight;
            // either use console.log or POST to a special URL
            if (0) {
                console.log("iframeresize"+newHeight); // IPC
            } else {
                schirm.POST(commUri,
                            JSON.stringify({command:"resize",
                                            height:newHeight}));
            }
        }
    }

    // Resize the iframe to have enough space for height using schirm.resize.
    // Listen to window resize events to adjust the height accordingly.
    schirm.resizing = function(height) {
        schirm.resize(height);

        var resizeHandler = function() {
            // remove the resize callback when resizing to prevent
            // infinite callback recursion
            window.removeEventListener('resize', resizeHandler);
            schirm.resize(height);
            window.setTimeout(0, function() {
                window.addEventListener('resize', resizeHandler);
            });
        };
        window.addEventListener('resize', resizeHandler);
    };

    schirm.ready = function(f) {
        document.addEventListener('readystatechange', function() {
            if (document.readyState == "complete") {
                f();
            }
        });
    };

    // TODO:
    // websocket to communicate with the schirm process:
    //   json messages for both, internal uses (resizeiframe) and schirm
    //   user process communication

    // Embedd a SchirmTerminal inside an iframe the embedded terminal
    // will be under full control of the surrounding schirm iframe and
    // provides the same capabilities (iframe mode, vt100 emulation) as
    // the main terminal.
    schirm.SchirmTerminal = function() {
        var self = this;
        // RPC-style API

    }

    return schirm;

})(schirm || {})
