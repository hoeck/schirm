#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Schirm - a linux compatible terminal emulator providing html modes.
# Copyright (C) 2011  Erik Soehnel
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import signal
import os
import time
import urllib
import threading
import simplejson
import logging
import argparse
import warnings
import urlparse
import base64
import pkg_resources
import types

import gtkui
import term

class Webview():

    def __init__(self):
        # set everything up
        # - webview/gtk
        # - webserver
        pass

    # schirm -> webview
    def execute_script(self, src):
        # execute sth. in the context of the document hosting the terminal
        pass

    def execute_script_frame(self, frameid, src):
        # execute sth. in the context of the document of *frame*
        pass

    def respond(self, requestid, data):
        # respond to an earlier request with data
        pass
    
    def load_uri_and_wait(self, uri):
        # load a URI into the webview
        pass

    # webview -> schirm
    def receive(self):
        # console.log (schirm ipc)
        # key
        # mouse
        # request
        dict(type={'key', 'mouse', 'console', 'request'},
             value='',
             frameid='')

def get_term_iframe(view, frame):
    """Given a frame, return the frames iframe-mode frame ancestor or None.

    The iframe-mode ancestor is the first child of the root frame (the
    one that contains term.html and the terminal lines.)
    """
    main_frame = view.get_main_frame()
    f = frame
    while 1:
        p = f.get_parent()
        if not p:
            return None # f was the main frame
        elif p == main_frame:
            return f
        else:
            f = p

def resource_requested_handler(view, frame, resource, request, response):
    (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(request.get_uri())

    mode_frame = get_term_iframe(view, frame) or frame

    if netloc == 'termframe.localhost' and mode_frame.get_name():
        uri = request.get_uri().replace("http://termframe.localhost", "http://{}.localhost".format(mode_frame.get_name()))
        request.set_uri(uri)

    logging.info("{} requested uri: {}".format(mode_frame.get_name() or 'termframe', request.get_uri()))
    return 0

def sample_console_message_handler(view, msg, line, source_id, user_data):
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
            pty.q_resize(int(h), int(w))

        return True

    elif msg.startswith("frame"):
        frame_id = msg[5:msg.find(" ")]
        logging.debug("Log message for iframe {}".format(frame_id))
        if frame_id == str(pty.screen.iframe_id):
            pty.q_write(["\033Rmessage\033;", base64.encodestring(msg[msg.find(" ")+1:]), "\033Q", "\n"])
            return True

    elif msg.startswith("iframeresize"):
        try:
            height = int(msg[len("iframeresize"):])
        except:
            height = None
        if height != None:
            logging.debug("Iframe resize request to {}".format(height))
            pty.q_iframe_resize(height)
            return True
        else:
            return False

    elif msg.startswith("removehistory"):
        n = int(msg[13:])
        pty.q_removehistory(n)
        return True

    else:
        return False # not handled


def check_prepare_path(path):
    """Expand users, absolutify and return path if exists else None."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.exists(path):
        return path
    else:
        return None

def init_dotschirm():
    """Create ~/.schirm/ and or missing files in it."""
    if not os.path.exists(os.path.expanduser('~')):
        return

    dotschirm = os.path.expanduser('~/.schirm/')
    if not os.path.exists(dotschirm):
        os.mkdir(dotschirm)

    user_css = os.path.join(dotschirm, 'user.css')
    if not os.path.exists(user_css):
        with open(user_css, 'w') as f:
            f.write(pkg_resources.resource_string("schirm.resources", "user.css"))

def webkit_event_loop(console_log=None, user_css='~/.schirm/user.css'):
    """Setup, initialize and wire the schirm components:

    - the terminal emulator (term, termscreen)
    - the webkit webview (webkit_wrapper)
    - the local proxy webserver (webserver)
    - the thread transporting changes from term -> webkview (pty_loop)
    - the loop reading the webviews console messages

    console_log .. write console.log messages to stdout
      None: don't write them
         1: write the message
         2: write document-URL:line message

    user_css .. path to the user.css file
    """
    init_dotschirm()

    global gtkthread
    gtkthread = GtkThread()

    schirmview = gtkthread.invoke_s(EmbeddedWebView)
    receive, execute = establish_browser_channel(gtkthread, schirmview.webview)

    # exit handler
    gtkthread.invoke(lambda : schirmview.webview.connect('destroy', lambda *args, **kwargs: quit()))

    # rewrite webkit http requests
    gtkthread.invoke(lambda : schirmview.webview.connect('resource-request-starting', resource_requested_handler)) # obsolete: read iframe documents from the webserver instead of using document.write!

    # terminal focus
    gtkthread.invoke(lambda : schirmview.webview.connect('focus-in-event', lambda *_: pty.q_set_focus(True)))
    gtkthread.invoke(lambda : schirmview.webview.connect('focus-out-event', lambda *_: pty.q_set_focus(False)))

    pty = term.Pty([80,24])
    schirmview.webview.paste_to_pty = pty.paste
    gtkthread.invoke(lambda : install_key_events(schirmview.window, lambda widget, event: handle_keypress(widget, event, schirmview, pty, execute), lambda *_: True))

    # A local webserver to write requests to the PTYs stdin and wait
    # for responses because I did not find a way to mock or get a
    # proxy of libsoup.
    server = webserver.Server(pty, user_css=check_prepare_path(user_css) or 'user.css').start()
    pty.set_webserver(server)
    schirmview.webview.set_proxy("http://localhost:{}".format(server.getport()))

    global state # make interactive development and debugging easier
    state = dict(schirmview=schirmview,
                 receive=receive,
                 execute=execute,
                 pty=pty,
                 server=server)

    # setup onetime load finished handler to track load status of the
    # term.html document
    load_finished = Promise()
    load_finished_id = None
    def load_finished_cb(view, frame, user_data=None):
        load_finished.deliver()
        if load_finished_id:
            schirmview.webview.disconnect(load_finished_id)
    load_finished_id = gtkthread.invoke_s(lambda : schirmview.webview.connect('document-load-finished', load_finished_cb))

    # create and load the term document
    doc = pkg_resources.resource_string("schirm.resources", "term.html")

    gtkthread.invoke(lambda : schirmview.webview.load_uri("http://termframe.localhost/term.html"))
    load_finished.get()

    # start a thread to send js expressions to webkit
    t = threading.Thread(target=lambda : pty_loop(pty, execute, schirmview))
    t.start()

    # read console.log from webkit messages starting with 'schirm'
    # and decode them with json
    while running():

        msg, line, source = receive(block=True, timeout=0.1) or (None, None, None) # timeout to make waiting for events interruptible
        if msg:
            if receive_handler(msg, pty):
                logging.info("webkit-console IPC: {}".format(msg))
            elif console_log == 1:
                print msg
            elif console_log == 2:
                print "{}:{} {}".format(source, line, msg)
    quit()

# import cProfile as profile
# def pty_loop(pty, execute, schirmview):
#     execute("termInit();")
#     # p = profile.Profile()
#     # p.enable()
#     while running() and pty.running():
#         for x in pty.read_and_feed_and_render():
#             # strings are executed in a js context
#             # functions are executed with pty, browser as the arguments
#             if isinstance(x, basestring):
#                 if 'exxitexxitexxitexxit' in x:
#                     print "endegelände"
#                     # p.disable()
#                     # p.dump_stats("schirmprof.pstats")
#                     stop()
#                 execute(x) # TODO: synchronize!!!
#                 #print "execute: %r" % x[:40]
#             elif isinstance(x, types.FunctionType):
#                 x(pty, schirmview, gtkthread)
#             else:
#                 logging.warn("unknown render event: {}".format(x[0]))
# 
#     # p.disable()
#     # p.dump_stats("schirmprof.pstats")
#     stop()

# def main():
#
#     signal.signal(signal.SIGINT, lambda sig, stackframe: quit())
#     signal.siginterrupt(signal.SIGINT, True)
#
#     parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
#     parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
#     parser.add_argument("-c", "--console-log", help="write all console.log messages to stdout (use -cc to include document URL and linenumber)", action="count")
#     args = parser.parse_args()
#
#     if args.verbose:
#         logging.basicConfig(level=[None, logging.INFO, logging.DEBUG][args.verbose])
#
#     if not (args.verbose and args.verbose > 1):
#         warnings.simplefilter('ignore')
#
#     try:
#         __IPYTHON__
#         print "IPython detected, starting webkit loop in its own thread"
#         t = threading.Thread(target=webkit_event_loop, args=(args.console_log,))
#         t.start()
#     except:
#         webkit_event_loop(args.console_log)


# class Schirm(object):
    
    # def __init__(self, webview, profile_file):
    #     self.webview = webview # Webview Proxy: either gtk or sth. else
    #     self.pty = term.Pty([80,24])
    # 
    # def pty_out_loop(self):
    #     """Move information from the terminal to the (embedded) webkit browser."""
    #     self.webview.execute_s("termInit();") # execute and wait for the result
    #     while self.pty.running():
    #         for x in self.pty.read_and_feed_and_render():
    #             # strings are executed in a js context
    #             # functions are executed with pty, browser as the arguments
    #             if isinstance(x, basestring):
    #                 self.webview.execute_script(x)
    #             elif isinstance(x, types.FunctionType):
    #                 # TODO: change all function calls to only use the abstract Webview interface!
    #                 x(self.pty, self.webkit, gui.gtkthread)?
    #             else:
    #                 logging.warn("unknown render event: {}".format(x[0]))
    # 
    # def pty_in_loop(self):
    #     # read console.log from webkit messages starting with 'schirm'
    #     # and decode them with json
    #     message_queue = Queue.Queue()
    # 
    #     def console_message_cb(view, msg, line, source_id):
    #         # source_id .. uri string of the document the console.log occured in
    #         message_queue.put((msg, line, source_id))
    # 
    #         # 1 .. do not invoke the default console message handler
    #         # 0 .. invoke other handlers
    #         return 1
    # 
    #     self.webkit.connect('console-message', console_message_cb)
    # 
    #     def receive(block=True, timeout=None):
    #         """
    #         Like Queue.get but return None if nothing is available
    #         (instead of raising Empty).
    #         """
    #         try:
    #             return message_queue.get(block=block, timeout=timeout)
    #         except Queue.Empty:
    #             return None
    # 
    #     while True: #running():
    #         msg, line, source = receive(block=True, timeout=0.1) or (None, None, None) # timeout to make waiting for events interruptible
    #         if msg:
    #             if receive_handler(msg, pty):
    #                 logging.info("webkit-console IPC: {}".format(msg))
    #             elif console_log == 1:
    #                 print msg
    #             elif console_log == 2:
    #                 print "{}:{} {}".format(source, line, msg)



class Schirm(object):

    # default static resources:
    # - relative paths are looked up in schirm.resources module
    #   using pkg_resources.
    # - absolute paths are loaded from the filesystem (user.css)
    static_resources = {'/schirm.js': "schirm.js",   # schirm client lib
                        '/schirm.css': "schirm.css", # schirm iframe mode styles
                        # terminal emulator files
                        '/term.html': 'term.html',
                        '/term.js': 'term.js',
                        '/term.css': 'term.css',
                        #'/user.css': get_user_css(user_css) # TODO
                        }

    self.not_found = set(["/favicon.ico"])

    def __init__(self, uiproxy):
        self.uiproxy
        self.resources = {} # iframe_id -> resource name -> data
        
        
        self.pty = term.Pty([80,24])
        self.uiproxy.load_uri("")
        self.uiproxy.execute("termInit();")

    # requests

    def respond(self, req_id, data):
        self.uiproxy.respond(req_id, data)

    def register_resource(self, frame_id, name, mimetype, data):
        """Add a static resource name to be served.

        Use the resources name to guess an appropriate Content-Type if
        no mimetype is provided.
        """
        if not name.startswith("/"):
            name = "/" + name
        if frame_id not in self.resources:
            self.resources[frame_id] = {}

        # todo: cleanup old resources:
        # need timeout and old iframe to decide whether to delete
        self.resources[frame_id][name] = self.make_response(mimetype or self.guess_type(name), data)

    def _make_response(self, mimetype, data):
        """Return a string making up an HTML response."""
        return "\n".join(["HTTP/1.1 200 OK",
                          "Cache-Control: " + "no-cache",
                          "Connection: close",
                          "Content-Type: " + mimetype,
                          "Content-Length: " + str(len(data)),
                          "",
                          data])

    def guess_type(self, name):
        """Given a path to a file, guess its mimetype."""
        guessed_type, encoding = mimetypes.guess_type(name, strict=False)
        return guessed_type or "text/plain"

    def _handle_request(self, req): # req is the value of the 'request' message
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)
        m = re.match("(.+)\.localhost", netloc)
        if m:
            iframe_id = m.group(1)
        else:
            iframe_id = None

        if req.error_code:
            logging.debug(req.error_message)
            self.respond(req.id)

        elif req.command == 'GET' \
                and iframe_id \
                and iframe_id in self.resources \
                and path in self.resources[iframe_id]:
            # it's a known static resource, serve it!
            logging.debug("serving static resource {} for iframe {}".format(path, iframe_id))
            self.respond(req.id, self.resources[iframe_id][path])

        elif req.command == 'GET' \
                and path in self.static_resources:
            # builtin static resource, serve it!
            res = self.static_resources[path]
            if os.path.isabs(res):
                # external resource (e.g. user.css file in ~/.schirm/)
                f = None
                try:
                    with open(res, 'r') as f:
                        data = f.read()
                    logging.debug("serving builtin static resource {} from external path {}.".format(path, res))
                    self.respond(res.id, self._make_response(self.guess_type(path), data))
                except:
                    logging.error("failed to load static resource {} from path {}.".format(path, res))
                    self.respond(req.id)
            else:
                # internal, packaged resource
                logging.debug("serving builtin static resource {}.".format(path))
                data = pkg_resources.resource_string('schirm.resources', res)
                self.respond(req.id, self._make_response(self.guess_type(path), data))

        elif req.command == 'GET' and path in self.not_found:
            # ignore some requests (e.g. favicon)
            logging.debug("Ignoring request ({})".format(path))
            self.respond(req.id)

        elif self.pty.screen.iframe_mode == 'closed':
            # Write requests into stdin of the current terminal process.
            # Only if all document data has already been sent to the iframe.
            # So that requests are not echoed into the document or
            # into the terminal screen.

            # with self._requests_lock:
            #     req_id = self._getnextid()
            #     self.requests[req_id] = {'client': client, 'time': time.time()}

            def clear_path(path):
                # transform the iframe path from a proxy path to a normal one
                root = "http://{}.localhost".format(iframe_id)
                if root in path:
                    return path[len(root):]
                else:
                    return path

            # transmitting: req_id, method, path, (k, v)*, data
            data = [str(req_id),
                    req.request_version,
                    req.method,
                    clear_path(req.path)]

            for k in req.headers.keys():
                data.append(k)
                data.append(req.headers[k])
            data.append(req.data or "")

            pty_request = START_REQ + SEP.join(base64.encodestring(x) for x in data) + END + NEWLINE
            # TODO: better IN loop, also, check the flag _inside_ the
            # loop thread by pushing a fnuction onto the input_queue
            # and have it execute in the context of the thread to
            # avoid race conditions
            if self.pty.screen.iframe_mode == 'closed':
                self.pty.q_write_iframe(pty_request)

        else:
            # only serve non-static requests if terminal is in iframe_mode == 'open'
            if self.pty.screen.iframe_mode == 'open':
                logging.debug("unknown resource: '{}' - responding with 404".format(path))
            else:
                logging.debug("Not in iframe mode - responding with 404")

            self.respond(req.id)

    def _handle_keypress(self, key):
        """Map gtk keyvals/strings to terminal keys."""
        # compute the terminal key
        k = self.pty.map_key(key.name, (key.shift, key.alt, key.control))
        if not k:
            if alt:
                k = "\033%s" % key.string
            else:
                k = key.string

        # TODO: this must be a function running in the pty thread
        #       to get rid of the iframe_mode race condition
        if self.pty.screen.iframe_mode:
            # in iframe mode, only write some ctrl-* events to the
            # terminal process
            if k and \
                    control and \
                    name in "dcz":
                self.pty.q_write(k)
        else:
            if k:
                self.pty.q_write(k)

    def pty_out_loop(self):
        """Move information from the terminal to the (embedded) webkit browser."""
        self.uiproxy.execute_script("termInit();") # execute and wait for the result

        while self.pty.running():
            # reads term input from a queue, alters term input accordingly, reads output
            for x in self.pty.read_and_feed_and_render():
                if isinstance(x, basestring):
                    # strings are evaled as javascript in the main term document
                    self.uiprocy.execute_script(x)
                elif isinstance(x, types.FunctionType):
                    # functions are invoked with self (in order to get
                    # access to the uiproxy and the pty)
                    x(self.uiproxy)
                else:
                    logging.warn("unknown render event: {}".format(x[0]))

def main():
    gtkui.PageProxy.start(Schirm)

if __name__ == '__main__':
    main()
