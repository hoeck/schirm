// schirm client module (use within terminal iframes)

var schirm = (function(schirm) {

    // IPC
    var webSocketUri = "%(websocket_uri)s";
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

    socket.onmessage = function (event) {
        if (schirm.onmessage) {
            schirm.onmessage(event.data);
        }
    }

    // default message handler
    schirm.onmessage = function(data) { };

    // Determine and cache the height of a vertical scrollbar
    var __vscrollbarheight;
    var getVScrollbarHeight = function() {
        var compute = function() {
            var div = document.createElement("div");
            div.style.width = 100;
            div.style.height = 100;
            div.style.overflowX = "scroll";
            div.style.overflowY = "scroll";

            var content = document.createElement("div");
            content.style.width = 200;
            content.style.height = 200;

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

    // return true if el will render with a vertical scrollbar
    var vScrollbarRequired = function(el) {
        return el.scrollWidth > el.clientWidth;
    }

    // simple get and post
    var request = function(method, uri, data, success) {
        var req = new XMLHttpRequest();
        req.open(method, uri, true);
        req.send(data);
        req.onreadystatechange = function (oEvent) {
            if (req.readyState === 4) {
                if (req.status === 200) {
                    success(req.responseText);
                } else {
                    // nothing
                }
            }
        };
    }

    schirm.GET  = function (uri, data, success) { request('GET', uri, data, success); };
    schirm.POST = function (uri, data, success) { request('POST', uri, data, success); };

    // ask the iframes parent to resize the current iframe
    schirm.resize = function(height) {
        var bodyStyle = getComputedStyle(document.body);
        var bodyMargin = parseInt(bodyStyle.marginTop) + parseInt(bodyStyle.marginBottom);

        var vScrollbarHeight = 0;
        if (vScrollbarRequired(document.body)) {
            vScrollbarHeight = getVScrollbarHeight()
        }

        var newHeight = height + bodyMargin + vScrollbarHeight;

        // either use console.log or POST to a special URL
        if (0) {
            console.log("iframeresize"+newHeight); // IPC
        } else {
            console.log('posting');
            schirm.POST('schirm',
                        JSON.stringify({command:"resize",
                                        height:newHeight}),
                        function() { console.log('done posting'); });
        }
    }

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
