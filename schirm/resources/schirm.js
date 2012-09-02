
// schirm client module (use within terminal iframes)

var schirm = (function(schirm) {

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

  // ask the iframes parent to resize the current iframe
  schirm.resize = function(height) {
    var bodyStyle = getComputedStyle(document.body);
    var bodyMargin = parseInt(bodyStyle.marginTop) + parseInt(bodyStyle.marginBottom);

    var vScrollbarHeight = 0;
    if (vScrollbarRequired(document.body)) {
      vScrollbarHeight = getVScrollbarHeight()
    }
    console.log(height);
    console.log(bodyMargin);
    console.log(vScrollbarHeight);
    var newHeight = height + bodyMargin + vScrollbarHeight;

    console.log("iframeresize"+newHeight); // IPC
  }

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
