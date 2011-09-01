#!/usr/bin/env python

import sys
import random

def enterIframeMode():
    sys.stdout.write("\033[21h");

def leaveIframeMode():
    sys.stdout.write("\033[21l");

def testIframeMode(s):
    #print "plain term"
    try:
        enterIframeMode()
        print "<h1>{}</h1>".format(s)
    finally:
        leaveIframeMode()
        #print "again plain term"

def testIframeModeHeight():
    #print "plain term"
    try:
        enterIframeMode()
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
    print '<tr><td>key</td><td>value</td>'
    switch = False
    for k,v in d.iteritems():
        print '<tr class="{clss}"><td>{key}</td><td>{val}</td>'.format(clss='odd' if switch else '', key=k,val=v)
        switch = not switch
    print '</table>'


if __name__ == '__main__':
    for x in range(1):
        #print "-----------------------------"
        #testIframeMode("iframe #{}".format(x))
        testIframeModeHeight()

