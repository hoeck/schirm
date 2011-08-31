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
        for x in range(random.randint(0,23)):
            print "<div>{}</div>".format(x)
    finally:
        leaveIframeMode()
        #print "again plain term"


if __name__ == '__main__':
    for x in range(100):
        print "-----------------------------"
        #testIframeMode("iframe #{}".format(x))
        testIframeModeHeight()

