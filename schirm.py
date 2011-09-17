#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import signal
import os
import time
import urllib
import threading
import simplejson

from webkit_wrapper import GtkThread, launch_browser, establish_browser_channel, install_key_events
from promise import Promise
import webserver
# import shellinabox

import term

import gtk # for key handler

state = None
gtkthread = None
run = True

def running():
    global run
    return run

def stop():
    global run
    run = False

def quit():
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
    global last_resource
    global last_frame
    global last_request
    last_resource = resource
    last_frame = frame
    last_request = request

    #if request.get_uri().startswith("schirm://"):
    #    print "schirm-request!!"
    #print "request for:", request.get_uri()

    return 0


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
        w = d.get('width')
        h = d.get('height')

        if w and h:
            #pty.set_size(int(h), int(w))
            pty.resize(int(h), int(w))

        return True
    else:
        return False # not handled

def keypress_cb(widget, event):
    print "keypress:",event.time, event.keyval, event.string, event.string and ord(event.string)

def handle_keypress(event, pty):
    """
    Map gtk keyvals/strings to terminal keys.
    """
    # KEY_PRESS
    # KEY_RELEASE            time
    #                        state
    #                        keyval
    #                        string
    name = gtk.gdk.keyval_name(event.keyval)
    key = pty.map_key(name)
    #print name
    if not key:
        # if len(event.string) == 1:
        #     print "string-ord:", ord(event.string), event.string
        # else:
        #     print "string-ord:", 'not a char:', event.string
        key = event.string
    
    if key:
        pty.q_write(key)


def webkit_event_loop():

    global gtkthread
    gtkthread = GtkThread()
      
    window, browser = gtkthread.invoke_s(launch_browser)
    receive, execute = establish_browser_channel(gtkthread, browser)
   
    # handle links
    #gtkthread.invoke(lambda : browser.browser.connect('navigation-requested', lambda view, frame, networkRequest: 0))
    #gtkthread.invoke(lambda : browser.connect_navigation_requested(my_navigation_request_handler))
    
    gtkthread.invoke(lambda : browser.connect('destroy', lambda *args, **kwargs: quit()))
    gtkthread.invoke(lambda : browser.connect('resource-request-starting', my_resource_requested_handler))

    pty = term.Pty([80,24])
    gtkthread.invoke(lambda : install_key_events(window, lambda widget, event: handle_keypress(event, pty)))

    # A local webserver to write requests to the PTYs stdin and wait
    # for responses because I did not find a way to mock or get a
    # proxy of libsoup.
    server = webserver.Server(pty).start()
    pty.set_webserver(server) # currently pty handles register_resource commands directly
    
    global state # to make interactive development and debugging easier
    state = dict(browser=browser,
                 receive=receive,
                 execute=execute,
                 pty=pty,
                 server=server)

    # setup onetime load finished handler
    load_finished = Promise()
    load_finished_id = None
    def load_finished_cb(view, frame, user_data=None):
        load_finished.deliver()
        if load_finished_id:
            browser.disconnect(load_finished_id)
    load_finished_id = gtkthread.invoke_s(lambda : browser.connect('document-load-finished', load_finished_cb))

    # load term document
    file = os.path.abspath("term.html")
    uri = 'file://' + urllib.pathname2url(file)

    with open("term.css") as f:
        term_css = f.read()

    with open(file, "r") as f:
        doc = f.read()
        doc = doc.replace("//TERM-CSS-PLACEHOLDER", term_css)
        
    gtkthread.invoke(lambda : browser.load_string(doc, base_uri="http://localhost:{}".format(server.getport())))

    load_finished.get()

    # start a thread to send js expressions to webkit
    t = threading.Thread(target=lambda : pty_loop(pty, execute))
    t.start()



    # read from webkit though console.log messages starting with 'schirm'
    # and containing json data
    while running():
        msg = receive(block=True, timeout=1) # timeout to make waiting for events interruptible
        if msg:
            #print "received:", msg
            if receive_handler(msg, pty):
                pass
            elif msg == "show_webkit_inspector": # shows a blank window :/
                gtkthread.invoke(browser.show_inspector)
    quit()


def pty_loop(pty, execute):
    execute("termInit();")
    try:
        while running():
            jslist = pty.read_and_feed_and_render()
            #print "\n".join(jslist)
            execute("\n".join(jslist))
            execute('term.scrollToBottom();')
    except OSError:
        stop()


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
