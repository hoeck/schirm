#!/usr/bin/env python
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

def run(use_pty=True, cmd=None):

    # threaded webserver acting as a proxy+webserver
    server = webserver.Server().start()

    # client process (pty or plain process)
    client = terminalio.AsyncResettableTerminal(
        use_pty=use_pty,
        cmd=cmd,
    )

    # terminal
    term = terminal.Terminal(client)

    # thread
    def dispatch():
        while True:
            channels = [client.chan, server.chan]

            try:
                ch, val = chan.chanselect(consumers=channels,
                                          producers=[])
                closed = False
            except chan.ChanClosed, co:
                ch = co.which
                val = None
                closed = True

            if ch == client.chan:
                if closed:
                    return

                # output from the terminal process
                res = term.input(val)
                if res is False:
                    return

            elif ch == server.chan:
                if ch = closed:
                    return
                # webserver incoming request
                res = term.request(val)
                if isinstance(res, chan.Chan):
                    channels.append(res)
                elif res is False:
                    return

            else:
                if closed:
                    channels.pop(ch)
                # webserver incoming websocket message
                term.websocket(ch, val)

    utils.create_thread(dispatch)

    # browser process to display the terminal
    browser_process = browser.start_browser(
        proxy_host='localhost',
        proxy_port=server.getport(),
        url=term.url,
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
    args = parser.parse_args()

    init_logger(level=([None, logging.INFO, logging.DEBUG][max(0, min(2, args.verbose))]),
                filters=args.log_filter)

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    run(use_pty=not args.no_pty,
        cmd=args.command or None)

if __name__ == '__main__':
    main()
