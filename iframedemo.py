#!/usr/bin/env python

import os
import sys
import random
import time
import base64
import termios
from contextlib import contextmanager

ESC = "\033"
INTRO = "\033R"
END = "\033Q"
SEP = "\033;"
EXIT = "\033x"

def echo_on():
    new = termios.tcgetattr(sys.stdin)
    new[3] = new[3] | termios.ECHO # lflags
    termios.tcsetattr(sys.stdin,
                      termios.TCSANOW,
                      new)

def echo_off():
    new = termios.tcgetattr(sys.stdin)
    new[3] = new[3] & ~termios.ECHO # lflags
    termios.tcsetattr(sys.stdin,
                      termios.TCSANOW,
                      new)

def enter():
    """
    Enter the frame mode.
    """
    sys.stdout.write("".join((INTRO, 'enter', END)))
    sys.stdout.flush()

def leave():
    """
    Get back to normal terminal mode.
    """
    sys.stdout.write(EXIT)
    sys.stdout.flush()

def close():
    """
    If in frame mode, close the current document (triggering document.load events).
    Any subsequent writes to stdout reopen and clear the current document again.
    """
    sys.stdout.write("".join((INTRO, 'close', END)))
    sys.stdout.flush()

@contextmanager
def frame():
    try:
        enter()
        yield
    finally:
        leave()

def register_resource(path, name=None):
    if not name:
        _, name = os.path.split(path)
    sys.stdout.write("".join((INTRO, "register_resource", SEP, base64.b64encode(name), SEP)))
    with open(path, "rb") as f:
        sys.stdout.write(base64.b64encode(f.read()))
    sys.stdout.write(END)  

def respond(rid, data):
    sys.stdout.write("".join((INTRO, "respond", SEP, rid, SEP)))
    sys.stdout.write(base64.b64encode(data))
    sys.stdout.write(END)

def debug(data):
    sys.stdout.write("".join((INTRO, "debug", SEP)))
    sys.stdout.write(base64.b64encode(data))
    sys.stdout.write(END)

def decode_request(input_stream):
    pass

def read_next_request():
    req = []
    buf = []
    state = None
    #print '<pre>'
    while 1:
        ch = sys.stdin.read(1)
        #print 'ESC' if ch == '\033' else ch
        if state == 'esc':
            if ch == "Q":
                req.append(base64.decodestring("".join(buf)))
                return req
            elif ch == ';':
                req.append(base64.decodestring("".join(buf)))
                buf = []
                state = 'arg'
            elif ch == 'R':
                state = 'arg'
                req = []
                buf = []
            else:
                raise Exception("Illegal escape sequence in input.")
        elif state == 'arg':
            if ch == ESC:
                state = 'esc'
            else:
                buf.append(ch)
        elif state == None:
            if ch == ESC:
                state = 'esc'
            else:
                # raise Exception("Ignoring input: " + str(ch))
                pass
        #debug("{} ({}) state: {}".format(ch, ord(ch), state))


def serve_requests(input_stream, handler, use_thread=False):
    pass


def testIframeModeHeight():
    #print "plain term"
    try:
        enter()
        register_resource("x.gif")
        register_resource("jquery-1.6.2.js", "jquery.js")
        print "<html><head>"
        print '<style type="text/css">'
        print 'body { margin:0px; } tr.odd { background-color: #dddddd; }'
        print '</style>'
        print '<script type="text/javascript" src="jquery.js">'
        print '</script>'
        print "</head><body>"
        #for x in range(random.randint(0,23)):
        #    print "<div>{}</div>".format(x)
        pprint_dict({'a':1, 'b':4, 'c':5, 'x':10, 'y':234234})
        print "</body></html>"
        close()
        try:
            foobar()
        except:
            print "<pre>"
            import traceback
            traceback.print_exc()
            print "</pre>"
    finally:
        leave()
        #print "again plain term"


def ajax_demo():
    req = None
    try:
        enter()
        register_resource("jquery-1.6.2.js", "jquery.js")
        print "<html><head>"
        print '<script type="text/javascript" src="jquery.js"></script>'
        print """
<script type="text/javascript">

$(document).ready(function() {
  $("#butt").click(function() {
    $("#container").load("content");
  });
});
</script>
"""
        print "</head><body>"
        print "<h3>ajax-demo</h3>"
        print '<div id="container"><input type="button" id="butt" value="click me"/></div>'
        print "</body></html>"
        print "    "
        #return
        close()
        req = read_next_request()
        rid, ver, method, path = req[:4]
        if method == 'GET' and path == '/content':
            content = "<h2>filled</h2>"
            respond(rid,
                    "\n".join(("{} 200 OK".format(ver),
                               "Content-Type: text/html",
                               "Content-Length: {}".format(len(content)),
                               "\r",
                               content)))
    finally:
        leave()
        #print req


def pprint_dict(d):
    print '<table>'
    print '<tr><td>key</td><td>value</td><td>image</td></tr>'
    switch = False
    i = 99
    for k,v in d.iteritems():
        print '<tr class="{clss}"><td>{key}</td><td>{val}</td><td><img src="x.gif"/></td></tr>'.format(clss='odd' if switch else '', key=k,val=v)
        switch = not switch
        i += 1
        if i == 3:
            0/0
        #time.sleep(2)
    print '</table>'


def echotest2():
    enter()
    register_resource("x.gif")
    #register_resource("jquery-1.6.2.js", "jquery.js")
    print "<span>test</span><img src=\"x.gif\">"
    close()
    leave()

if __name__ == '__main__':
#    for x in range(1):
        #print "-----------------------------"
        #testIframeMode("iframe #{}".format(x))
    #for x in range(1):
    #    testIframeModeHeight()
    #enterIframeMode()   
#    print "x:\033  \033 -----"

    # special input command (via stdin) in iframemode:
    #   - normal keyboard input is redirected to the webkit view
    #     except control characters??
    #   - ESC R <digits> ; <escaped-data> ESC Q

    #ajax_demo()
    echotest2()
