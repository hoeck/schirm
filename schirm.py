import sys
import signal
import os
import time
import urllib
import threading
import simplejson


from webkit_wrapper import GtkThread, launch_browser, establish_browser_channel

run = True
def stop():
    global run
    run = False

state = None
gtkthread = None


last_nav_request = None
def my_navigation_request_handler(view, frame, networkRequest):
    print "navigation-request", networkRequest.get_uri()
    global last_nav_request
    last_nav_request = (view, frame, networkRequest)
    return 0


def webkit_event_loop():
    global run
    global gtkthread
    gtkthread = GtkThread()
      
    browser = gtkthread.invoke_s(launch_browser)

    receive, send = establish_browser_channel(gtkthread, browser)

    # handle links
    #gtkthread.invoke(lambda : browser.browser.connect('navigation-requested', lambda view, frame, networkRequest: 0))
    gtkthread.invoke(lambda : browser.connect_navigation_requested(my_navigation_request_handler))

    global state
    state = dict(browser=browser, receive=receive, send=send)

    # load shellinabox
    file = os.path.abspath('/var/www/index.html')
    uri = 'file://' + urllib.pathname2url(file)
    browser.open_uri(uri)

    # while run:
    #     msg = receive(block=True)
    #     print "received:", msg 
        

def quit():
    #signal.signal(signal.SIGINT, lambda sig, stackframe: pass)
    try:
        stop()
        gtkthread.kill()
    except:
        pass

def main():
    #t = threading.Thread(target=webkit_event_loop)
    #t.start()
    webkit_event_loop()
    
if __name__ == '__main__': # <-- this line is optional    
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
