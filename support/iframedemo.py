#!/usr/bin/env python

import os
import sys
import cgi
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
        print "foo"
        close()
        # execute("""console.log("execute_window: " + window);""")
        # execute("""console.log("execute_document: " + document);""")
        # execute("""value = "value set"; console.log("value: " + value); console.log("window.value: " + window.value);""")
        # execute("""console.log("value again: " + value);""")
        #time.sleep(1)
        execute("""console.log("iframe-exec")""")
        eval("""console.log("iframe-eval")""")
        eval("""1+2""")
        #time.sleep(1)
    #x = read_next()
    #print x



######### table

css = """
html {
}

body {
  margin:0px;
}

div.tablecontainer {
  float:left;
  border-radius: 1ex;
  background: none repeat scroll 0 0 #eaeaea;
  border-style: solid;
  border-width: 0.3ex;
  border-color: #ccc;
  padding: 0.0ex;
  overflow:hidden;
}

table {
    display:none;
    border-spacing: 0px;
    border-collapse: collapse;
    font-family: "Lucida Sans Unicode","Lucida Grande",Sans-Serif;
    font-size: 12px;
    text-align: left;
    margin: 0 0 0.5ex 0;
}
table th {
    border-bottom: 2px solid #6678B1;
    color: #003399;
    font-size: 14px;
    font-weight: normal;
    padding: 3px 2px;
}
table td {
    color: #558;
    padding: 0.5ex;
}

table tbody tr:hover td {
    color: #008;
    background-color: #c9c9f0;
}

table tr:nth-child(even) {
    background-color: #ffffff;
}
"""

def table(cols, header, rows):
    tmpl = """
    <html>
      <head>
        <style type="text/css">
          {css}
        </style>
      </head>
      <body>
        <div class="tablecontainer">
        <table>
          <thead>
            <tr>
              {header}
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
<button onclick="show();">show</button>
</div>
<script type="text/javascript" src="/schirm.js"></script>
<script type="text/javascript">
function show() {{
  document.querySelector("table").style.display = 'block';


  schirm.resize(document.querySelector(".tablecontainer").getBoundingClientRect().height);
}}
</script>
      </body>
    </html>
    """

    res = []
    for r in rows:
        #res.append('<tr{}>'.format(' class="{}"'.format(" ".join(classes)) if classes else ''))
        res.append('<tr>')
        res.extend('<td>{}</td>'.format(cgi.escape(str(r[c]))) for c in cols)
        res.append('</tr>')

    return tmpl.format(css=css,
                       header="".join("<th>{}</th>".format(cgi.escape(header[c]))
                                      for c
                                      in cols),
                       rows="".join(res))

def table_test():

    rows = [{'column 1': 'X'*20,
             'column 2': 'Y'*20,
             'column 3': 'Z'*20,
             'column 4': 'A'*20}] * 3
    header = {'column 1': 'C1',
              'column 2': 'C2',
              'column 3': 'C3',
              'column 4': 'C4'}
    cols = ['column 1','column 2','column 3','column 4']
    with frame():
        print table(cols, header, rows)


def test_websocket():
    with frame():
        register_resource("misc/jquery-1.6.2.js", "jquery.js")
        print """
<link rel="stylesheet" href="schirm.css" type="text/css">
<script type="text/javascript" src="schirm.js"></script>

<script type="text/javascript" src="jquery.js"></script>
<script type="text/javascript">

schirm.onmessage = function(data) { console.log(data); };

$(function() {
        schirm.onmessage = function(data) {
            $('h2').text(data);
            schirm.resize($('h2').get(0));
        }
        // websocket
        schirm.send('foo');
});
</script>
<div><h2>WebSocket</h2></div>
"""
        close()
        send('bar');
        req = read_next()
    print req, req

if __name__ == '__main__':
    test_websocket()
    #frame_in_frame_test()
    #ajax_demo()
    #table_test()

