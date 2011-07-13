#!/usr/bin/env python

import sys
import signal
import os
import time
import urllib
import threading
import simplejson

from webkit_wrapper import GtkThread, launch_browser, establish_browser_channel
import shellinabox

state = None
gtkthread = None
run = True

def stop():
    global run
    run = False

def quit():
    print "quitting"
    try:
        stop()
        os.kill(os.getpid(), 15)
        gtkthread.kill()
    except:
        pass


# navigation-request is deprecated
last_nav_request = None
def my_navigation_request_handler(view, frame, networkRequest):
    print "navigation-request", networkRequest.get_uri()
    global last_nav_request
    last_nav_request = (view, frame, networkRequest)
    return 0

last_resource_requested = None
def my_resource_requested_handler(view, frame, resource, request, response):
    print "resource-request-starting", request.get_uri()
    return 1

# browser.connect('console-message', my_console_message_handler)
def my_console_message_handler(view, msg, line, source_id, user_data):
    """
    webView : the object on which the signal is emitted
    message : the message text
    line : the line where the error occured
    source_id : the source id
    user_data : user data set when the signal handler was connected.
    """
    pass


def receive_handler(msg, pty):
    if msg.startswith("schirm"):
        d = simplejson.loads(msg[6:])

        # always set size
        w = d.get('width',0)
        h = d.get('height',0)
        if w and h:
            pty.set_size(int(w), int(h))

        if d.get('keys'):
            pty.write_keys(d.get('keys'))
    else:
        return None


def webkit_event_loop():

    pty = shellinabox.Pty()

    global run
    global gtkthread
    gtkthread = GtkThread()
      
    browser = gtkthread.invoke_s(launch_browser)
    receive, execute = establish_browser_channel(gtkthread, browser)

    # handle links
    #gtkthread.invoke(lambda : browser.browser.connect('navigation-requested', lambda view, frame, networkRequest: 0))
    #gtkthread.invoke(lambda : browser.connect_navigation_requested(my_navigation_request_handler))
    
    gtkthread.invoke(lambda : browser.connect('destroy', lambda *args, **kwargs: quit()))
    gtkthread.invoke(lambda : browser.connect('resource-request-starting', my_resource_requested_handler))

    global state
    state = dict(browser=browser, receive=receive, execute=execute)

    # load shellinabox
    file = os.path.abspath('root_page.html')
    #file = os.path.abspath("/var/www/index.html")
    #file = os.path.abspath("foo.html")
    uri = 'file://' + urllib.pathname2url(file)
    browser.open_uri(uri)

    t = threading.Thread(target=lambda : read_pty_loop(pty, execute))
    t.start()

    while run:
        msg = receive(block=True, timeout=1) # timeout to make waiting for events interruptible
        if msg:
            #print "received:", msg
            receive_handler(msg, pty)


def read_pty_loop(pty, execute):
    global run
    while run:
        #print "reading ...."
        response = pty.read()
        #print "read response:", len(response), "bytes, type:", type(response), '"' in response
        execute('''document.my_shellinabox.schirmBackendResponse("%s");''' % response)
        #execute("console.log([document.my_shellinabox.terminalWidth, document.my_shellinabox.terminalHeight]);")


def main():
    try:
        __IPYTHON__
        print "IPython detected, starting webkit loop in its own thread"
        t = threading.Thread(target=webkit_event_loop)
        t.start()
    except:
        webkit_event_loop()

    
if __name__ == '__main__':
    signal.signal(signal.SIGINT, lambda sig, stackframe: quit())
    signal.siginterrupt(signal.SIGINT, True)
    main()



# todo next:
# connect gtkthread.invoke(lambda : state['browser'].browser.connect('navigation-requested', lambda *args, **kwargs: False))
# to not follw links automatically


# don't follow links
#gtkthread.invoke(lambda : browser.browser.connect('navigation-requested', lambda view, frame, networkRequest: 0))


# webtty (http://code.google.com/p/webtty) - no full terminal support, does only work in IE (---)
# anyterm - technically the best but all C (-) -> hard to integrate (different plattforms??)
# web-shell, ajaxterm (http://antony.lesuisse.org/software/ajaxterm/) - python (+), updates always the whole screen (--) -> no scroll history, anyterm has no utf-9 support (-)
# shell-in-a-box - c (-), renders terminal in the browser, allows for fullscreen
