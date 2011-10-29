#!/usr/bin/env python

import os
import sys
import random
import time
import base64
import termios
import fcntl
from contextlib import contextmanager

from schirmclient import *


def testIframeModeHeight():
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
        print """
<html><head>
<script type="text/javascript" src="jquery.js"></script>
<script type="text/javascript">

$(document).ready(function() {
  $("#button").click(function() {
    $("#container").load("content", {data: $('#txt').attr('value')});
  });
});
</script>
</head><body>
<h3>ajax-demo</h3>
<input id="txt" length="30">
<div id="container"><input type="button" id="button" value="submit"/></div>
</body></html>
"""
        close()
        # wait for the requst
        req = read_next_request()
        rid, ver, method, path = req[:4]
        if method == 'POST' and path.startswith('/content'):
            data = req[-1][5:]
            content = "<h2>clicked</h2><br><h2>{}</h2>".format(data)
            respond(rid,
                    "\n".join(("{} 200 OK".format(ver),
                               "Content-Type: text/html",
                               "Content-Length: {}".format(len(content)),
                               "\r",
                               content)))
    finally:
        leave()


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


def frame_in_frame_test():
    with frame():
#        register_resource("bla.html")
#        register_resource("x.gif")
#        register_resource("jquery-1.6.2.js", "jquery.js")
#<iframe src="http://www.heise.de">
#         print """
# <html><head>
# <script type="text/javascript" src="jquery.js">
# <script>
# 
# </script>
# </head><body>
# <h3>empty</h3>
# <span>test</span><img src=\"x.gif\">
# </body></html>
# """
        close()
        # execute("""console.log("execute_window: " + window);""")
        # execute("""console.log("execute_document: " + document);""")
        # execute("""value = "value set"; console.log("value: " + value); console.log("window.value: " + window.value);""")
        # execute("""console.log("value again: " + value);""")
        time.sleep(3)
        execute("""console.log("iframe-exec")""")
        eval("""console.log("iframe-eval")""")
        eval("""console.log("iframe-eval-2")""")
        execute("""console.log("iframe-exec-2")""")

if __name__ == '__main__':
    frame_in_frame_test()
    #ajax_demo()

