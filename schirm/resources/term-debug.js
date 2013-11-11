// schirm debug terminal
// connects to the schirm websocket and prints all received messages

var SchirmTerminal = function(parentElement, termId) {

    var socket = new WebSocket('ws://'+window.location.host);
    var markup = "<div class=\"messages-container\"></div> \
                  <div><input type=button id=key value=send></div>";
    var messagesContainer;

    // receiving messages
    var onmessageQueue = []
    socket.onmessage = function (event) {
        var msgLine = document.createElement('div');
        msgLine.innerText = event.data;
        messagesContainer.appendChild(msgLine);
    };

    var send = function(msg) {
        console.log("SEND", msg);
        socket.send(JSON.stringify(msg));
    };

    // init
    parentElement.innerHTML = markup;
    messagesContainer  = parentElement.getElementsByClassName("messages-container")[0];

    // debugkeypresses
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
        'space': function() { send({name:'keypress', key:{string: ' '}}); return true; },
        'shift-space': function() { send({name:'keypress', key:{string:' ', shift:true}}); return true; }
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
            send({name:'keypress', key:key});
            return true;
        }

        // special keys
        if (key.name) {
            send({name:'keypress', key:key});
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
                send({name:'keypress', key:key});
                return true;
            } else {
                return false;
            }
        };

        window.onkeyup = function(e) {
            keyDownProcessed = true;
        };
    }

    // var input = document.getElementById('key');
    // input. = function() {
    //     send({name:'keypress', key:{string:'a'}});
    // };
};
