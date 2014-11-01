#!/usr/bin/env python
import os
import sys
import logging
import argparse
import warnings
import itertools
import signal

import chan

import terminal
import terminalio
import utils

import sys; sys.path.append('../webkitwindow') # TODO: fix
import webkitwindow

logger = logging.getLogger('schirm')

def init_logger(level=logging.ERROR, filters=[]):
    l = logging.getLogger('schirm')
    h = logging.StreamHandler()

    if filters:
        for name in filters:
            h.addFilter(logging.Filter(name))

    f = logging.Formatter("%(name)s - %(message)s")

    h.setFormatter(f)
    l.addHandler(h)
    if level:
        l.setLevel(level)
    return l


class SchirmHandler(object):

    _ids = itertools.count()

    def __init__(self, dest_chan, startup_fn):
        self._dest_chan = dest_chan
        self._startup_fn = startup_fn

    def startup(self, window):
        signal.signal(signal.SIGINT, signal.SIG_DFL) # exit on CTRL-C
        self._startup_fn()

    def request(self, req):
        # non blocking
        req.id = self._ids.next()
        utils.create_thread(lambda: self._dest_chan.put(('request', req)))

    def connect(self, websocket):
        # non blocking
        utils.create_thread(lambda: self._dest_chan.put(('websocket_connect', websocket)))
        # websocket.connected()

    def receive(self, websocket, data):
        # print "Websocket recv", websocket, data
        # websocket.send('my'+data) # echo
        utils.create_thread(lambda: self._dest_chan.put(('websocket_receive', websocket, data)))

    def close(self, websocket):
        print "Websocket closed", websocket


def setup_and_dispatch(server_chan,
                       terminal_url,
                       use_pty,
                       cmd,
                       start_clojurescript_repl=False,
                       initial_request=None):

    # client process (pty or plain process)
    client = terminalio.AsyncResettableTerminal(
        use_pty=use_pty,
        cmd=cmd,
    )

    # terminal
    term = terminal.Terminal(client,
                             url=terminal_url,
                             start_clojurescript_repl=start_clojurescript_repl)

    if initial_request:
        term.request(initial_request)

    channels = [client.out, server_chan]

    while True:
        res = True

        try:
            ch, val = chan.chanselect(consumers=channels, producers=[])
            closed = False
        except chan.ChanClosed, co:
            ch = co.which
            val = None
            closed = True

        if ch == client.out:
            assert not closed

            # output from the terminal process
            res = term.input(val)

        elif ch == server_chan:
            assert not closed
            msgtype = val[0]
            if msgtype == 'request':
                # webserver incoming request
                res = term.request(val[1])
            elif msgtype == 'websocket_connect':
                res = term.websocket_connect(val[1])
            elif msgtype == 'websocket_receive':
                res = term.websocket_receive(val[1], val[2])
            else:
                assert 'unknown msgtype: %r' % (msgtype, )

        else:
            if closed:
                channels.remove(ch)
            else:
                # webserver incoming websocket message
                res = term.websocket_msg(ch, val)

        # deal with the returnvalue
        if isinstance(res, chan.Chan):
            channels.append(res)
        elif res == 'reload':
            return 'reload', val
        elif res is False:
            return False, None

def run(use_pty=True, cmd=None, start_clojurescript_repl=False):

    # pyqt embedded webkit
    server_chan = chan.Chan()

    terminal_url = terminal.Terminal.create_url()

    def run_emulation():
        req = None
        while True:
            res, req = setup_and_dispatch(server_chan=server_chan,
                                          cmd=cmd,
                                          use_pty=use_pty,
                                          terminal_url=terminal_url,
                                          start_clojurescript_repl=start_clojurescript_repl,
                                          initial_request=req)
            if res == 'reload':
                pass
            else:
                return res

    # pyqt embedded webkit takes over now
    # puts all requests into server_chan
    webkitwindow.WebkitWindow.run(handler=SchirmHandler(server_chan, lambda:utils.create_thread(run_emulation)),
                                  url=terminal_url + '/term.html')

def main():

    # configure logging and the Schirm class
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("--log-filter", help="Only show log messages for this module, e.g. schirm-webserver", nargs="+")
    parser.add_argument("-d", "--iframe-debug", help="Let iframes use the same domain as the main term frame to be able to access them with javascript from the webkit inspector", action="store_true")
    parser.add_argument("--no-pty", help="Do not use a pty (pseudo terminal) device.", action="store_true")
    parser.add_argument("--command", help="The command to execute within the terminal instead of the current users default shell.")
    parser.add_argument("--rpdb", help="Start the Remote Python debugger using this password.")
    parser.add_argument("--repl", "--start-clojurescript-repl", help="Start Clojurescript REPL to debug the Schirm client code.", action="store_true")
    args = parser.parse_args()

    if args.rpdb:
        try:
            import rpdb2
            print "run the following command to connect the debugger (password: %r):" % (args.rpdb,)
            print "    rpdb2 --attach %s" % (os.getpid(), )
            rpdb2.start_embedded_debugger(args.rpdb)
        except ImportError:
            print "install winpdb to debug schirm (`apt-get install winpdb` on ubuntu)"
            sys.exit(1)

    init_logger(level=([None, logging.INFO, logging.DEBUG][max(0, min(2, args.verbose))]),
                filters=args.log_filter)

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    run_args = dict

    run(use_pty=not args.no_pty,
        cmd=args.command or None,
        start_clojurescript_repl=args.repl)

if __name__ == '__main__':
    main()
