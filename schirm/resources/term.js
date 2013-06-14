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
    <pre class=\"terminal-alt-container\"></pre>\
    <div class=\"terminal-alt-iframe-container\"></div>\
</div>\
";
    var webSocketUrl = "ws://termframe.localhost"

    var self = this;

    var linesElement; // PRE element to render the terminal in line mode
    var altElement;   // PRE element to render the alternative buffer
    var altIframeContainer; // DIV element to render fullscreen iframes in the alternative buffer mode

    var screen0 = 0; // offset from the first line to the current terminal line 0
    var altBufEnabled = false;
    this.screen; // the current screen object which implements drawing methods for alt or line mode

    this.size = { lines: 0, cols: 0 };

    // keep the current iframe around for debugging
    this.iframe = undefined;

    // IPC (via self.send())
    var preOpenQueue = [];
    var send = function(msg) {
        // enqueue all messages sent before the websocket is ready
        preOpenQueue.push(msg);
    };
    self.send = send;

    var socket = new WebSocket(webSocketUrl);
    socket.onopen = function (event) {
        // send enqueued messages
        for (var i=0; i<preOpenQueue.length; i++) {
            socket.send(JSON.stringify(preOpenQueue[i]));
        }
        preOpenQueue = undefined;

        send = function(msg) { socket.send(JSON.stringify(msg)); };
        self.send = send;
    };

    socket.onmessage = function (event) {
        eval(event.data);
        self.screen.autoScroll();
    }

    // focus

    self.setFocus = function(focus) {
        self.send({name:'focus', msg:{focus:!!focus}});
    };

    // scroll
    self.scroll = function(how) {
        if (how === 'page-up') {
            window.scrollBy(0, window.innerHeight * -0.95);
        } else if (how === 'page-down') {
            window.scrollBy(0, window.innerHeight * 0.95);
        } else if (how === 'top') {
            window.scrollTo(0, 0);
        } else if (how === 'bottom') {
            window.scrollTo(0, 9999999999999);
        }
    };

    // key handling

    // map browser key codes to Gtk key names used in schirm
    // see termkey.py
    var knownKeys = {
        33: 'Page_Up',
        34: 'Page_Down',
        35: 'End',
        36: 'Home',
        45: 'Insert',
        46: 'Delete',

        37: 'Left',
        38: 'Up',
        39: 'Right',
        40: 'Down',

        32: 'Space',
        8:  'BackSpace',
        9:  'Tab',
        13: 'Enter',
        27: 'Esc',

        112: 'F1',
        113: 'F2',
        114: 'F3',
        115: 'F4',
        116: 'F5',
        117: 'F6',
        118: 'F7',
        119: 'F8',
        120: 'F9',
        121: 'F10',
        122: 'F11',
        123: 'F12'
    };

    var sendKeyFn = function(keyname) {
        return function(key) {
            key.name = keyname;
            self.send({name:'keypress', msg:{key:key}});
        }
    };

    var getKeyChordString = function(key) {
        var a = [];
        if (key.shift) { a.push('shift'); }
        if (key.control) { a.push('control'); }
        if (key.alt) { a.push('alt'); }
        if (key.name) {
            a.push(key.name.toLowerCase());
        } else {
            a.push(String.fromCharCode(key.code).toLowerCase());
        }
        return a.join('-');
    };

    var todoFn = function() { return function() { return true }; };
    var chords = {
        // essential shortcuts
        'shift-page_up':   function() { self.scroll('page-up');   return True; },
        'shift-page_down': function() { self.scroll('page-down'); return True; },
        'shift-home':      function() { self.scroll('top');       return True; },
        'shift-end':       function() { self.scroll('bottom');    return True; },

        // paste xselection
        'shift-insert': function() { send({name:'paste_xsel'}); },

        // use the browser search
        'control-f':  function() { return false; },

        // browsers have space and shift-space bound to scroll page down/up
        'space': function() { self.send({name:'keypress', msg:{key:{string: ' '}}}); return true; },
        'shift-space': function() { self.send({name:'keypress', msg:{key:{string:' ', shift:true}}}); return true; }
    }

    var handleKeyDown = function(key) {
        var keyChordString = getKeyChordString(key);

        var handler = chords[keyChordString];
        if (handler) {
            return handler();
        }

        // catch (control|alt)-* sequences
        var asciiA = 65;
        var asciiZ = 90;
        if ((key.control || key.alt) && (key.code >= asciiA) && (key.code <= asciiZ)) {
            key.name = String.fromCharCode(key.code);
            self.send({name:'keypress', msg:{key:key}});
            return true;
        }

        // special keys
        if (key.name) {
            self.send({name:'keypress', msg:{key:key}});
            return true;
        }

        return false
    }

    // key events
    if (true) {
        var keyDownProcessed;
        window.onkeydown = function(e) {
            var key = {'name':knownKeys[e.keyCode],
                       'code':e.keyCode,
                       'string': '',
                       'shift': e.shiftKey,
                       'alt':e.altKey,
                       'control':e.ctrlKey};
            if (handleKeyDown(key)) {
                keyDownProcessed = true;
                return false;
            } else {
                keyDownProcessed = false;
                return true;
            }
        };
        window.onkeypress = function(e) {
            var key = {'name':undefined,
                       'string': String.fromCharCode(e.charCode),
                       'shift': e.shiftKey,
                       'alt':e.altKey,
                       'control':e.controlKey};
            if (key.string && !keyDownProcessed) {
                self.send({name:'keypress', msg:{key:key}});
                return true;
            } else {
                return false;
            }
        };

        window.onkeyup = function(e) {
            keyDownProcessed = true;
        };
    }

    // terminal sizing

    // Return the size of a single character in the given PRE element
    var getCharSize = function(preElement) {
        var specimen = document.createElement("span");
        specimen.innerHTML = "X";
        preElement.appendChild(specimen);

        // gapsize between lines, required for an accurate lines
        // computation, seems to depend on the selected font.
        var gapSpecimen = document.createElement("span");
        gapSpecimen.innerHTML = "X<br>X";
        preElement.appendChild(gapSpecimen);

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

        var width = specimen.offsetWidth + marginBorderWidth;
        var height = specimen.offsetHeight + marginBorderHeight;
        var gap = gapSpecimen.offsetHeight + marginBorderHeight - (height * 2);

        preElement.removeChild(specimen);
        preElement.removeChild(gapSpecimen);

        return {width: width, height: height, gap: gap};
    };

    // Return the size in lines and columns of the terminals PRE element
    var getTermSize = function(preElement) {
        var blockSize = getCharSize(preElement);
        var cols  = Math.floor(document.body.clientWidth/blockSize.width);
        var lines = Math.floor(document.body.clientHeight/(blockSize.height + blockSize.gap));

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

    var LineScreen = function() {
        // Determine the new size of the currently active screen and
        // return it by sending JSON encoded mapping of the size to the
        // terminal emulator process
        this.resize = function() {
            self.size = getTermSize(linesElement);
            send({name:'resize',
                  msg:{width:self.size.cols,
                       height:self.size.lines}});
        };

        // AutoScroll
        // automatically keep the bottom visible unless the user actively scrolls to the top
        var autoScrollActive = true;
        var autoScrollActivationAreaHeight = 10;
        var autoScrollLastHeight;

        // should be bound to terminal scroll events to deactivate
        // autoScroll if user scrolls manually
        this.checkAutoScroll = function() {
            if (autoScrollLastHeight == parentElement.scrollHeight) {
                // Whenever the user scrolls withing
                // autoScrollActivationAreaHeight pixels to the bottom,
                // automatically keep bottom content visible (==
                // scroll automatically)
                if ((parentElement.scrollTop + parentElement.clientHeight) > (parentElement.scrollHeight - autoScrollActivationAreaHeight)) {
                    autoScrollActive = true;
                } else {
                    autoScrollActive = false;
                }
            } else {
                // scroll event had been fired as result of adding lines
                // to the terminal and thus increasing its size, do not
                // deactivate autoscroll in that case
                autoScrollLastHeight = parentElement.scrollHeight;
            }
        }

        var autoScroll = function() {
            if (autoScrollActive) {
                // scroll to the bottom
                parentElement.scrollTop = parentElement.scrollHeight - parentElement.clientHeight;
            }
        };
        this.autoScroll = autoScroll;

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
            autoScroll();
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
                                  msg:{n:i}});
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
            linesElement.insertBefore(span, linesElement.childNodes[index]);
        };

        this.appendLine = function(content) {
            var span = document.createElement("span");
            span.innerHTML = content + "\n";
            linesElement.appendChild(span);
        };

        this.removeLine = function(index) {
            linesElement.removeChild(linesElement.childNodes[index]);
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
            iframe.addEventListener('webkitTransitionEnd', autoScroll, false);

            // todo: add seamless & sandbox="allow-scripts allow-forms" attributes
            iframe.name = id;
            iframe.id = id;
            div.appendChild(iframe);

            var newline = document.createElement('span');
            newline.innerHTML = "\n";
            div.appendChild(newline);

            // keep the current iframe around for debugging
            term.iframe = iframe;

            // linemode: iframe grows vertically with content
            //           iframe is as wide as the terminal window
            iframe.style.width = '100%';

            // the iframe must have at least the height of a vertical
            // scrollbar otherwise, artifacts show up when animating the
            // inital resize of an iframe with vertically scrolled content
            iframe.style.minHeight = getVScrollbarHeight();
            iframe.style.height = getVScrollbarHeight();

            adjustTrailingSpace();

            // load the frame document
            iframe.src = uri;

            iframe.focus();
        };

        // called when entering plain terminal mode
        this.iframeLeave = function() {
            window.focus();
        };

        //
        this.iframeResize = function(frameId, height) {
            var iframe = document.getElementById(frameId);
            if (height === 'fullscreen') {
                iframe.style.height = "100%";
            } else {
                iframe.style.height = height;
            }
            autoScroll();
        };
    }

    // screen render interface of the alternative buffer:
    // no scrollback, thus no autoscroll and switching to iframe mode
    // always uses a fullscreen iframe
    var AltScreen = function() {
        this.resize = function() {
            // get the size from the line element by temporarily switching buffer mode
            self.altBufferMode(false);
            self.altBufferMode(true);
        };

        this.setLine = function(index, content) {
            altElement.childNodes[index].innerHTML = content + "\n";
        };

        this.insertLine = function(index, content) {
            var span = document.createElement('span');
            span.innerHTML = content + "\n";
            altElement.insertBefore(span, altElement.childNodes[index]);
        };

        this.appendLine = function(content) {
            var span = document.createElement("span");
            span.innerHTML = content + "\n";
            altElement.appendChild(span);
        };

        this.removeLine = function(index) {
            altElement.removeChild(altElement.childNodes[index]);
        };

        // clear all a lines and the history
        this.reset = function() {
            altElement.innerHTML = "";
        };

        // iframes
        this.insertIframe = function(index, id, uri) {
            // ignore the index, always create fullscreen iframes
            altIframeContainer.innerHTML = "";
            altIframeContainer.style.display = "block";
            altElement.style.display = "none";

            var iframe = document.createElement('iframe');

            // todo: add seamless & sandbox="allow-scripts allow-forms" attributes
            iframe.name = id;
            iframe.id = id;
            altIframeContainer.appendChild(iframe);

            // keep the current iframe around for debugging
            term.iframe = iframe;

            // todo: or use absolute positioning???
            iframe.style.width = '100%';
            iframe.style.height = '100%';

            // load the frame document
            iframe.src = uri;

            iframe.focus();
        };

        // back to plain terminal emulation (still in altbuffer mode)
        this.iframeLeave = function() {
            altElement.style.display="block";
            altIframeContainer.style.display = "none";
            altIframeContainer.innerHTML = ""; // destroy the iframe
            window.focus();
        };

        this.iframeResize = function(frameId, height) {
            // alt buffer mode iframes are always fullscreen
        };

        this.autoScroll = function() {
            // fullscreen - no scrolling required
        };
    }

    // select a substring on a line
    var selectSubLine = function(lineSpan, startIdx, endIdx) {
        var s = document.getSelection();
        var r = document.createRange();

        var spanStart = 0;
        var spanEnd = undefined;
        for (var i=0; i<lineSpan.children.length; i++) {
            var currentChild = lineSpan.children[i];
            spanEnd = spanStart + currentChild.childNodes[0].length;

            if ((spanStart <= startIdx) && (startIdx < spanEnd)) {
                r.setStart(currentChild.childNodes[0], startIdx - spanStart);
            }
            if ((spanStart <= startIdx) && (endIdx <= spanEnd)) {
                r.setEnd(currentChild.childNodes[0], endIdx - spanStart);
            }
            spanStart = spanEnd;
        }
        s.removeAllRanges();
        s.addRange(r);
    };

    // compute the boundaries of the word at idx
    var wordBoundaries = function(string, idx) {
        var wordCharsRegex = /[-,.\/?%&#:_~A-Za-z0-9]/;
        // find the beginning of the 'word'
        for (var wordStart=idx;
             wordStart>=0 && wordCharsRegex.test(string[wordStart]);
             wordStart--) { };

        for (var wordEnd=idx;
             wordEnd<string.length && wordCharsRegex.test(string[wordEnd]);
             wordEnd++) { };

        return {start:wordStart+1, end:wordEnd};
    }


    // line screen and alternative screen setup

    var lineScreen = new LineScreen();
    var altScreen = new AltScreen();
    self.screen = lineScreen;

    // render lines and iframes in app mode (fullscreen without
    // scrollback)
    this.altBufferMode = function(enable) {
        if (enable) {
            // always call resize on the lineScreen so that both
            // buffers use the same dimensions, even though the
            // altScreen could be larger because it does not need a
            // scrollbar
            lineScreen.resize();
            altElement.style.display = "block";
            linesElement.parentElement.style.display = "none";
            self.screen = altScreen;
        } else {
            altElement.style.display = "none";
            linesElement.parentElement.style.display = "block";
            self.screen = lineScreen;
            lineScreen.resize();
        }
    };

    this.resize = function() {
        self.screen.resize();
    }

    // init
    parentElement.innerHTML = termMarkup;
    linesElement = parentElement.getElementsByClassName('terminal-line-container')[0];
    altElement   = parentElement.getElementsByClassName('terminal-alt-container')[0];
    altIframeContainer = parentElement.getElementsByClassName('terminal-alt-iframe-container')[0];
    self.resize();

    // debug
    this.linesElement = linesElement;
    this.altElement = altElement;

    // focus
    window.onfocus = function() { self.setFocus(true); };
    window.onblur  = function() { self.setFocus(false); };
    self.setFocus(document.hasFocus());

    // adaptive autoScroll
    window.onscroll = self.checkAutoScroll;

    // click handler to select words
    linesElement.addEventListener('dblclick', function(e) {
            if (e.target.tagName === 'SPAN' || e.target.parentElement === 'SPAN') {
                var line = e.target.parentElement;
                var relPos = e.clientX / line.offsetWidth;
                var text = line.innerText;
                var idx = Math.round(text.length * relPos);
                var boundaries = wordBoundaries(text, idx);
                selectSubLine(line, boundaries.start, boundaries.end);
            }
            return true;
        });
};
