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

from UserList import UserList
import os
import logging
import re
import base64
import pkgutil

import pyte
from pyte.screens import Char, Margins, Cursor
from pyte import modes as mo, graphics as g, charsets as cs, control as ctrl
import browserscreen

logger = logging.getLogger(__name__)

# id for the iframe modes:
# ``ESC [ ?`` <mode-id> ( ``;`` <arg> )* ``h``
# all writes go to an iframe
IFRAME_DOCUMENT_MODE_ID = 5151
# cgi-like interface to respond to a previous iframes http requests
IFRAME_RESPONSE_MODE_ID = 5152

class TermScreen(pyte.Screen):

    def __init__(self, columns, lines):
        self.savepoints = []
        # terminal dimensions in characters
        self.lines, self.columns = lines, columns

        self.linecontainer = browserscreen.BrowserScreen()

        # list of drawing events for the cljs screen
        self.events = []

        # current iframe_mode,
        # one of None, 'open' or 'closed'
        # None     .. no active iframe
        # 'open'   .. active iframe which is still being sent data to
        # 'closed' .. active iframe where the initial data has already been sent
        self.iframe_mode = None
        self.iframe_id = None
        self.reset()
        self.events = []

    def _flush_events(self):
        self.events.extend(self.linecontainer.pop_events())

    def pop_events(self):
        self.linecontainer.cursor(self.cursor.y, self.cursor.x)
        self.linecontainer.check_scrollback()
        if self.events:
            self.events.extend(self.linecontainer.pop_events())
            ev = self.events
            self.events = []
            return ev
        else:
            return self.linecontainer.pop_events()

    # pyte.Screen implementation

    def __before__(self, command):
        pass

    def __after__(self, command):
        pass

    _default_char = Char(data=" ", fg="default", bg="default")
    def _create_line(self, default_char=None):
        return Line(self.columns, default_char or self._default_char)

    def _is_empty_line(self, line):
        return line.is_empty()

    def reset(self):
        """Resets the terminal to its initial state.

        * Scroll margins are reset to screen boundaries.
        * Cursor is moved to home location -- ``(0, 0)`` and its
          attributes are set to defaults (see :attr:`default_char`).
        * Screen is cleared -- each character is reset to
          :attr:`default_char`.
        * Tabstops are reset to "every eight columns".

        .. note::

           Neither VT220 nor VT102 manuals mentioned that terminal modes
           and tabstops should be reset as well, thanks to
           :manpage:`xterm` -- we now know that.
        """
        self._flush_events()
        self.linecontainer.reset(self.lines)

        if self.iframe_mode:
            self.iframe_leave()

        self.mode = set([mo.DECAWM, mo.DECTCEM, mo.LNM, mo.DECTCEM])
        self.margins = Margins(0, self.lines - 1)

        # According to VT220 manual and ``linux/drivers/tty/vt.c``
        # the default G0 charset is latin-1, but for reasons unknown
        # latin-1 breaks ascii-graphics; so G0 defaults to cp437.
        self.charset = 0
        self.g0_charset = cs.IBMPC_MAP
        self.g1_charset = cs.VT100_MAP

        # From ``man terminfo`` -- "... hardware tabs are initially
        # set every `n` spaces when the terminal is powered up. Since
        # we aim to support VT102 / VT220 and linux -- we use n = 8.
        self.tabstops = set(range(7, self.columns, 8))

        self.cursor = Cursor(0, 0)
        self.cursor_position()

    def resize(self, lines=None, columns=None):
        """Resize the screen to the given dimensions keeping the history intact.

        If the requested screen size has more lines than the existing
        screen, lines will be added at the bottom. If the requested
        size has less lines than the existing screen, lines will be
        clipped at the top of the screen. Similarly, if the existing
        screen has less columns than the requested screen, columns will
        be added at the right, and if it has more -- columns will be
        clipped at the right.

        .. note:: According to `xterm`, we should also reset origin
                  mode and screen margins, see ``xterm/screen.c:1761``.
                  -> but we don't do this here
        :param int lines: number of lines in the new screen.
        :param int columns: number of columns in the new screen.
        """
        self._flush_events()

        old_lines = self.lines

        self.lines   = (lines   or self.lines)
        self.columns = (columns or self.columns)

        if mo.DECALTBUF in self.mode and False:
            # home cursor
            self.reset_mode(mo.DECOM)
        else:
            # cursor: make sure that it 'stays' on its current line
            cursor_delta = self.linecontainer.resize(old_lines, self.lines, self.columns)
            self.cursor.y += cursor_delta
            self.cursor.x = min(max(self.cursor.x, 0), self.columns-1)

        self.margins = Margins(0, self.lines - 1)

    def set_mode(self, *modes, **kwargs):
        """Sets (enables) a given list of modes.

        :param list modes: modes to set, where each mode is a constant
                           from :mod:`pyte.modes`.
        """
        mode_id = (modes[:1] or [None])[0]
        if mode_id in (IFRAME_DOCUMENT_MODE_ID, IFRAME_RESPONSE_MODE_ID):
            cookie = ';'.join(map(str,modes[1:]))
            # Need the cookie to prove that the request comes from a
            # real program, an not just by 'cat'-ing some file.
            # Javascript in iframes will only be activated with a
            # valid cookie.
            self.iframe_set_mode(mode_id, cookie)
            return

        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = set([mode << mo.PRIVATE_MODE_SHIFT for mode in modes])

        # translate mode shortcuts and aliases
        if mo.DECAPPMODE in modes:
            # DECAPP is a combination of DECALTBUF and DECSAVECUR and
            # additionally erase the alternative buffer
            modes.update([mo.DECALTBUF, mo.DECSAVECUR])

        if mo.DECALTBUF_ALT in modes:
            modes.remove(mo.DECALTBUF_ALT)
            modes.add(mo.DECALTBUF)

        self.mode.update(modes)

        if mo.DECAPPKEYS in modes:
            # use application mode keys, see termkey.py (app_key_mode arg)
            pass

        # When DECOLM mode is set, the screen is erased and the cursor
        # moves to the home position.
        if mo.DECCOLM in modes:
            self.resize(columns=132)
            self.erase_in_display(2)
            self.cursor_position()

        # According to `vttest`, DECOM should also home the cursor, see
        # vttest/main.c:303.
        if mo.DECOM in modes:
            self.cursor_position()

        # Mark all displayed characters as reverse.
        if mo.DECSCNM in modes:
            # todo: check that iter(self.linecontainer) lazily creates and returns all lines
            linecontainer.reverse_all_lines()
            self.select_graphic_rendition(g._SGR["+reverse"])

        # Make the cursor visible.
        if mo.DECTCEM in modes:
            self.cursor.hidden = False

        if mo.DECSAVECUR in modes:
            # save cursor position and restore it on mode reset
            self.save_cursor()
            if mo.DECAPPMODE in modes:
                self.cursor_position()

        if mo.DECALTBUF in modes:
            # enable alternative draw buffer
            self._flush_events()
            self.linecontainer.enter_altbuf_mode()

        # if mo.DECAPPMODE in modes:
        #     self.erase_in_display(2)

    def reset_mode(self, *modes, **kwargs):
        """Resets (disables) a given list of modes.

        :param list modes: modes to reset -- hopefully, each mode is a
                           constant from :mod:`pyte.modes`.
        """

        mode_id = (modes[:1] or [None])[0]
        if mode_id in (IFRAME_DOCUMENT_MODE_ID, IFRAME_RESPONSE_MODE_ID) \
                and kwargs.get('private'):
            cookie = ';'.join(map(str,modes[1:]))
            # Need the cookie to prove that the request comes from a
            # real program, an not just by 'cat'-ing some file.
            # Javascript in iframes will only be activated with a
            # valid cookie.
            self.iframe_reset_mode(mode_id, cookie)
            return

        # Private mode codes aree shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = set([mode << mo.PRIVATE_MODE_SHIFT for mode in modes])

        # translate mode shortcuts and aliases
        if mo.DECAPPMODE in modes:
            # DECAPP is a combination of DECALTBUF and DECSAVECUR
            modes.remove(mo.DECAPPMODE)
            modes.update([mo.DECALTBUF, mo.DECSAVECUR])

        if mo.DECALTBUF_ALT in modes:
            modes.remove(mo.DECALTBUF_ALT)
            modes.add(mo.DECALTBUF)

        self.mode.difference_update(modes)

        # Lines below follow the logic in :meth:`set_mode`.
        if mo.DECCOLM in modes:
            self.resize(columns=80)
            self.erase_in_display(2)
            self.cursor_position()

        if mo.DECOM in modes:
            self.cursor_position()

        if mo.DECSCNM in modes:
            self.linecontainer.reverse_all_lines()
            self.select_graphic_rendition(g._SGR["-reverse"])

        # Hide the cursor.
        if mo.DECTCEM in modes:
            self.cursor.hidden = True

        if mo.DECSAVECUR in modes:
            # save cursor position and restore it on mode reset
            self.restore_cursor()

        if mo.DECALTBUF in modes:
            # disable alternative draw buffer, switch internal
            # linecontainer while preserving generated events
            self._flush_events()
            self.linecontainer.leave_altbuf_mode()

    def draw_string(self, string):
        """Like draw, but for a whole string at once.

        String MUST NOT contain any control characters like newlines or carriage-returns.
        """

        def _write_string(s):
            self.linecontainer.insert_overwrite(self.cursor.y, self.cursor.x, s, self.cursor.attrs)

        # iframe mode? just write the string
        if self.iframe_mode:
            if self.iframe_mode == 'document':
                self.linecontainer.iframe_write(self.iframe_id, string)
            else:
                # ignore all writes to closed documents:
                # those are echo writes of input to the terminal
                pass
        else:
            if mo.IRM in self.mode:
                # move existing chars to the right before inserting string
                # (no wrapping)
                self.insert_characters(len(string))
                _write_string(reversed(string[-(self.columns - self.cursor.x):]))

            elif mo.DECAWM in self.mode:
                # Auto Wrap Mode
                # all chars up to the end of the current line
                line_end = self.columns-self.cursor.x
                s = string[:line_end]
                _write_string(s)
                self.cursor.x += len(s)
                # remaining chars will be written on subsequent lines
                i = 0
                while len(string) > (line_end+(i*self.columns)):
                    self.linefeed()
                    s = string[line_end+(i*self.columns):line_end+((i+1)*self.columns)]
                    _write_string(s)
                    self.cursor.x += len(s)
                    i += 1

            else:
                # no overwrap, just replace the last old char if string
                # will draw over the end of the current line
                line_end = self.columns-self.cursor.x
                if len(string) > line_end:
                    s = string[:line_end-1] + string[-1]
                else:
                    s = string
                _write_string(s)
                self.cursor.x += len(s)

    def index(self):
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        if self.iframe_mode:
            self.linecontainer.iframe_write(self.iframe_id, "\n")
            return

        top, bottom = self.margins
        if self.cursor.y == bottom:
            if top == 0 and bottom == (self.lines - 1):
                # surplus lines move the scrollback if no margin is active
                self.linecontainer.append_line(self.columns)
            else:
                self.linecontainer.insert_line(bottom+1, self.cursor.attrs)
                # delete surplus lines to achieve scrolling within in the margins
                self.linecontainer.remove_line(top)
        else:
            self.cursor_down()

    def reverse_index(self):
        """Move the cursor up one line in the same column. If the cursor
        is at the first line, create a new line at the top and remove
        the last one, scrolling all lines in between.
        """
        top, bottom = self.margins

        if self.cursor.y == top:
            self.linecontainer.remove_line(bottom)
            self.linecontainer.insert_line(top)
        else:
            self.cursor_up()

    def insert_lines(self, count=None):
        """Inserts the indicated # of lines at line with cursor. Lines
        displayed **at** and below the cursor move down. Lines moved
        past the bottom margin are lost.

        :param count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins

        # If cursor is outside scrolling margins it -- do nothin'.
        if top <= self.cursor.y <= bottom:
            # v+1, because range() is exclusive.
            for line in range(self.cursor.y,
                              min(bottom + 1, self.cursor.y + count)):
                self.linecontainer.remove_line(bottom)
                self.linecontainer.insert_line(line, self.cursor.attrs)

            self.carriage_return()

    def delete_lines(self, count=None):
        """Deletes the indicated # of lines, starting at line with
        cursor. As lines are deleted, lines displayed below cursor
        move up. Lines added to bottom of screen have spaces with same
        character attributes as last line moved up.

        :param int count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins

        # If cursor is outside scrolling margins it -- do nothin'.
        if top <= self.cursor.y <= bottom:
            #                v -- +1 to include the bottom margin.
            for _ in range(min(bottom - self.cursor.y + 1, count)):
                self.linecontainer.remove_line(self.cursor.y)
                # TODO: get and use the attributes for the *last* line
                self.linecontainer.insert_line(bottom, self.cursor.attrs)

            self.carriage_return()

    def insert_characters(self, count=None):
        """Inserts the indicated # of blank characters at the cursor
        position. The cursor does not move and remains at the beginning
        of the inserted blank characters. Data on the line is shifted
        forward.

        :param int count: number of characters to insert.
        """
        count = count or 1
        self.linecontainer.insert(self.cursor.y, self.cursor.x, ' ' * count, self.cursor.attrs)

    def delete_characters(self, count=None):
        """Deletes the indicated # of characters, starting with the
        character at cursor position. When a character is deleted, all
        characters to the right of cursor move left. Character attributes
        move with the characters.

        :param int count: number of characters to delete.
        """
        count = count or 1
        # TODO: which style is used for the space characters created
        # on the left? is it really the cursor attrs or is it the
        # style of the rightmost character?
        self.linecontainer.remove(self.cursor.y, self.cursor.x, count)

    def erase_characters(self, count=None):
        """Erases the indicated # of characters, starting with the
        character at cursor position. Character attributes are set
        cursor attributes. The cursor remains in the same position.

        :param int count: number of characters to erase.

        .. warning::

           Even though *ALL* of the VTXXX manuals state that character
           attributes **should be reset to defaults**, ``libvte``,
           ``xterm`` and ``ROTE`` completely ignore this. Same applies
           too all ``erase_*()`` and ``delete_*()`` methods.
        """
        count = count or 1
        self.linecontainer.insert_overwrite(self.cursor.y, self.cursor.x, ' ' * count, self.cursor.attrs)

    def erase_in_line(self, type_of=0, private=False):
        """Erases a line in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: when ``True`` character attributes are left
                             unchanged **not implemented**.
        """
        if type_of == 0:
            start = self.cursor.x
            end = self.columns
        elif type_of == 1:
            start = 0
            end = self.cursor.x
        else:
            start = 0
            end = self.columns

        self.linecontainer.insert_overwrite(self.cursor.y, start, ' ' * (end-start), self.cursor.attrs)

    def erase_in_display(self, type_of=0, private=False):
        """Erases display in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
        :param bool private: when ``True`` character attributes aren left
                             unchanged **not implemented**.
        """
        if type_of in [0, 1]:
            # erase parts of the display -> don't care about history
            interval = (
                # a) erase from cursor to the end of the display, including
                # the cursor,
                range(self.cursor.y + 1, self.lines),
                # b) erase from the beginning of the display to the cursor,
                # including it,
                range(0, self.cursor.y)
            )[type_of]

            s = ' ' * self.columns
            for line in interval:
                # erase the whole line
                self.linecontainer.insert_overwrite(line, 0, s, self.cursor.attrs)

            # erase the line with the cursor.
            self.erase_in_line(type_of)

        else: # type_of == 2
            if mo.DECALTBUF in self.mode:
                s = ' ' * self.columns
                for line in range(self.lines):
                    # erase the whole line
                    self.linecontainer.insert_overwrite(line, 0, s, self.cursor.attrs)
            else:
                # c) erase the whole display ->
                # Push every visible line to the history == add blank
                # lines until all current non-blank lines are above the
                # top of the term window. (thats what xterm does and
                # linux-term not, try using top in both term emulators and
                # see what happens to the history)
                self.linecontainer.add_line_origin(self.lines)

    def string(self, string):
        if self.iframe_mode:
            # in document mode -> 'register resource', debug-message, ...
            # in request mode -> response, send-message, debug-message, ...
            self.linecontainer.iframe_string(self.iframe_id, string)
        else:
            # ignore strings (xterm behaviour) in plain terminal mode
            self.draw_string(string)

    ## xterm title hack

    def os_command(self, string):
        """Parse OS commands.

        Xterm will alter the terminals title according to these commands.
        """
        res = (string or '').split(';', 1)
        if len(res) == 2:
            command_id, data = res
            if command_id == '0':
                self.linecontainer.set_title(data)

    ## iframe extensions

    def _next_iframe_id(self):
        # unique random id to hide the terminals url
        return base64.b32encode(os.urandom(35)).lower()

    def _insert_iframe_line(self):
        self.linecontainer.iframe_enter(self.iframe_id, self.cursor.y)

    def _iframe_close_document(self):
        # add some html to the iframe document for registering ctr-c and ctrl-d key handlers
        iframe_close_snippet = pkgutil.get_data('schirm.resources', 'iframe_close_snippet.html')
        self.linecontainer.iframe_write(self.iframe_id, iframe_close_snippet)
        self.linecontainer.iframe_close(self.iframe_id)

    def iframe_set_mode(self, mode_id, cookie):
        if mode_id == IFRAME_DOCUMENT_MODE_ID:
            # replace the current line with an iframe line at the current
            # cursor position (like self.index())
            # all following chars are written to the iframes root document connection
            if self.iframe_mode == None:
                self.iframe_mode = 'document'
                self.iframe_id = self._next_iframe_id()
                self._insert_iframe_line()
            elif self.iframe_mode == 'response':
                self.iframe_mode = 'document'
            elif self.iframe_mode == 'document':
                pass
            else:
                assert False # Illegal Iframe Mode

        elif mode_id == IFRAME_RESPONSE_MODE_ID:
            if self.iframe_mode == 'document':
                self.iframe_mode = 'response'
                self._iframe_close_document()
            elif self.iframe_mode == 'response':
                pass
            elif self.iframe_mode == None:
                # TODO: insert the iframe and directly switch into
                # response mode, use '/' as the path for the iframe.
                assert False # TODO
            else:
                assert False # unknown iframe mode

        else:
            assert False # unknown mode_id

    def iframe_reset_mode(self, mode_id, cookie):
        if mode_id in (IFRAME_DOCUMENT_MODE_ID, IFRAME_RESPONSE_MODE_ID):
            # always reset the iframe mode, regardless of the exact mode id
            if self.iframe_mode == 'document':
                self._iframe_close_document()
                self.linecontainer.iframe_leave(self.iframe_id)
                self.iframe_mode = None
            elif self.iframe_mode == 'response':
                self.linecontainer.iframe_leave(self.iframe_id)
                self.iframe_mode = None
            else:
                # not in iframe mode - ignore
                pass
        else:
            assert False # unknown mode_id

    def close_stream(self):
        # just hand of the event to the linecontainer
        self.linecontainer.close_stream()

    def iframe_resize(self, iframe_id, height):
        self.linecontainer.iframe_resize(iframe_id, height)

    def start_clojurescript_repl(self):
        self.linecontainer.start_clojurescript_repl()

class SchirmStream(pyte.Stream):

    """An optimized (for the usage in this project) verison pyte.Stream."""

    def close(self):
        """Mark the stream as closed.

        Call this to indicate that there will be no more data being
        fed into this Stream.
        """
        self.dispatch('close_stream')

    stream_esc_pattern = re.compile('|'.join(re.escape(chr(x)) for x in range(32)))
    def feed(self, bytes):
        """Perf-optimized feed function.

        Like feed() but directly use a stream and do not return until
        everything has been read.

        Work in chunks and try to use python functions to capture
        huge, escape-less substrings without having to go through the
        state-machinery (avoiding the function call overhead).
        """
        print "FEED>", repr(bytes)

        string_chunksize = 8192
        stream_chunksize = 128
        src = bytes.decode('utf-8', 'ignore')
        i = 0
        l = len(src)
        while i < l:
            if self.state == 'string':
                # read data fast
                # TODO: call find directly on src and do not create a chunk
                chunk = src[i:i+string_chunksize]
                esc_idx = chunk.find(ctrl.ESC)
                if esc_idx == -1:
                    # fast route: chunk is clean and can be appended
                    # to the current string immediately
                    self.current.append(chunk)
                    i += string_chunksize
                else:
                    # fallback: only the first chars up to esc_idx are clean
                    # use the to normal state machine to parse the remaining string
                    self.current.append(chunk[:esc_idx])
                    i += esc_idx
                    self.consume(src[i])
                    i += 1
            elif self.state == 'stream':
                chunk = src[i:i+stream_chunksize]
                # TODO: do not create a chunk and call search directly on src
                m = self.stream_esc_pattern.search(chunk)
                if not m:
                    # fast route
                    self.dispatch("draw_string", chunk)
                    i += stream_chunksize
                else:
                    if m.start() > 0:
                        self.dispatch("draw_string", chunk[:m.start()])
                    i += m.start()
                    self.consume(src[i])
                    i += 1
            else:
                char = src[i]
                if char:
                    self.consume(char)
                    i += 1
                else:
                    break
        #self._flush_draw()

    def consume(self, char):
        # same as super(SchirmStream, self).consume(char) but without
        # the unicode enforcement
        try:
            self.handlers.get(self.state)(char)
        except TypeError:
            raise
        except KeyError:
            if __debug__:
                self.flags["state"] = self.state
                self.flags["unhandled"] = char
                self.dispatch("debug", *self.params)
                self.reset()
            else:
                raise

    # I use my own dispatch function - I don't need multiple listeners.
    # Ignore the only flag too.
    def dispatch(self, event, *args, **kwargs):
        print "E>", event, args
        (listener, only) = self.listeners[0] # ignore 'only'
        if self.listeners:
            handler = getattr(listener, event, None)
            if handler:
                if hasattr(listener, "__before__"):
                    listener.__before__(event)
                handler(*args, **self.flags)

                if hasattr(listener, "__after__"):
                    listener.__after__(event)

            if kwargs.get("reset", True): self.reset()
        else:
            logger.error("no listener set")
