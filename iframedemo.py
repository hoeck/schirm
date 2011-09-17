#!/usr/bin/env python

import os
import sys
import random
import time

def enterIframeMode():
    sys.stdout.write("\033Renter\033Q")

def leaveIframeMode():
    sys.stdout.write("\033x\033x")

def testIframeMode(s):
    #print "plain term"
    try:
        enterIframeMode()
        print "<h1>{}</h1>".format(s)
    finally:
        leaveIframeMode()
        #print "again plain term"

def register_resource(path):
    _, name = os.path.split(path)

    sys.stdout.write("\033Rregister_resource\033;{}\033;".format(name))
    with open(path, "rb") as f:
        sys.stdout.write(f.read().replace("\033", "\033\033"))
    sys.stdout.write("\033Q")   

def testIframeModeHeight():
    #print "plain term"
    try:
        enterIframeMode()
        register_resource("x.gif")
        print "<html><head>"
        print '<style type="text/css">'
        print 'body { margin:0px; } tr.odd { background-color: #dddddd; }'
        print '</style>'
        print "</head><body>"
        #for x in range(random.randint(0,23)):
        #    print "<div>{}</div>".format(x)
        pprint_dict({'a':1, 'b':4, 'c':5, 'x':10, 'y':234234})
        print "</body></html>"
    finally:
        leaveIframeMode()
        #print "again plain term"

def pprint_dict(d):
    print '<table>'
    print '<tr><td>key</td><td>value</td><td>image</td></tr>'
    switch = False
    for k,v in d.iteritems():
        print '<tr class="{clss}"><td>{key}</td><td>{val}</td><td><img src="x.gif"/></td></tr>'.format(clss='odd' if switch else '', key=k,val=v)
        switch = not switch
        #time.sleep(1)
    print '</table>'

if __name__ == '__main__':
#    for x in range(1):
        #print "-----------------------------"
        #testIframeMode("iframe #{}".format(x))
    testIframeModeHeight()
    #enterIframeMode()   
#    print "x:\033  \033 -----"
    



    # special input command (via stdin) in iframemode:
    #   - normal keyboard input is redirected to the webkit view
    #     except control characters??
    #   - ESC R <digits> ; <escaped-data> ESC Q
