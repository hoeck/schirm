#!/usr/bin/env python

import os
import sys
import random
import time
import base64
from contextlib import contextmanager
INTRO = "\033R"
END = "\033Q"
SEP = "\033;"
EXIT = "\033x"

def enter():
    sys.stdout.write("".join((INTRO, 'enter', END)))

def leave():
    sys.stdout.write(EXIT)

def close():
    sys.stdout.write("".join((INTRO, 'close', END)))

@contextmanager
def html():
    try:
        enter()
        yield
    finally:
        leave()

def register_resource(path, name=None):
    if not name:
        _, name = os.path.split(path)
    sys.stdout.write("".join((INTRO, "register_resource", SEP, name, SEP)))
    with open(path, "rb") as f:
        sys.stdout.write(base64.b64encode(f.read()))
    sys.stdout.write(END)  

def respond(id, data):
    sys.stdout.write("".join((INTRO, "respond", SEP, name, SEP)))
    sys.stdout.write(base64.b64encode(data))
    sys.stdout.write(END)

def decode_request(input_stream):
    pass

def wait_for_requests(input_stream, handler, use_thread=False):
    #sys.stdin
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


        print """
<script type="text/javascript">

$(document).ready(function() {
console.log('fooo');
$.ajax("foobar", {type: 'POST', data: {'param': 'value'}});
});
</script>
"""

        print "</head><body>"
        #for x in range(random.randint(0,23)):
        #    print "<div>{}</div>".format(x)
        pprint_dict({'a':1, 'b':4, 'c':5, 'x':10, 'y':234234})
        print "</body></html>"
        close()

    finally:
        leave()
        #print "again plain term"

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

if __name__ == '__main__':
#    for x in range(1):
        #print "-----------------------------"
        #testIframeMode("iframe #{}".format(x))
    for x in range(1):
        testIframeModeHeight()
    #enterIframeMode()   
#    print "x:\033  \033 -----"

    # special input command (via stdin) in iframemode:
    #   - normal keyboard input is redirected to the webkit view
    #     except control characters??
    #   - ESC R <digits> ; <escaped-data> ESC Q
