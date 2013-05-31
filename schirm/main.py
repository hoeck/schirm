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

def init_logger(level=logging.ERROR):
    l = logging.getLogger('schirm')
    h = logging.StreamHandler()
    f = logging.Formatter("%(name)s - %(message)s")

    h.setFormatter(f)
    l.addHandler(h)
    if level:
        l.setLevel(level)
    return l

def run(use_pty=True, cmd=None):

    # use two queues to feed and observe the terminal
    messages_in  = Queue.Queue()
    messages_out = Queue.Queue()

    # threaded webserver
    server = webserver.Server(queue=messages_in)

    browser_process = browser.start_browser(
        proxy_host='localhost',
        proxy_port=server.getport(),
        url='http://termframe.localhost'
    )

    # client process (pty or plain process)
    client = terminalio.create_terminal(use_pty=use_pty, cmd=cmd)

    # read from the client and push onto messages_in
    def client_read():
        while True:
            terminalio.terminal_read(client, messages_in)

    utils.create_thread(client_read, name="client_read")

    # client and webserver are required for inputs and responses
    webserver_async_stub = webserver.AsyncHttp(messages_out)
    client_async_stub = terminalio.AsyncTerminal(messages_out)
    term = terminal.Terminal(client=client_async_stub,
                             webserver=webserver_async_stub,
                             messages_out=messages_out)

    # messages_in
    def dispatch_terminal_input():
        while True:
            msg = messages_in.get()
            term.handle(msg)

    utils.create_thread(dispatch_terminal_input)

    # messages_out
    def dispatch_terminal_output():
        while True:
            try:
                msg = messages_out.get(timeout=1)
            except Queue.Empty, e:
                msg = None
            except KeyboardInterrupt, e:
                print "\nexiting schirm"
                sys.exit(0)

            if not msg:
                pass
            elif msg['name'] == 'client_write':
                # execute client writes in its own thread to avoid blocking??
                client.write(msg['msg']['data'])
            elif msg['name'] == 'client_set_size':
                client.set_size(msg['msg']['lines'], msg['msg']['columns'])
            elif msg['name'] == 'webserver':
                server.handle(msg['msg'])
            elif msg['name'] == 'close':
                sys.exit(0)
            elif msg['name'] == 'reload':
                pass
                # main page reload - restart the whole terminal
                # webserver: close all open connections except this one
                # client: kill
                # stop this thread, client read thread, terminal in thread
                # flush all messages from in and out queues
                # rebuild the structure in run
                # browser: keep going, redirect to the same url
            else:
                logger.error('unknown message from terminal: %r' % (msg, ))
                assert False

    # main application loop
    create_thread(target=dispatch_terminal_output, name='main_loop')

    browser_process.wait()

def main():

    # configure logging and the Schirm class
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("-d", "--iframe-debug", help="Let iframes use the same domain as the main term frame to be able to access them with javascript from the webkit inspector", action="store_true")
    parser.add_argument("--no-pty", help="Do not use a pty (pseudo terminal) device.", action="store_true")
    parser.add_argument("--command", help="The command to execute within the terminal instead of the current users default shell.")
    args = parser.parse_args()

    init_logger(level=([None, logging.INFO, logging.DEBUG][max(0, min(2, args.verbose))]))

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    run(use_pty=not args.no_pty,
        cmd=args.command or None)

if __name__ == '__main__':
    main()
