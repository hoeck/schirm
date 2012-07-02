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
import re
import time
import urllib
import mimetypes
import threading
import logging
import argparse
import warnings
import urlparse
import base64
import pkg_resources
import types
import Queue
import json

import gtkui
import term

ESC = "\033"
SEP = ESC + ";"
START_REQ = ESC + "R" + "request" + SEP
END = ESC + "Q"
NEWLINE = "\n" # somehow required for 'flushing', tcflush and other ioctls didn't work :/

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

def get_config_file_path(filename):
    """Return the full path for a file in ~/.schirm/<filename>.

    If it does not exist, return the one from resources.
    """
    config = os.path.join(os.path.expanduser('~/.schirm'), filename)
    if not os.path.exists(config):
        resource = pkg_resources.resource_filename('schirm.resources', filename)
        if not os.path.exists(resource):
            raise Exception("Unknown resource: %r" % (filename, ))
        return resource_dir
    return config


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
                        # user configurable stylesheets
                        '/user.css': get_config_file_path('user.css'),
                        }

    not_found = set(["/favicon.ico"])

    def __init__(self, uiproxy):
        # pty, webview, webserver -> schirm communication
        # each message on output queue is a tuple of: (typename, attrdict-value)
        # TODO: would be easier to directly enqueue functions + their arguments
        self._input_queue = Queue.Queue()

        self.uiproxy = uiproxy
        self.resources = {} # iframe_id -> resource name -> data

        # start the pty
        self.pty = term.Pty([80,24])

        # start workers
        ui_input_worker = threading.Thread(target=self.ui_in_loop)
        ui_input_worker.setDaemon(True)
        ui_input_worker.start()

        pty_output_worker = threading.Thread(target=self.pty_out_loop)
        pty_output_worker.setDaemon(True)
        pty_output_worker.start()

        # load the terminal ui
        self._term_uri = "http://termframe.localhost/term.html"
        self._term_init_js = "termInit();" # executed after document load
        self.uiproxy.load_uri(self._term_uri)

        # iframe_write connections
        self.iframe_document_data = {}

    # requests

    def respond(self, req_id, data=None, close=True):
        self.uiproxy.respond(req_id, data, close)

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
        self.resources[frame_id][name] = self._make_response(mimetype or self.guess_type(name), data)

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

    # state changing functions, all executed from input_queue in a
    # dedicated thread to keep consistency, the _underscored versions
    # are the tasks running in the input thread

    # 1) methods called from the terminal (render_chanages -> EventRenderer.xxx)
    #    to update UI and webserver state

    def _iframe_write(self, iframe_id, data):
        # enqueue document data for the iframe or respond immediately
        # to the still open connection
        req_id = self.iframe_document_data[iframe_id]['req_id']
        if req_id:
            # respond immediately
            self.respond(req_id, data, close=False)
        else:
            # 'enqueue' the data
            self.iframe_document_data[iframe_id]['data'].append(data)

    def iframe_write(self, iframe_id, data):
        self.enqueue_f(self._iframe_write, iframe_id, data)

    def _iframe_insert(self, line_index, iframe_id):
        self.iframe_document_data[iframe_id] = {'req_id':None,
                                                'data':[]}
        # create the js to insert an iframe line
        uri = "http://{iframe_id}.localhost/".format(iframe_id=iframe_id) # TODO: urlencode iframe_id
        js = "term.insertIframe({line_index}, {iframe_id}, {uri})".format(
            line_index=json.dumps(line_index),
            iframe_id=json.dumps(iframe_id),
            uri=json.dumps(uri))
        self.uiproxy.execute_script(js)

    def iframe_insert(self, line_index, iframe_id):
        self.enqueue_f(self._iframe_insert, line_index, iframe_id)

    def _iframe_close(self, iframe_id):
        # iframe data entry must already exist
        iframe = self.iframe_document_data[iframe_id]
        req_id = iframe['req_id']
        if req_id:
            # close instantly
            self.respond(req_id, '', close=True)
            del self.iframe_document_data[iframe_id]
        else:
            # 'enqueue' a close message
            self.iframe_document_data[iframe_id]['close'] = True

    def iframe_close(self, iframe_id):
        # close the iframe connection but stay in iframe mode
        self.enqueue_f(self._iframe_close, iframe_id)

    def _iframe_leave(self, iframe_id):
        # back to classic terminal mode
        # TODO: check and close the current iframe data connection
        self.uiproxy.execute_script('iframeLeave();')

    def iframe_leave(self, iframe_id):
        self.enqueue_f(self._iframe_leave, iframe_id)

    # 2) methods called from the uiproxy to change the terminal state
    #    (http requests, document-load-finished, keypresses, mouseclicks ..)

    def _set_focus(self, focus):
        self.pty.q_set_focus(focus)

    def set_focus(self, focus):
        self.enqueue_f(self._set_focus, focus)

    def _keypress(self, key):
        """Map gtk keyvals/strings to terminal keys."""
        # compute the terminal key
        k = self.pty.map_key(key.name, (key.shift, key.alt, key.control))
        if not k:
            if key.alt:
                k = "\033%s" % key.string
            else:
                k = key.string

        # TODO: this must be a function running in the pty thread
        #       to get rid of the iframe_mode race condition
        if self.pty.screen.iframe_mode:
            # in iframe mode, only write some ctrl-* events to the
            # terminal process
            if k and \
                    key.control and \
                    key.name in "dcz":
                self.pty.q_write(k)
        else:
            if k:
                self.pty.q_write(k)

    def keypress(self, key):
        self.enqueue_f(self._keypress, key)

    def _resize(self, size):
        self.pty.q_resize(size.height, size.width)

    def resize(self, size):
        self.enqueue_f(self._resize, size)

    def _request(self, req):
        # TODO: split this up into separate functions
        (scheme, netloc, path, params, query, fragment) = urlparse.urlparse(req.path)

        logging.info("%s %s" % (req.method, req.path))

        # use the subdomain to sandbox iframes and separate requests
        m = re.match("(.+)\.localhost", netloc)
        if m:
            try:
                iframe_id = int(m.group(1))
            except:
                iframe_id = None
        else:
            iframe_id = None

        if req.error_code:
            logging.debug(req.error_message)
            self.respond(req.id)

        elif req.method == 'GET' \
                and iframe_id    \
                and path == '/'  \
                and iframe_id in self.iframe_document_data:
            # iframe document data request
            self.iframe_document_data[iframe_id]['req_id'] = req.id
            data = ''.join(self.iframe_document_data[iframe_id]['data'])
            self.respond(req.id,
                         data="\r\n".join(["HTTP/1.1 200 OK",
                                           "Cache-Control: no-cache",
                                           "Content-Type: text/html",
                                           "",
                                           data]),
                         close=False)
            if self.iframe_document_data[iframe_id].get('close'):
                # close the connection and delete the iframe data
                self.respond(req.id, '')
                del self.iframe_document_data[iframe_id]

        elif req.method == 'GET' \
                and iframe_id \
                and iframe_id in self.resources \
                and path in self.resources[iframe_id]:
            # it's a known static (iframe) resource, serve it!
            logging.debug("serving static resource {} for iframe {}".format(path, iframe_id))
            self.respond(req.id, self.resources[iframe_id][path])

        elif req.method == 'GET' \
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
                    self.respond(req.id, self._make_response(self.guess_type(path), data))
                except:
                    logging.error("failed to load static resource {} from path {}.".format(path, res))
                    self.respond(req.id)

            else:
                # internal, packaged resource
                logging.debug("serving builtin static resource {}.".format(path))
                data = pkg_resources.resource_string('schirm.resources', res)
                self.respond(req.id, self._make_response(self.guess_type(path), data))

        elif req.method == 'GET' and path in self.not_found:
            # ignore some requests (e.g. favicon)
            logging.debug("Ignoring request ({})".format(path))
            self.respond(req.id)

        elif self.pty.screen.iframe_mode == 'closed':
            # Write requests into stdin of the current terminal process.
            # Only if all document data has already been sent to the iframe.
            # So that requests are not echoed into the document or
            # into the terminal screen.

            def clear_path(path):
                # transform the iframe path from a proxy path to a normal one
                root = "http://{}.localhost".format(iframe_id)
                if root in path:
                    return path[len(root):]
                else:
                    return path

            # transmitting: req_id, method, path, (k, v)*, data
            data = [str(req.id),
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

    def request(self, req):
        self.enqueue_f(self._request, req)

    def _document_load_finished(self, uri):
        if uri == self._term_uri:
            self.uiproxy.execute_script(self._term_init_js)
        else:
            logging.error("Unexpected document-load-finished. %r" % (uri,))

    def document_load_finished(self, uri):
        self.enqueue_f(self._document_load_finished, uri)

    # ui event loop

    def enqueue_message(self, message):
        self._input_queue.put(message)

    def enqueue_f(self, f, *args, **kwargs):
        self._input_queue.put(lambda: f(*args, **kwargs))

    def ui_in_loop(self):
        """Pop functions (tasks) from the _input_queue and execute them."""
        while True:
            self._input_queue.get()()

    # pty render input loop

    def pty_out_loop(self):
        """Move information from the terminal to the (embedded) webkit browser."""
        while True: #self.pty.running():
            # reads term input from a queue, alters the term input
            # accordingly, reads output and enques that on the
            # uiproxies input queue
            for x in self.pty.read_and_feed_and_render():
                if isinstance(x, basestring):
                    # strings are evaled as javascript in the main term document
                    self.uiproxy.execute_script(x)
                elif isinstance(x, types.FunctionType):
                    # functions are invoked with self (in order to get
                    # access to the uiproxy and the pty)
                    x(self)
                else:
                    logging.warn("unknown render event: {}".format(x[0]))


def main():
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("-c", "--console-log", help="write all console.log messages to stdout (use -cc to include document URL and linenumber)", action="count")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=[None, logging.INFO, logging.DEBUG][args.verbose])

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    if args.console_log > 0:
        gtkui.console_log_level = min(3, max(0, args.console_log))

    init_dotschirm()
    gtkui.PageProxy.start(Schirm)
    gtkui.PageProxy.new_tab()

if __name__ == '__main__':
    main()
