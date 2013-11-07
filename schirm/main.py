#!/usr/bin/env python
import os
import sys
import logging
import argparse
import warnings
import chan

import terminal
import terminalio
import webserver
import browser
import utils

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

def setup_and_dispatch(server,
                       terminal_url,
                       use_pty,
                       cmd,
                       initial_request=None):

    # client process (pty or plain process)
    client = terminalio.AsyncResettableTerminal(
        use_pty=use_pty,
        cmd=cmd,
    )

    # terminal
    term = terminal.Terminal(client, url=terminal_url)
    if initial_request:
        term.request(initial_request)

    channels = [client.out, server.chan]

    while True:
        try:
            ch, val = chan.chanselect(consumers=channels, producers=[])
            closed = False
        except chan.ChanClosed, co:
            ch = co.which
            val = None
            closed = True

        if ch == client.out:
            if closed:
                assert False # TODO

            # output from the terminal process
            res = term.input(val)

        elif ch == server.chan:
            if ch == closed:
                assert False

            # webserver incoming request
            res = term.request(val)

        else:
            if closed:
                channels.pop(ch)
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

def run(use_pty=True, cmd=None):

    # threaded webserver acting as a proxy+webserver
    server = webserver.Server().start()

    terminal_url = terminal.Terminal.create_url()

    def run_emulation():
        req = None
        while True:
            res, req = setup_and_dispatch(server,
                                          cmd=cmd,
                                          use_pty=use_pty,
                                          terminal_url=terminal_url,
                                          initial_request=req)
            if res == 'reload':
                pass
            else:
                return res

    utils.create_thread(run_emulation)

    # browser process to display the terminal
    browser_process = browser.start_browser(
        proxy_host='localhost',
        proxy_port=server.port,
        url=terminal_url,
    )

    # wait for the browser to be closed and rm the temporary profile
    browser_process.wait_and_cleanup()

def main():

    # configure logging and the Schirm class
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("--log-filter", help="Only show log messages for this module, e.g. schirm-webserver", nargs="+")
    parser.add_argument("-d", "--iframe-debug", help="Let iframes use the same domain as the main term frame to be able to access them with javascript from the webkit inspector", action="store_true")
    parser.add_argument("--no-pty", help="Do not use a pty (pseudo terminal) device.", action="store_true")
    parser.add_argument("--command", help="The command to execute within the terminal instead of the current users default shell.")
    parser.add_argument("--rpdb", help="Start the Remote Python debugger using this password.")
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
        cmd=args.command or None)

if __name__ == '__main__':
    main()
