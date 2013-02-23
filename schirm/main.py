#!/usr/bin/env python
import logging
import argparse
import warnings

import schirm

def main(use_gtk=False):

    # configure logging and the Schirm class
    parser = argparse.ArgumentParser(description="A linux compatible terminal emulator providing modes for rendering (interactive) html documents.")
    parser.add_argument("-v", "--verbose", help="be verbose, -v for info, -vv for debug log level", action="count")
    parser.add_argument("-d", "--iframe-debug", help="Let iframes use the same domain as the main term frame to be able to access them with javascript from the webkit inspector", action="store_true")
    if use_gtk:
        parser.add_argument("-c", "--console-log", help="write all console.log messages to stdout (use -cc to include document URL and linenumber, -ccc to include schirm-internal usages of console.log)", action="count")

    parser.add_argument("--no-pty", help="Do not use a pty (pseudo terminal) device.", action="store_true")
    parser.add_argument("--command", help="The command to execute within the terminal instead of the current users default shell.")

    args = parser.parse_args()

    if args.verbose:
        schirm.logger.setLevel([None, logging.INFO, logging.DEBUG][max(0, min(2, args.verbose))])

    if not (args.verbose and args.verbose > 1):
        warnings.simplefilter('ignore')

    if use_gtk and args.console_log:
        cl = logging.getLogger('webview_console')
        cl.setLevel([None, logging.INFO, logging.DEBUG][max(0, min(2, args.console_log))])
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(name)s - %(message)s"))
        cl.addHandler(h)

    if args.iframe_debug:
        schirm.Schirm.inspect_iframes = True

    if use_gtk:
        import gtkui
        gtkui.PageProxy.start(Schirm)
        gtkui.PageProxy.new_tab()
    else:
        import termserver
        termserver.start(use_pty=not args.no_pty,
                         cmd=args.command or None)

if __name__ == '__main__':
    main()
