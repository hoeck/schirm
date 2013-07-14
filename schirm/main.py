#!/usr/bin/env python
import sys
import logging
import argparse
import warnings
import Queue

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

    # use two queues to feed and observe the terminal (the other is setup in _setup_http_terminal)
    messages_in  = Queue.Queue() # (webserver, client) -> terminal
    # terminal -> (webserver, client, controller) communication
    messages_out = Queue.Queue()

    # threaded webserver acting as a proxy+webserver
    server = webserver.Server(queue=messages_in)

    # client process (pty or plain process)
    client = terminalio.AsyncResettableTerminal(
        outgoing=messages_in,
        use_pty=use_pty,
        cmd=cmd,
    )

    # client and webserver are required for inputs and responses
    webserver_stub = webserver.AsyncHttp(messages_out)
    client_stub = terminalio.TerminalMessages(messages_out)
    term = terminal.Terminal(client=client_stub, # async .write and .set_size methods
                             webserver=webserver_stub,
                             messages_out=messages_out)

    # browser process to display the terminal
    browser_process = browser.start_browser(
        proxy_host='localhost',
        proxy_port=server.getport(),
        url=term.url,
    )

    # messages_in
    def dispatch_terminal_input():
        p = utils.Profile('profile/term')
        while True:
            msg = messages_in.get()
            p.enable()
            quit = term.handle(msg)
            p.disable()
            if quit:
                p.done()
                return

    utils.create_thread(dispatch_terminal_input)

    # messages_out
    def dispatch_terminal_output():
        while True:
            try:
                msg = messages_out.get(timeout=1)
            except Queue.Empty, e:
                msg = None
            except KeyboardInterrupt, e:
                # should do: client.kill()
                print "\nexiting schirm"
                sys.exit(0)

            if not msg:
                pass
            elif msg['name'] == 'client':
                # execute client writes in its own thread to avoid blocking??
                client.handle(msg['msg'])
            elif msg['name'] == 'webserver':
                server.handle(msg['msg'])
            elif msg['name'] == 'close':
                if msg['pid'] == client.getpid():
                    browser_process.kill()
                else:
                    # ignore close messages of previously killed client processes
                    pass
            elif msg['name'] == 'reload':
                # main page reload - restart the whole terminal
                # TODO: implement confirmation in term.js when 'leaving' the page

                # webserver: close all pending (== waiting for an
                # internal response) requests except this one)
                server.abort_pending_requests(except_id=msg['msg']['request_id'])

                client.kill()

                # clear the _in_ queue
                while True:
                    try:
                        messages_in.get_nowait()
                    except Queue.Empty, e:
                        break

                term.reset()

                # restart client
                client.reset()

                # stop this thread, client read thread, terminal in thread
                # flush all messages from in and out queues
                # rebuild the structure in run
                # browser: keep going, redirect to the same url
                server.redirect(
                    id=msg['msg']['request_id'],
                    url=term.url,
                )

            else:
                logger.error('unknown message from terminal: %r' % (msg, ))
                assert False

    # main application loop
    utils.create_thread(target=dispatch_terminal_output, name='main_loop')

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
