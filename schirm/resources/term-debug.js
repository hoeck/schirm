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
    var input = document.getElementById('key');
    input.onclick = function() {
        send({name:'keypress', key:{string:'a'}});
    };
};
