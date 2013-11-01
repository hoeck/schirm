// schirm debug terminal
// connects to the schirm websocket and prints all received messages

var SchirmTerminal = function(parentElement, termId) {

    var socket = new WebSocket('ws://'+window.location.host);
    var markup = "<div class=\"messages-container\"></div>";
    var messagesContainer;

    // receiving messages
    var onmessageQueue = []
    socket.onmessage = function (event) {
        var msgLine = document.createElement('div');
        msgLine.innerText = event.data;
        messagesContainer.appendChild(msgLine);
    };

    // init
    parentElement.innerHTML = markup;
    messagesContainer  = parentElement.getElementsByClassName("messages-container")[0];
}
