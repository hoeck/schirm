// Redesign of the Schirm API using a js object pattern
// goal: reuse this code to create embedded terminals

var SchirmTerminal = function(parentElement, termId) {
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
    var size = { lines: 0, cols: 0 };

    // IPC

    var sendCommand = function(cmd) {
        console.log(cmd);
    };

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
    var resizeHandler = function(event) {
        size = getTermSize(linesElement);
        sendCommand('schirm{"width":'+size.cols+',"height":'+size.lines+'}');
    };

    // terminal render functions

    // adjust layout to 'render' empty lines at the bottom
    var adjustTrailingSpace = function() {
        if (linesElement.childNodes.length && ((linesElement.childNodes.length - screen0) <= term.size.lines)) {
            var historyHeight = linesElement.childNodes[screen0].offsetTop;
            // position the <pre> so that anything above the screen0 line is outside the termscreen client area
            linesElement.style.setProperty("top", -historyHeight);
            // set the termscreen div margin-top so that it covers all history lines (lines before line[screen0])
            linesElement.parentElement.style.setProperty("margin-top", historyHeight);
        }
    };

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
                        sendCommand('removehistory' + i);
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

    this.setScreen0 = function(screen0) {
        screen0 = screen0;
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

    this.resize = function(oldLines, newLines) {
        // todo: remove
    };

    // clear all a lines and the history (
    this.reset = function() {
        linesElement.innerHTML = "";
    };

    // iframe functions

    // insert an iframe 'line' before linenumber
    this.insertIframe = function(index, id, uri) {
        var div = document.createElement('div');
        linesElement.replaceChild(div, linesElement.childNodes[index]);

        var iframe = document.createElement('iframe');
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
    resizeHandler();

    if (termId) {
        // we are an embedded terminal, enter the ajax loop
        self.termAjaxWorker = function() {
            var termXHR = new XMLHttpRequest();
            termXHR.open("GET", termId, true); // asnyc
            termXHR.onreadystatechange = function (event) {
                if (termXHR.readyState === 4) {
                    if (termXHR.status === 200) {
                        // evil eval:
                        var code = "function(term) {"+termXHR.responseText+"}(self);"
                        console.log("term"+termId+"evaling:"+code);
                        // TODO: use json-data to drive the terminal functions!
                        eval(code);
                        self.termAjaxWorker(); // send the next request
                        // TODO: exit this loop
                    } else {
                        console.log("Error", termXHR.statusText);
                    }
                }
            };
            termXHR.send(null);
        };
    }
};
