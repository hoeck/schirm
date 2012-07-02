
// Return the size of a single character in the given PRE element
function getCharSize(preElement) {
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
}

// Return the size in lines and columns
function getTermSize(preElement) {
  var blockSize = getCharSize(preElement);
  var cols  = Math.floor(document.body.clientWidth/blockSize.width);
  // No idea why but the size reported by using offsetHeight in
  // getCharSize needs to be decremented by one to get the *real* size
  // of a char block in a pre element. Without this, the line
  // calculation will be inaccurate for large windows and will lead to
  // a few lines of trailing whitespace.
  var lines = Math.floor(document.body.clientHeight/(blockSize.height - 1));

  return { lines: lines, cols: cols };
}

// Determine and cache the height of a vertical scrollbar
var __vscrollbarheight;
function getVScrollbarHeight() {
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
function vScrollbarRequired(el) {
  return el.scrollWidth > el.clientWidth;
}

function resizeIframe(iframe) {
  try {
    var doc = iframe.contentDocument.documentElement;
      if (doc) {
        var newHeight;
        if (vScrollbarRequired(doc)) {
          newHeight = doc.scrollHeight + getVScrollbarHeight();
        } else {
          newHeight = doc.scrollHeight;
        }
        iframe.style.height = newHeight;
      }
  } catch (e) { }
};

// rendering the terminal in normal mode
// linesElement:
// a PRE element holding the terminals lines
// each line is a span of nested spans for styles
var Lines = (function(linesElement, term) {

  var fn = {

    // pointer to the first terminal line
    screen0: 0,
    pendingRemoveHistory: false,

    init: function() { },

    show: function(enable) {
      linesElement.style.display = enable ? "block" : "none";
    },

    elementIndex: function(lineNumber) {
      return this.screen0 + lineNumber;
    },

    checkHistorySize: function() {
      // generate an remove_history event if necessary

      // only check and generate the remove_history event if there is
      // no event waiting to be processed
      if (!this.pendingRemoveHistory) {
        var maxHistoryHeight = 10000; // in pixels
        var start = this.screen0;
        var historyHeight = linesElement.childNodes[start].offsetTop;

        if (historyHeight > maxHistoryHeight) {
          for (var i=0; i<start; i++) {
            if ((historyHeight - linesElement.childNodes[i].offsetTop) < maxHistoryHeight) {
              console.log('removehistory' + i);
              this.pendingRemoveHistory = true; // change state: wait for the removeHistory response
              return
            }
          }
        }
      }
    },

    adjustTrailingSpace: function() {
      // adjust layout to 'render' empty lines at the bottom
      if (linesElement.childNodes.length && ((linesElement.childNodes.length - this.screen0) <= term.size.lines)) {
        var historyHeight = linesElement.childNodes[this.screen0].offsetTop;
        // position the <pre> so that anything above the screen0 line is outside the termscreen client area
        linesElement.style.setProperty("top", -historyHeight);
        // set the termscreen div margin-top so that it covers all history lines (lines before line[screen0])
        linesElement.parentElement.style.setProperty("margin-top", historyHeight);
      }
    },

    setScreen0: function(screen0) {
      this.screen0 = screen0;
      this.adjustTrailingSpace();
    },

    setLine: function(index, content) {
      linesElement.childNodes[index].innerHTML = content + "\n";
    },

    insertLine: function(index, content) {
      var span = document.createElement('span');
      span.innerHTML = content + "\n";
      if ((linesElement.children.length) <= index) {
        linesElement.appendChild(span);
      } else {
        linesElement.insertBefore(span, linesElement.childNodes[index]);
      }
      this.adjustTrailingSpace();
    },

    appendLine: function(content) {
      var span = document.createElement("span");
      span.innerHTML = content + "\n";
      linesElement.appendChild(span);
      this.adjustTrailingSpace();
    },

    removeLine: function(index) {
      linesElement.removeChild(linesElement.childNodes[index]);
      this.adjustTrailingSpace();
    },

    removeLastLine: function() {
      linesElement.removeChild(linesElement.lastChild);
      this.adjustTrailingSpace();
    },

    // remove all history lines from 0..n
    removeHistoryLines: function(n) {
      for (var i=0; i<n; i++) {
        linesElement.removeChild(linesElement.firstChild);
      }
      this.pendingRemoveHistory = false;
    },

    getSize: function() {
      return getTermSize(linesElement);
    },

    resize: function(oldLines, newLines) {
    },

    // clear all a lines and the history (
    reset: function() {
      linesElement.innerHTML = "";
    },

    // iframe functions
    insertIframe: function (index, id, uri) {
      // insert an iframe 'line' before linenumber
      // close the old iframe
      // TODO: this should be done in termscreen.py
      if (term.currentIframe) {
        try {
          term.currentIframe.contentDocument.close();
        } catch (e) { }
      }

      var div = document.createElement('div');
      linesElement.replaceChild(div, linesElement.childNodes[index]);

      var iframe = document.createElement('iframe');
      iframe.name = id;
      iframe.id = id;
      div.appendChild(iframe);

      // provide a means to send messages to the pty
      //iframe.contentWindow.schirmlog = function(msg) { console.log("frame" + id + " " + msg); };

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

      //iframe.resizeHandler = function() { resizeIframe(iframe); };
      this.adjustTrailingSpace();
      window.iframe = iframe; // keep the current iframe around for debugging

      // load the frame document
      iframe.src = uri;
    },

    // contentDocument.write content (a string) to the currentIframe and
    // resize it (vertically) if necessary
    iframeWrite: function (content) {
      var iframe = term.currentIframe;
      try {
        iframe.contentDocument.write(content);
      } catch (e) {
        iframe.contentDocument.open("text/html");
        iframe.contentDocument.write(content);
      }
      resizeIframe(iframe);
      this.adjustTrailingSpace();
    },

    // call .close on the iframe document.
    iframeCloseDocument: function() {
      var iframe = term.currentIframe;
      resizeIframe(iframe);
      this.adjustTrailingSpace();
      try {
        iframe.contentDocument.close();
        iframe.addEventListener('load', function() { resizeIframe(iframe); });
      } catch (e) { }
    },

    // set the the current iframe document to null
    // so that we know whether we're in iframe mode or not
    iframeLeave: function() {
      term.currentIframe = null;
    },
    
    iframeResize: function(frameId, height) {
      var iframe = document.getElementById(frameId);
      iframe.style.height = height;
    }
  };

  return fn;
});


// providing a character matrix without history most ncurses
// fullscreen applications seem using this, like midnight commander
var App = (function(appElement, term) {

  var fn = {

    init: function(lines) {
      linesElement.innerHTML = "";
      for (var i=0; i<lines; i++) {
         var span = document.createElement("span");
         linesElement.appendChild(span);
      }
    },

    show: function(enable) {
      appElement.style.display = enable ? "block" : "none";
    },

    elementIndex: function(lineNumber) {
      return lineNumber;
    },

    scrollToBottom: function() { },

    scrollPageUp: function() { },

    scrollPageDown: function() { },

    setLine: function(index, content) {
      appElement.childNodes[index].innerHTML = content + "\n";
    },

    insertLine: function(index, content) {
      var span = document.createElement('span');
      span.innerHTML = content + "\n";
      
      if (term.size.lines <= index) {
        appElement.appendChild(span);
        appElement.removeChild(appElement.firstChild);
      } else {
        appElement.insertBefore(span, appElement.childNodes[index]);
        appElement.removeChild(appElement.lastChild); // ?????
      }
    },

    appendLine: function(content) {
      appElement.removeChild(appElement.firstChild)
      var span = document.createElement("span");
      span.innerHTML = content + "\n";
      appElement.appendChild(span);
    },

    removeLine: function(index) {
      appElement.removeChild(appElement.childNodes[index]);
    },

    getSize: function() {
      return getTermSize(appElement);
    },

    // Resize the terminal space used to render the screen in
    // application mode
    resize: function(oldLines, newLines) {
    },

    reset: function() { // todo: should take lines, cols param
    },

    // iframe
    // TODO
    // insert iframe as large as the whole screen
    // or use a second gtk webview instead - might be safer & more robust
    insertIframe: function (linenumber, id, uri) {
      // close the old iframe
      // if (term.currentIframe) {
      //   term.currentIframe.contentDocument.close();
      // }

      // var div = document.createElement('div');
      // if (term.height <= linenumber) {
      //   linesElement.appendChild(div);
      // } else {
      //   linesElement.insertBefore(div, linesElement.childNodes[linenumber]);
      // }

      // var iframe = document.createElement('iframe');
      // div.appendChild(iframe);

      // var newline = document.createElement('span');
      // newline.innerHTML = "\n";
      // div.appendChild(newline);

      // term.currentIframe = iframe;
      // iframe.height = "1";
      // iframe.contentDocument.open("text/html");
    },

    // contentDocument.write content (a string) to the currentIframe and
    // resize it (vertically) if necessary
    iframeWrite: function(content) {
      var iframe = term.currentIframe;
      iframe.contentDocument.write(content);
    },

    iframeLeave: function(content) {
      term.currentIframe = null;
    }
  };

  return fn;

});

var iframe; // keep the current iframe around for debugging
var Term = function() {

  var state = {
    currentIframe: undefined,
    appmode: false,
    size: { lines: 24, cols: 80 } // initial size should be 0,0? or undefined?
  };

  var lines = Lines(document.getElementById('term'), state); // one screen to render lines + history
  var app = App(document.getElementById('app'), state); // the other for rendering a char matrix w/o history

  var fn = {

    getState: function() {
      return state;
    },

    getScreen: function() {
      return state.appmode ? app : lines;
    },

    // Determine the new size of the currently active screen and return
    // it by writing JSON encoded mapping of the size to console.log
    resizeHandler: function(event) {
      oldLines = state.size.lines;
      state.size = fn.getScreen().getSize();
      //fn.getScreen().resize(oldLines, state.size.lines); not required anymore
      // IPC
      console.log('schirm{"width":'+state.size.cols+',"height":'+state.size.lines+'}');
    },

    applicationMode: function(enable) {
      app.show(enable);
      lines.show(!enable);
      state.appmode = enable;
      fn.resize(state.size.lines, state.size.lines);
    },

    scrollToBottom: function() { fn.getScreen().scrollToBottom(); },
    scrollPageUp: function() { fn.getScreen().scrollPageUp(); },
    scrollPageDown: function() { fn.getScreen().scrollPageDown(); },

    setScreen0: function(index) { fn.getScreen().setScreen0(index); },

    setLine: function(index, content) { fn.getScreen().setLine(index, content); },
    insertLine: function(index, content) { fn.getScreen().insertLine(index, content); },
    appendLine: function(content) { fn.getScreen().appendLine(content); },
    removeLine: function(index) { fn.getScreen().removeLine(index); },
    removeLastLine: function() { fn.getScreen().removeLastLine(); },

    removeHistoryLines: function(n) { fn.getScreen().removeHistoryLines(n); },
    checkHistorySize: function() { fn.getScreen().checkHistorySize(); },

    insertIframe: function (index, iframeId, uri) { fn.getScreen().insertIframe(index, iframeId, uri); }, // TODO: create the uri!!!
    iframeWrite: function (content) { fn.getScreen().iframeWrite(content); },
    iframeCloseDocument: function() { fn.getScreen().iframeCloseDocument(); },
    iframeLeave: function() { fn.getScreen().iframeLeave(); },
    iframeResize: function(frameId, height) { fn.getScreen().iframeResize(frameId, height); },

    getSize: function() { return fn.getScreen().getSize(); },
    resize: function(oldLines, newLines) { fn.getScreen().resize(oldLines, newLines); },
    reset: function(lines) { fn.getScreen().reset(lines); },
    init: function(lines) { fn.getScreen().init(lines); }
  };

  return fn;
};
