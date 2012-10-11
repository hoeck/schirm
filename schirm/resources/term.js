// Redesign of the Schirm API using a js object pattern
// goal: reuse this code to create embedded terminals

var SchirmTerminal = function(parentElement, termId, webSocketUrl) {
    // When a termId & iframeId is given, the resulting terminal will act as an
    // embedded terminal running inside a main terminals iframe line.

    var termMarkup = "\
<div class=\"schirm-terminal\">\
    <div class=\"terminal-screen\">\
        <pre class=\"terminal-line-container\"></pre>\
    </div>\
    <pre class=\"terminal-app-container\"></pre>\
</div>\
";

    var self = this;

    var linesElement; // PRE element to render the terminal in line mode
    var appElement;   // PRE element to render the application mode

    var screen0 = 0; // offset from the first line to the current terminal line 0
    var appMode = false;
    var currentIframe;

    this.size = { lines: 0, cols: 0 };

    // IPC

    if (false) {
        var send = function(cmd) {
            console.log("schirmcommand" + JSON.stringify(cmd));
        };
        this.send = send;
    } else {
        var preOpenQueue = [];
        var send = function(cmd) {
            // enqueue all messages sent before the websocket is ready
            preOpenQueue.push(cmd);
        };
        self.send = send;

        var socket = new WebSocket(webSocketUrl);
        socket.onopen = function (event) {
            // send enqueued messages
            for (var i=0; i<preOpenQueue.length; i++) {
                socket.send(JSON.stringify(preOpenQueue[i]));
            }
            preOpenQueue = undefined;

            send = function(cmd) { socket.send(JSON.stringify(cmd)); };
            self.send = send;
        };

        socket.onmessage = function (event) {
            eval(event.data);
        }
    }

    // terminal sizing

    // Return the size of a single character in the given PRE element
    var getCharSize = function(preElement) {
        var specimen = document.createElement("span");
        specimen.innerHTML = "x";
        preElement.appendChild(specimen);

        var marginBorderHeight =
                (window.getComputedStyle(specimen, 'margin-top').value || 0) +
                (window.getComputedStyle(specimen, 'border-top').value || 0) +
                (window.getComputedStyle(specimen, 'border-bottom').value || 0) +
                (window.getComputedStyle(specimen, 'margin-bottom').value || 0);

        var marginBorderWidth =
                (window.getComputedStyle(specimen, 'margin-left').value || 0) +
                (window.getComputedStyle(specimen, 'border-left').value || 0) +
                (window.getComputedStyle(specimen, 'border-right').value || 0) +
                (window.getComputedStyle(specimen, 'margin-right').value || 0);

        var size = {width: specimen.offsetWidth + marginBorderWidth,
                    height: specimen.offsetHeight + marginBorderHeight};
        preElement.removeChild(specimen);
        return size;
    };

    // Return the size in lines and columns of the terminals PRE element
    var getTermSize = function(preElement) {
        var blockSize = getCharSize(preElement);
        var cols  = Math.floor(document.body.clientWidth/blockSize.width);
        // No idea why but the size reported by using offsetHeight in
        // getCharSize needs to be decremented by one to get the *real* size
        // of a char block in a pre element. Without this, the line
        // calculation will be inaccurate for large windows and will lead to
        // a few lines of trailing whitespace.
        var lines = Math.floor(document.body.clientHeight/(blockSize.height - 1));

        return { lines: lines, cols: cols };
    };

    // Determine and cache the height of a vertical scrollbar
    var vScrollBarHeight;
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

        if (vScrollBarHeight === undefined) {
            vScrollBarHeight = compute();
        }
        return vScrollBarHeight;
    };

    // Determine the new size of the currently active screen and
    // return it by sending JSON encoded mapping of the size to the
    // terminal emulator process
    this.resize = function() {
        self.size = getTermSize(linesElement);
        send({cmd:'resize',
              width:self.size.cols,
              height:self.size.lines});
    };

    // terminal render functions

    // adjust layout to 'render' empty lines at the bottom
    var adjustTrailingSpace = function() {
        if (linesElement.childNodes.length && ((linesElement.childNodes.length - screen0) <= self.size.lines)) {
            var historyHeight = linesElement.childNodes[screen0].offsetTop;
            // position the <pre> so that anything above the screen0 line is outside the termscreen client area
            linesElement.style.setProperty("top", -historyHeight);
            // set the termscreen div margin-top so that it covers all history lines (lines before line[screen0])
            linesElement.parentElement.style.setProperty("margin-top", historyHeight);
        }
    };
    this.adjustTrailingSpace = adjustTrailingSpace;

    var checkHistorySizePending = false;
    this.checkHistorySize = function() {
        // generate an remove_history event if necessary

        // only check and generate the remove_history event if there is
        // no event waiting to be processed
        if (!checkHistorySizePending) {
            var maxHistoryHeight = 10000; // in pixels
            var start = screen0;
            var historyHeight = linesElement.childNodes[start].offsetTop;

            if (historyHeight > maxHistoryHeight) {
                for (var i=0; i<start; i++) {
                    if ((historyHeight - linesElement.childNodes[i].offsetTop) < maxHistoryHeight) {
                        send({cmd:'removehistory',
                              n:i});
                        checkHistorySizePending = true; // change state: wait for the removeHistory response
                        return
                    }
                }
            }
        }
    };

    // remove all history lines from 0..n
    this.removeHistoryLines = function(n) {
        for (var i=0; i<n; i++) {
            linesElement.removeChild(linesElement.firstChild);
        }
        checkHistorySizePending = false;
    };

    this.setScreen0 = function(s0) {
        screen0 = s0;
        adjustTrailingSpace();
    };

    this.setLine = function(index, content) {
        linesElement.childNodes[index].innerHTML = content + "\n";
    };

    this.insertLine = function(index, content) {
        var span = document.createElement('span');
        span.innerHTML = content + "\n";
        if ((linesElement.children.length) <= index) {
            linesElement.appendChild(span);
        } else {
            linesElement.insertBefore(span, linesElement.childNodes[index]);
        }
        adjustTrailingSpace();
    };

    this.appendLine = function(content) {
        var span = document.createElement("span");
        span.innerHTML = content + "\n";
        linesElement.appendChild(span);
        adjustTrailingSpace();
    };

    this.removeLine = function(index) {
        linesElement.removeChild(linesElement.childNodes[index]);
        adjustTrailingSpace();
    };

    this.removeLastLine = function() {
      linesElement.removeChild(linesElement.lastChild);
      adjustTrailingSpace();
    };

    // clear all a lines and the history
    this.reset = function() {
        linesElement.innerHTML = "";
    };

    // iframe functions

    // insert an iframe 'line' before linenumber
    this.insertIframe = function(index, id, uri) {
        var div = document.createElement('div');
        linesElement.replaceChild(div, linesElement.childNodes[index]);

        var iframe = document.createElement('iframe');
        // todo: add seamless & sandbox="allow-scripts allow-forms" attributes
        iframe.name = id;
        iframe.id = id;
        div.appendChild(iframe);

        var newline = document.createElement('span');
        newline.innerHTML = "\n";
        div.appendChild(newline);

        term.currentIframe = iframe;

        // linemode: iframe grows vertically with content
        //           iframe is as wide as the terminal window
        iframe.style.width = '100%';

        // the iframe must have at least the height of a vertical
        // scrollbar otherwise, artifacts show up when animating the
        // inital resize of an iframe with vertically scrolled content
        iframe.style.minHeight = getVScrollbarHeight();

        adjustTrailingSpace();
        window.iframe = iframe; // keep the current iframe around for debugging

        // load the frame document
        iframe.src = uri;
    };

    // call .close on the iframe document.
    this.iframeCloseDocument = function() {
        // todo delete
    };

    // set the the current iframe document to null
    // so that we know whether we're in iframe mode or not
    this.iframeLeave = function() {
        currentIframe = null;
    };

    this.iframeResize = function(frameId, height) {
        var iframe = document.getElementById(frameId);
        iframe.style.height = height;
    };

    // begin to render lines in app mode (fullscreen without
    // scrollback)
    var applicationMode = function(enable) {
        //TODO: implement
        // if (appElement) {
        //     app.show(enable);
        //     lines.show(!enable);
        //     state.appmode = enable;
        //     fn.resize(state.size.lines, state.size.lines);
        // }
    };


    // init
    parentElement.innerHTML = termMarkup;
    linesElement = parentElement.getElementsByClassName('terminal-line-container')[0];
    appElement   = parentElement.getElementsByClassName('terminal-app-container')[0];
    self.resize();
};
