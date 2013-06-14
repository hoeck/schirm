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
import logging
import pkg_resources
import re

import pyte
from pyte.screens import Char, Margins, Cursor
from pyte import modes as mo, graphics as g, charsets as cs, control as ctrl

logger = logging.getLogger(__name__)

# id for the iframe modes:
# ``ESC [ ?`` <mode-id> ( ``;`` <arg> )* ``h``
# all writes go to an iframe
IFRAME_DOCUMENT_MODE_ID = 5151
# cgi-like interface to respond to a previous iframes http requests
IFRAME_RESPONSE_MODE_ID = 5152

# create an explicit interface to Lines and the seq of Lines to be
# able to create better js dom-update instructions

class Line(UserList):
    """
    A line of characters
    """

    # this is not a valid list ctor, so do not use list methods that
    # copy the current list like splice ([:]) assignment
    def __init__(self, size, default_char):
        self.size = size
        self.default_char = default_char
        self.changed = False # empty lines are rendered lazily
        self.data = [] # UserList data attribute
        # if set to a number, render a cursor block on this line at
        # the given position:
        self.cursorpos = None
        # the kind of cursor to render, either 'cursor' or 'cursor-inactive'
        # set in self.show_cursor()
        self.cursorclass = ''

    def modified(self, linecontainer, real_line_index):
        """Mark this line as modified."""
        # try limiting the amount of modify events by not adding consecutive duplicates
        if linecontainer.events:
            last_ev = linecontainer.events[-1]
            if last_ev[0] == 'modify' \
                    and last_ev[1] == real_line_index \
                    and last_ev[2] is self:
                # skip consecutive modify events of the same line
                return
            elif last_ev[0] == 'append' \
                    and last_ev[1] is self:
                # skip append - modify sequences
                # event though append receives an empty line, at
                # rendering time, it will be rendered with the full
                # lines contents, this works because each events keeps
                # a reference to the line instead of only its value.
                return

        linecontainer.events.append(('modify', real_line_index, self))

    def is_empty(self):
        return (not self.cursorpos) \
            and ((not self.data) or all(c == self.default_char for c in self.data))

    def set_size(self, size):
        """ set the size in columns for this line """
        #self.changed = True
        #if size > self.size:
        #    self.extend([self.default_char] * (size - self.size))
        self.size = size

    def _ensure_size(self, pos=None):
        """Ensure that this line is filled with at least pos default char characters.

        pos defaults to self.size."""
        if pos == None:
            pos = self.size

        missing_chars = 1 + pos - len(self)
        if missing_chars > 0:
            self.data.extend([self.default_char] * missing_chars)

    def reverse(self):
        """ swap foreground and background for each character """
        self._ensure_size()
        self.changed = True
        for char in self.data:
            char._replace(reverse=True)

    def insert_characters(self, pos, count, char):
        """
        Inserts count chars at pos and moves existing chars to the left.
        (see Screen insert_characters)
        """
        self._ensure_size(min(pos + count, self.size))
        self.changed = True
        self.data[pos:pos] = [char] * count

        # trim the line to its size
        self.data = self.data[:self.size]

    def replace_character(self, pos, char):
        """Set character at pos to char."""
        self._ensure_size(pos)
        self.changed = True
        self.data[pos] = char

    def replace_characters(self, pos, chars):
        """Set all characters beginning at pos to chars."""
        self._ensure_size(pos)
        self.changed = True
        self.data[pos:pos+len(chars)] = chars

    def delete_characters(self, pos, count, char):
        """
        Delete count characters at pos, characters after pos move left.
        Use char to fill holes at the end of the line.
        """
        self._ensure_size()
        self.changed = True
        self.data[pos:pos+count] = []
        self.data[len(self.data):] = [char] * (self.size - len(self.data))

    def erase_characters(self, pos, count, char):
        """ Replace count characters beginning at pos with char. """
        self._ensure_size(pos + count)
        self.changed = True
        end = min(pos + count, self.size)
        self.data[pos:end] = [char] * (end-pos)

    def erase_in_line(self, type_of, pos, char):
        """ implements Screen.erase_in_line for a Line. """
        self.changed = True

        start, end, ensure_size = (
            # a) erase from the cursor to the end of line, including
            # the cursor,
            (pos, self.size, lambda: self._ensure_size()),
            # b) erase from the beginning of the line to the cursor,
            # including it,
            (0, pos + 1, lambda: self._ensure_size(pos+1)),
            # c) erase the entire line.
            (0, self.size, lambda: self._ensure_size()),
        )[type_of]

        ensure_size()
        self.data[start:end] = [char] * (end-start)

    def show_cursor(self, cursorpos, cursorclass):
        """Show the cursor on this line at cursorpos using cursorclass."""
        self._ensure_size(cursorpos)
        self.changed = True
        self.cursorpos = cursorpos
        self.cursorclass = cursorclass

    def hide_cursor(self):
        """Turn off the cursor on this line."""
        self.changed = True
        self.cursorpos = None

    def __repr__(self):
        return "#<Line %s:%s>" % (hex(id(self)), repr(''.join(c.data for c in self)))

class IframeLine(Line):

    def __init__(self, id):
        """
        Create an IframeLine.
        Id must be a unique identifier to be able to map webview requests to iframes.
        Args is a list of strings, interpreted as a dictionary used to set options:
          width, height: width/height of the iframe
            defaults: width='100%', height='auto'
            possible values:
              '100%': make the iframe as large as the schirm window in this dimension
              'auto': resize the iframe whenever its content changes
        """
        self.id = id
        self.changed = False
        self.cursorpos = None
        self.cursorclass = None

    def modified(self, linecontainer, index):
        pass

    def is_empty(self):
        return False

    def set_size(self, size):
        pass

    def reverse(self):
        pass

    def insert_characters(self, pos, count, char):
        pass

    def replace_character(self, pos, char):
        pass

    def replace_characters(self, pos, chars):
        pass

    def delete_characters(self, pos, count, char):
        pass

    def erase_characters(self, pos, count, char):
        pass

    def erase_in_line(self, type_of, pos, char):
        pass

    def show_cursor(self, cursorpos, cursorclass):
        # showing the cursor on an iframe line could be rendered
        # by highlighting the iframe?
        pass

    def hide_cursor(self):
        pass


class LineContainer(): # lazy

    """The LineContainer provides an array-like interface for the TermScreen
    and translates calls to it into a stream of events digestible by the
    browser interface implemented in term.js.
    """

    def __init__(self, create_line_fn):
        # the real initialization happens in self.reset()
        self.height = 0
        # index into self.lines where the screen starts
        # everything < screen0 is the terminal history
        # without lazy line rendering, screen0 would
        # be defined by: len(lines) - height
        self.screen0 = 0
        self.lines  = []
        # list of events (tuples) describing changes (line
        # insertions, changes, cursor movement ..)
        self.events = []
        self._create_line_fn = create_line_fn

    def _create_line(self, default_char=None):
        return self._create_line_fn(default_char)

    def _ensure_lines(self, _linenumber=None):
        """Ensure that all lines up to linenumber are present."""
        if _linenumber == None:
            linenumber = self.height-1
        else:
            linenumber = _linenumber

        missing_lines =  1 + linenumber - (len(self.lines) - self.screen0)

        for i in range(missing_lines):
            # must issue an append event for each appended line
            self._append(self._create_line())

    def real_line_index(self, i):
        """Given a linenumber i, return the index into self.lines."""
        return self.screen0 + i

    def get_and_clear_events(self):
        ret = self.events
        self.events = []
        return ret

    def append_events(self, events):
        self.events.extend(events)

    def alt_buffer_mode(self, enable=False):
        self.events.append(('alt_buffer_mode', enable))

    def reset(self, height):
        self.height = height # height of the terminal screen in lines
        self.set_screen0(0)
        self.lines = [] # a list of Line objects, created lazily
        self.events.append(('reset',))

    def pop(self, index):
        """Remove the line at terminal screen lineumber index."""
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        line = self.lines.pop(ri)
        self.events.append(('pop', ri, line))
        return line

    def _append(self, line):
        """Append line to self.lines and generate an appropriate event.
        Do mess with screen0.
        """
        self.lines.append(line)
        line.changed = False
        self.events.append(('append', line))

    def append(self, line):
        """Append an empty line to the bottom of the terminal screen."""
        # is line always empty?
        self._ensure_lines()
        if (len(self.lines) - self.screen0) >= self.height:
            # if there are already height lines visible, move the
            # topmost visible line pointer

            # propagate=False explanation:
            # If each line is only appended to the terminal screen,
            # there is no need to set the screen0 pointer for every
            # append operation. Screen0 is only required to determine
            # the top of the terminal window within the list of lines,
            # so setting it (and computing all the proper offsets to
            # hide the scrollback and find the first real line) can be
            # deferred to the client unless we really need it
            # (e.g. for a pop operation).
            self.set_screen0(self.screen0 + 1, propagate=False)

        self._append(line)

    def insert(self, index, line):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        self.lines.insert(ri, line)
        line.changed = False
        self.events.append(('insert', ri, line))

    def __getitem__(self, index):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        line = self.lines[ri]
        line.modified(self, ri)
        return line

    def __setitem__(self, index, line):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        self.lines[ri] = line
        if isinstance(line, IframeLine):
            self.events.append(('set_iframe', ri, line.id))
        else:
            self.events.append(('set', ri, line))

    def __iter__(self):
        assert False # do we need an __iter__ method?
        self._ensure_lines() # ???
        return self.lines[self.real_line_index(0):].__iter__()

    def resize(self, newheight, newwidth):
        """Resize this container to newheight and all lines to newwidth.

        Return the cursor line change.
        """
        line_delta = newheight - self.height
        remaining_empty_lines = self.height - (len(self.lines) - self.screen0)

        if line_delta < remaining_empty_lines:
            # when resizing and there are empty lines below the last visible line,
            # keep this line in same place (measured from the top of the terminal window)
            cursor_delta = 0
        else:
            screen0 = self.screen0
            self.set_screen0(len(self.lines) - newheight)
            cursor_delta = screen0 - self.screen0

        self.purge_empty_lines()
        self.height = newheight

        # set width for all lines
        # (they could become visible by resizing the terminal again)
        for l in self.lines:
            l.set_size(newwidth)

        return cursor_delta

    def set_title(self, title):
        self.events.append(('set_title', title))

    def purge_empty_lines(self):
        """Remove all consecutive unchanged empty lines from the bottom."""
        i = len(self.lines)
        while True and i>0:
            l = self.lines[-1]
            if (not l.changed) \
                    and l.is_empty() \
                    and i >= self.screen0:
                self.lines.pop()
                # remove at most self.height lines
                # do not remove empty lines from the history
                i += 1
            else:
                return

    def set_screen0(self, screen0, propagate=True):
        self.screen0 = max(0, min(len(self.lines), screen0))
        if propagate:
            # some uses of set_screen0 do not need to also execute
            # this on the client, such as append line, to optimize the
            # performance (by a factor of 10-50x) of printing many
            # lines to the bottom of the terminal (which is a very
            # common case).
            self.events.append(('set_screen0', self.screen0))

    def add_screen0(self, delta):
        self.set_screen0(self.screen0 + delta)

    def erase_in_display(self, cursor_attrs):
        """Implements marginless erase_in_display type 2 preserving the history."""
        # push the current terminal contents to the history
        self.set_screen0(len(self.lines))

    def remove_history(self, lines_to_remove=None):
        """Remove all or the first n lines_to_remove from the history."""
        if lines_to_remove == None:
            n = self.screen0
        else:
            n = min(self.screen0, lines_to_remove)

        self.lines = self.lines[n:]
        self.events.append(('remove_history_lines', n))
        self.set_screen0(self.screen0 - n)

    def close_stream(self):
        self.events.append(('close_stream',))

    ## cursor show and hide events

    def show_cursor(self, linenumber, column, cursorclass='cursor'):
        self[linenumber].show_cursor(column, cursorclass)

    def hide_cursor(self, linenumber):
        self[linenumber].hide_cursor()

    ## iframe events, not directly line-based

    # mode messages

    #   <plain terminal mode>
    # enter -> 'document'
    #   <write document>
    #   <provide static resources>
    # close -> 'response'
    #   <responses>
    # leave -> None
    #   <plain terminal mode>

    def iframe_enter(self, iframe_id):
        self.events.append(('iframe_enter', iframe_id))

    def iframe_close(self, iframe_id):
        self.events.append(('iframe_close', iframe_id))

    def iframe_leave(self, iframe_id):
        self.events.append(('iframe_leave', iframe_id))

    # sending data

    def iframe_write(self, iframe_id, data):
        self.events.append(('iframe_write', iframe_id, data))

    def iframe_string(self, iframe_id, data):
        self.events.append(('iframe_string', iframe_id, data))

    def iframe_resize(self, iframe_id, height):
        self.events.append(('iframe_resize', iframe_id, height))

    # embedded terminals: TODO

    # def iframe_terminal_create(self, iframe_id, terminal_id):
    #     # Create an embedded terminal for the given iframe using the
    #     # given terminal_id as a handle in terminal_writes and
    #     # terminal_responses.
    #     # Free the used terminal responses when the iframe closes.
    #
    #     # self._iframe_id()
    #     # self._embedded_terminals = self.__init__
    #     self.events.append(('iframe_terminal_create', iframe_id, terminal_id))
    #
    # def iframe_terminal_write(self, iframe_id, terminal_id, data):
    #     self.events.append(('iframe_terminal_write', iframe_id, terminal_id, data))

    # example usage
    # with schirmclient.iframe():
    #     # plain iframe-term RPC
    #     term_id = schirmclient.create_terminal()
    #     # ESC R 'terminal_create' ESC Q
    #     # response?:
    #     # ESC R 'terminal_created' ESC ; <term-id> ESC Q
    #     # alternatively, specify the terminal_id when creating the terminal
    #     # client will be responsible to specify a uniqe (per iframe) term-id
    #     # renders the 'terminal_create' response redundant (less complexity)
    #
    #     schirmclient.write("""
    #         <h1>embedded terminal<h1>
    #         <div id="terminal"></div>
    #         <script type=text/javascript>
    #              var term = SchirmTerminal(document.getElementById("terminal"), %(term_id)s);
    #         </script>
    #     """ % term_id);
    #     schirmclient.close()
    #
    #     # write contents to the embedded terminal:
    #     schirmclient.write(term_id, 'hello world')
    #     # ESC R 'terminal_write' ESC ; <term-id> ESC ; <b64-encoded data> ESC Q
    #
    #     # any need to get information from the embedded terminal??
    #     # yes, for iframe content, read via stdin:
    #     # ESC R 'terminal_response' ESC ; <term-id> ESC ; <b64-encoded data> ESC Q


class AltContainer(LineContainer):
    """A simplified Line Container implementation for the DECALTBUF mode."""

    # In this mode, there is no scrollback which simplifies some of
    # the operations.

    # no-scrollback
    #  -> screen0 is always 0
    #  -> real_line_index is not needed
    #  -> rendering is still lazy, so _ensure_lines must be called
    #     prior to each line-array operation

    def pop(self, index):
        """Remove the line at terminal screen lineumber index."""
        self._ensure_lines(index)
        line = self.lines.pop(index)
        self.events.append(('pop', index, line))
        return line

    def append(self, line):
        """Append an empty line to the bottom of the terminal screen."""
        # is line always empty?
        self._ensure_lines()
        if len(self.lines) >= self.height:
            # remove the topmost line to have space to append one line
            self.pop(0)
        self._append(line)

    def insert(self, index, line):
        self._ensure_lines(index)
        # if len(self.lines) >= self.height:
        #     # remove the topmost line to have space to insert one line
        #     self.pop(0)
        self.lines.insert(index, line)
        line.changed = False
        self.events.append(('insert', index, line))

    def resize(self, newheight, newwidth):
        """Resize this container to newheight and all lines to newwidth.

        Return the cursor line change.
        """
        # height
        if self.height > newheight:
            unneeded_lines = max(0, len(self.lines) - newheight)
            if unneeded_lines:
                # remove excessive lines from the top
                for i in range(unneeded_lines):
                    self.pop(0)

        else:
            # increasing the height works 'automatically' through lazy
            # line rendering (additional lines are created on demand)
            pass

        self.height = newheight

        # set width for all lines
        for l in self.lines:
            l.set_size(newwidth)

        return 0

    def erase_in_display(self, cursor_attrs):
        # clear the whole display
        for i, line in enumerate(self.lines):
            # erase the whole line
            line.erase_in_line(2, 0, cursor_attrs)
            line.modified(self, i)

    def remove_history(self, lines_to_remove=None):
        pass

class TermScreen(pyte.Screen):

    def __init__(self, columns, lines):
        self.savepoints = []
        # terminal dimensions in characters
        self.lines, self.columns = lines, columns

        # switch container implementations in self.set_mode and
        # self.reset_mode when the DECALTBUF mode is requested
        self._line_mode_container = LineContainer(self._create_line)
        self._alt_mode_container = AltContainer(self._create_line)
        self.linecontainer = self._line_mode_container

        # current iframe_mode,
        # one of None, 'open' or 'closed'
        # None     .. no active iframe
        # 'open'   .. active iframe which is still being sent data to
        # 'closed' .. active iframe where the initial data has already been sent
        self.iframe_mode = None
        self.iframe_id = None
        self.reset()

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
        delta_lines   = (lines   or self.lines)   - self.lines
        delta_columns = (columns or self.columns) - self.columns

        self.lines   += delta_lines
        self.columns += delta_columns

        if mo.DECALTBUF in self.mode and False:
            # home cursor
            self.reset_mode(mo.DECOM)
        else:
            # cursor: make sure that it 'stays' on its current line
            cursor_delta = self.linecontainer.resize(self.lines, self.columns)
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
            for line in self.linecontainer:
                line.reverse()
            self.select_graphic_rendition(g._SGR["+reverse"])

        # Make the cursor visible.
        if mo.DECTCEM in modes:
            self.cursor.hidden = False

        if mo.DECSAVECUR in modes:
            # save cursor position and restore it on mode reset
            self.save_cursor()

        if mo.DECALTBUF in modes:
            # enable alternative draw buffer, switch internal
            # linecontainer while preserving generated events
            if self.linecontainer is self._line_mode_container:
                events = self.linecontainer.get_and_clear_events()
                self.linecontainer = self._alt_mode_container
                self.linecontainer.append_events(events)
                self.linecontainer.alt_buffer_mode(True)

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
            for line in self.linecontainer:
                line.reverse()
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
            if self.linecontainer is self._alt_mode_container:
                events = self.linecontainer.get_and_clear_events()
                self.linecontainer = self._line_mode_container
                self.linecontainer.append_events(events)
                self.linecontainer.alt_buffer_mode(False)

    # def draw(self, char):
    #     """Display a character at the current cursor position and advance
    #     the cursor if :data:`~pyte.modes.DECAWM` is set.
    #
    #     :param unicode char: a single character or string to display.
    #     """
    #
    #
    #     # Translating a given character.
    #     if self.charset != 0 and 0: # commented out
    #         # somehow, the latin 1 encoding done here is wrong,
    #         # json.dumps does not correctly convert the resulting
    #         # string
    #         char = char.translate([self.g0_charset,
    #                                self.g1_charset][self.charset])
    #
    #     # If this was the last column in a line and auto wrap mode is
    #     # enabled, move the cursor to the next line. Otherwise replace
    #     # characters already displayed with newly entered.
    #     if self.cursor.x == self.columns:
    #         if mo.DECAWM in self.mode:
    #             self.linefeed()
    #         else:
    #             self.cursor.x -= 1
    #
    #     # Drawing on an IframeLine reverts it to a plain text Line.
    #     if isinstance(self.linecontainer[self.cursor.y], IframeLine):
    #         self.linecontainer[self.cursor.y] = self._create_line()
    #
    #     # If Insert mode is set, new characters move old characters to
    #     # the right, otherwise terminal is in Replace mode and new
    #     # characters replace old characters at cursor position.
    #     if mo.IRM in self.mode:
    #         self.insert_characters(1)
    #
    #     self.linecontainer[self.cursor.y] \
    #         .replace_character(self.cursor.x,
    #                            self.cursor.attrs._replace(data=char))
    #
    #     # .. note:: We can't use :meth:`cursor_forward()`, because that
    #     #           way, we'll never know when to linefeed.
    #     self.cursor.x += 1

    def draw_string(self, string):
        """Like draw, but for a whole string at once.

        String MUST NOT contain any control characters like newlines or carriage-returns.
        """

        cur_attrs = self.cursor.attrs[1:]
        def _write_string(s):
            self.linecontainer[self.cursor.y] \
                .replace_characters(self.cursor.x,
                                    #[self.cursor.attrs._replace(data=ch) for ch in s])
                                    [Char(ch, *cur_attrs) for ch in s])

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
            if bottom == self.lines-1:
                # default margin
                self.linecontainer.append(self._create_line())
            else:
                self.linecontainer.insert(bottom+1, self._create_line())
                if top == 0:
                    # surplus lines move the scrollback if no margin is active
                    self.linecontainer.add_screen0(1)
                else:
                    # delete surplus lines to achieve scrolling within in the margins
                    self.linecontainer.pop(top)

        else:
            self.cursor_down()

    def reverse_index(self):
        """Move the cursor up one line in the same column. If the cursor
        is at the first line, create a new line at the top and remove
        the last one, scrolling all lines in between.
        """
        top, bottom = self.margins

        if self.cursor.y == top:
            self.linecontainer.pop(bottom)
            self.linecontainer.insert(top, self._create_line())
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
                self.linecontainer.pop(bottom)
                self.linecontainer.insert(line, self._create_line())

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
                self.linecontainer.pop(self.cursor.y)
                self.linecontainer.insert(bottom, self._create_line(self.cursor.attrs))

            self.carriage_return()

    def insert_characters(self, count=None):
        """Inserts the indicated # of blank characters at the cursor
        position. The cursor does not move and remains at the beginning
        of the inserted blank characters. Data on the line is shifted
        forward.

        :param int count: number of characters to insert.
        """
        count = count or 1

        self.linecontainer[self.cursor.y].insert_characters(self.cursor.x,
                                                            count,
                                                            self.cursor.attrs)

    def delete_characters(self, count=None):
        """Deletes the indicated # of characters, starting with the
        character at cursor position. When a character is deleted, all
        characters to the right of cursor move left. Character attributes
        move with the characters.

        :param int count: number of characters to delete.
        """
        count = count or 1

        self.linecontainer[self.cursor.y].delete_characters(self.cursor.x,
                                                            count,
                                                            self.cursor.attrs)

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

        self.linecontainer[self.cursor.y].erase_characters(self.cursor.x,
                                                           count,
                                                           self.cursor.attrs)

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
        self.linecontainer[self.cursor.y].erase_in_line(type_of,
                                                        self.cursor.x,
                                                        self.cursor.attrs)

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

            for line in interval:
                # erase the whole line
                self.linecontainer[line].erase_in_line(2, 0, self.cursor.attrs)

            # In case of 0 or 1 we have to erase the line with the cursor.
            if type_of in [0, 1]:
                self.erase_in_line(type_of)
        else: # type_of == 2
            # c) erase the whole display ->
            # Push every visible line to the history == add blank
            # lines until all current non-blank lines are above the
            # top of the term window. (thats what xterm does and
            # linux-term not, try using top in both term emulators and
            # see what happens to the history)
            self.linecontainer.erase_in_display(self.cursor.attrs)

        self.linecontainer.purge_empty_lines()

    def string(self, string):
        if self.iframe_mode:
            # in document mode -> 'register resource', debug-message, ...
            # in request mode -> response, send-message, debug-message, ...
            self.linecontainer.iframe_string(self.iframe_id, string)
        else:
            # ignore strings (xterm behaviour) in plain terminal mode
            self.draw_string(string)

    ## cutting the terminal scrollback

    def remove_history(self, lines):
        """Remove the first n lines from the history."""
        self.linecontainer.remove_history(lines)

    ## xterm title hack

    def os_command(self, string):
        res = (string or '').split(';', 1)
        if len(res) == 2:
            command_id, data = res
            if command_id == '0':
                self.linecontainer.set_title(data)

    ## iframe extensions

    def _next_iframe_id(self):
        self.iframe_id = str(int(self.iframe_id or 0) + 1)
        return self.iframe_id

    def _insert_iframe_line(self):
        iframe_id = self._next_iframe_id()
        self.linecontainer.iframe_enter(iframe_id)
        self.linecontainer[self.cursor.y] = IframeLine(iframe_id)

    def _iframe_close_document(self):
        # add some html to the iframe document for registering ctr-c and ctrl-d key handlers
        iframe_close_snippet = pkg_resources.resource_string('schirm.resources', 'iframe_close_snippet.html')
        self.linecontainer.iframe_write(self.iframe_id, iframe_close_snippet)
        self.linecontainer.iframe_close(self.iframe_id)

    def iframe_set_mode(self, mode_id, cookie):
        if mode_id == IFRAME_DOCUMENT_MODE_ID:
            # replace the current line with an iframe line at the current
            # cursor position (like self.index())
            # all following chars are written to the iframes root document connection
            if self.iframe_mode == None:
                self.iframe_mode = 'document'
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
        # disable the cursor
        (screen, _) = self.listeners[0]
        screen.linecontainer.hide_cursor(screen.cursor.y)

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
