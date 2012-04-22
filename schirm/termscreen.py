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
from StringIO import StringIO
import codecs
import base64
import logging

import pyte
from pyte.screens import Char, Margins, Cursor
from pyte import modes as mo, graphics as g, charsets as cs, control as ctrl

# create an explicit interface to Lines and the seq of Lines to be
# able to create better js dom-update instructions
class Line(UserList):
    """
    A line of characters
    """
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

    def is_empty(self):
        return (not self.cursorpos) \
            and ((not self) or all(c == self.default_char for c in self.data))

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
            self.extend([self.default_char] * missing_chars)

    def reverse(self):
        """ swap foreground and background for each character """
        self._ensure_size()
        self.changed = True
        for char in self:
            char._replace(reverse=True)

    def insert_characters(self, pos, count, char):
        """
        Inserts count chars at pos.
        (see Screen insert_characters)
        """
        self._ensure_size(pos + count)
        self.changed = True
        for _ in range(min(self.size - pos, count)):
            self.insert(pos, char)
            self.pop()

    def replace_character(self, pos, char):
        """Set character at pos to char."""
        self._ensure_size(pos)
        self.changed = True
        self[pos] = char

    def replace_characters(self, pos, chars):
        """Set characters at pos..pos+len(chars) to chars."""
        self._ensure_size(pos)
        self.changed = True
        self[pos:pos+len(chars)] = chars

    def delete_characters(self, pos, count, char):
        """
        Delete count characters at pos, characters after pos move left.
        Use char to fill holes at the current end of the line.
        """
        self._ensure_size(pos + count)
        self.changed = True
        for _ in range(min(self.size - pos, count)):
            self.pop(pos)
            self.insert(self.size, char)

    def erase_characters(self, pos, count, char):
        """ Replace count characters beginning at pos with char. """
        self._ensure_size(pos + count)
        self.changed = True
        for p in range(pos, min(pos + count, self.size)):
            self[p] = char

    def erase_in_line(self, type_of, pos, char):
        """ implements Screen.erase_in_line for a Line. """
        self.changed = True

        interval, ensure_size = (
            # a) erase from the cursor to the end of line, including
            # the cursor,
            (range(pos, self.size), lambda: self._ensure_size()),
            # b) erase from the beginning of the line to the cursor,
            # including it,
            (range(0, pos + 1), lambda: self._ensure_size(pos+1)),
            # c) erase the entire line.
            (range(0, self.size), lambda: self._ensure_size()),
        )[type_of]

        ensure_size()

        for column in interval:
            self[column] = char

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


class IframeLine(Line):

    def __init__(self, id, args):
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
        self.args = {'width':'100%', 'height':'auto'}
        self.args.update(dict(args[i:i+2] for i in range(0, len(args), 2)))
        self.id = id
        self.changed = False

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

    def __init__(self, create_line_fn):
        # the real initialization happens in self.reset()
        self.height = 0
        # index into self.lines where the screen starts
        # everything < screen0 is the terminal history
        # without lazy line rendering, screen0 would
        # be defined by: len(lines) - height
        self.screen0 = 0
        self.lines  = []
        # list of events (tuples) sent to the browser
        self.events = []
        self._create_line_fn = create_line_fn

    def _create_line(self):
        return self._create_line_fn()

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

    def get_changed_lines(self):
        """Iterator to get a sequence of all changed lines.

        Return a list of (linenumber, Line).
        """
        return ((i,l) for i, l in enumerate(self.lines[self.screen0:], self.screen0) if l.changed)

    def reset(self, height):
        self.height = height # height of the terminal screen in lines
        self.set_screen0(0)
        self.lines = [] # a list of Line objects, created lazily
        self.events.append(('reset',))

    def pop(self, index):
        """Remove the line at terminal screen linumber index."""
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        if self.screen0 > 0:
            self.set_screen0(self.screen0 - 1)
        line = self.lines.pop(ri)
        self.events.append(('pop', index, line))
        return line

    def pop_bottom(self):
        """Remove a line from the bottom of the terminal screen."""
        self._ensure_lines()
        if self.screen0 > 0:
            self.set_screen(self.screen0 - 1)
        line = self.lines.pop(len(self.lines)-1)
        self.events.append(('pop_bottom',))
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
            self.set_screen0(self.screen0 + 1)
        self._append(line)

    def insert(self, index, line):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        if (len(self.lines) - self.screen0) >= self.height:
            self.set_screen0(self.screen0 + 1)
        self.lines.insert(ri, line)
        line.changed = False
        self.events.append(('insert', ri, line))

    def __getitem__(self, index):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        return self.lines[self.real_line_index(index)]

    def __setitem__(self, index, line):
        self._ensure_lines(index)
        ri = self.real_line_index(index)
        self.lines[ri] = line
        self.events.append(('set', ri, line))

    def __iter__(self):
        self._ensure_lines() # ???
        # do we need an __iter__ method?
        return self.lines[self.real_line_index(0):].__iter__()

    def resize(self, newheight, newwidth):
        """Resize this container to newheight and all lines to newwidth.

        Return the cursor line change.
        """
        # if true, keep lines at the bottom when resizing, otherwise
        # stick them at the top of the terminal window
        grow = bool((len(self.lines) - self.screen0) == self.height)

        if (len(self.lines) > newheight) and grow:
            screen_delta = len(self.lines) - newheight - self.screen0
        else:
            screen_delta = 0

        self.purge_empty_lines()

        # emit a set_screen0 event to force a recomputation of the trailing space
        self.set_screen0(self.screen0 + screen_delta)
        self.height = newheight

        # set width for all lines
        # (they could become visible by resizing the terminal again)
        for l in self.lines:
            l.set_size(newwidth)

        return screen_delta * -1

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
                # do not remove empty lines from the history!
                i += 1
            else:
                return

    def last_nonempty_line(self):
        """Return the linenumber of the last nonempty line of the current screen."""
        for i, l in enumerate(reversed(self.lines[self.screen0:])):
            if not l.is_empty():
                return self.height - i
        return 0

    def set_screen0(self, screen0):
        self.screen0 = screen0
        self.events.append(('set_screen0', self.screen0))

    def erase_in_display(self, cursor_line, cursor_column):
        """Implements marginless erase_in_display type 2 preserving the history."""
        # push the current terminal contents to the history
        self.set_screen0(len(self.lines))
        self.show_cursor(cursor_line, cursor_column)

    def remove_history(self, lines_to_remove=None):
        """Remove all or the first n lines_to_remove from the history."""
        if lines_to_remove == None:
            n = self.screen0
        else:
            n = min(self.screen0, lines_to_remove)

        self.lines = self.lines[n:]
        self.events.append(('remove_history_lines', n))
        self.set_screen0(self.screen0 - n)

    ## cursor show and hide events

    def show_cursor(self, linenumber, column, cursorclass='cursor'):
        self._ensure_lines(linenumber)
        index = self.real_line_index(linenumber)
        line = self.lines[index]
        line.show_cursor(column, cursorclass)
        self.events.append(('set', index, line))

    def hide_cursor(self, linenumber):
        self._ensure_lines(linenumber)
        index = self.real_line_index(linenumber)
        line = self.lines[index]
        line.hide_cursor()
        self.events.append(('set', index, line))

    ## iframe events, not directly line-based

    def iframecharinsert(self, char):
        self.events.append(('iframe', char))

    def iframe_register_resource(self, id, name, mimetype, data):
        self.events.append(('iframe_register_resource', id, name, mimetype, data))

    def iframe_respond(self, name, data):
        self.events.append(('iframe_respond', name, data))

    def iframe_debug(self, data):
        self.events.append(('iframe_debug', data))

    def iframe_close(self):
        self.events.append(('iframe_close', ))

    def iframe_enter(self):
        self.events.append(('iframe_enter', ))

    def iframe_leave(self):
        self.events.append(('iframe_leave', ))

    def iframe_execute(self, source):
        self.events.append(('iframe_execute', source))

    def iframe_eval(self, source):
        self.events.append(('iframe_eval', source))

    def iframe_resize(self, iframe_id, height):
        self.events.append(('iframe_resize', iframe_id, height))


class TermScreen(pyte.Screen):

    def __init__(self, columns, lines):
        self.savepoints = []
        self.lines, self.columns = lines, columns
        self.linecontainer = LineContainer(self._create_line)
        self.iframe_mode = None
        self.iframe_id = None
        self.reset()

    def __before__(self, command):
        pass

    def __after__(self, command):
        pass

    _default_char = Char(data=" ", fg="default", bg="default")
    def _create_line(self):
        return Line(self.columns, self._default_char)

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

        cursor_delta = self.linecontainer.resize(self.lines, self.columns)

        # cursor: make sure that it 'stays' on its current line
        self.cursor.y = min(max(self.cursor.y + cursor_delta, 0), self.lines-1)
        self.cursor.x = min(max(self.cursor.x, 0), self.columns-1)

        self.margins = Margins(0, self.lines - 1)

    def set_mode(self, *modes, **kwargs):
        """Sets (enables) a given list of modes.

        :param list modes: modes to set, where each mode is a constant
                           from :mod:`pyte.modes`.
        """
        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = [mode << 5 for mode in modes]

        self.mode.update(modes)

        if mo.DECAPP in modes:
            # application mode set
            # todo: implement event so that we can switch to/from appmode
            # in term.html
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

    def _application_mode(self):
        return mo.DECAPP in self.modes

    def reset_mode(self, *modes, **kwargs):
        """Resets (disables) a given list of modes.

        :param list modes: modes to reset -- hopefully, each mode is a
                           constant from :mod:`pyte.modes`.
        """
        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = [mode << 5 for mode in modes]

        self.mode.difference_update(modes)

        if mo.DECAPP in modes:
            pass

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

    def draw(self, char):
        """Display a character at the current cursor position and advance
        the cursor if :data:`~pyte.modes.DECAWM` is set.

        :param unicode char: a character to display.
        """
        # Translating a given character.
        if self.charset != 0 and 0: # commented out
            # somehow, the latin 1 encoding done here is wrong,
            # json.dumps does not correctly convert the resulting
            # string
            char = char.translate([self.g0_charset,
                                   self.g1_charset][self.charset])

        # If this was the last column in a line and auto wrap mode is
        # enabled, move the cursor to the next line. Otherwise replace
        # characters already displayed with newly entered.
        if self.cursor.x == self.columns:
            if mo.DECAWM in self.mode:
                self.linefeed()
            else:
                self.cursor.x -= 1

        # Drawing on an IframeLine reverts it to a plain text Line.
        if isinstance(self.linecontainer[self.cursor.y], IframeLine):
            self.linecontainer[self.cursor.y] = self._create_line()

        # If Insert mode is set, new characters move old characters to
        # the right, otherwise terminal is in Replace mode and new
        # characters replace old characters at cursor position.
        if mo.IRM in self.mode:
            self.insert_characters(1)

        self.linecontainer[self.cursor.y] \
            .replace_character(self.cursor.x,
                               self.cursor.attrs._replace(data=char))

        # .. note:: We can't use :meth:`cursor_forward()`, because that
        #           way, we'll never know when to linefeed.
        self.cursor.x += 1

    def draw_string(self, string):
        """Like draw, but for a whole string at once."""

        cur_attrs = self.cursor.attrs[1:]
        def _write_string(s):
            self.linecontainer[self.cursor.y] \
                .replace_characters(self.cursor.x,
                                    #[self.cursor.attrs._replace(data=ch) for ch in s])
                                    [Char(ch, *cur_attrs) for ch in s])

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
            return

        top, bottom = self.margins
        if self.cursor.y == bottom:
            if bottom == self.lines-1:
                self.linecontainer.append(self._create_line())
            else:
                self.linecontainer.insert(bottom+1, self._create_line())
        else:
            self.cursor_down()

    def reverse_index(self):
        """Move the cursor up one line in the same column. If the cursor
        is at the first line, create a new line at the top.
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
            #                           v +1, because range() is exclusive.
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
            # see what
            # happens to the history)
            top, bottom = self.margins # where to use them?: ans: in linecontainer as an argument to insert, pop and append
            if top == 0 and bottom == self.lines - 1:
                self.linecontainer.erase_in_display(self.cursor.y, self.cursor.x)
            else:
                assert False, "erase_in_display not implemented for margins"

        self.linecontainer.purge_empty_lines()

    ## xterm title hack

    def os_command(self, command_id, data):
        if command_id == 0:
            self.linecontainer.set_title(data)

    ## iframe extensions

    def get_next_iframe_id(self):
        return (self.iframe_id or 0) + 1;

    def iframe_enter(self, *args):
        # replace the current line with an iframe line at the current
        # cursor position (like self.index())
        # all following chars are written to that frame via
        # iframe.document.write
        # TODO: replace document.open/write/close by writing all chars
        #       to this iframe using an http connection
        # For arguments, see IframeLine

        if self.iframe_mode == None:
            self.linecontainer.iframe_enter()
            self.iframe_id = self.get_next_iframe_id()
            self.linecontainer[self.cursor.y] = IframeLine(str(self.iframe_id), args)
            self.iframe_mode = 'open' # iframe document opened
        elif self.iframe_mode == 'closed':
            self.iframe_mode = 'open'
        elif self.iframe_mode == 'open':
            pass
        else:
            raise Exception("Illegal iframe_mode: '{}'".format(self.iframe_mode))

    def iframe_leave(self):
        self.linecontainer.iframe_leave()
        self.iframe_mode = None

    def iframe_write(self, char):
        if self.iframe_mode == 'open':
            self.linecontainer.iframecharinsert(char)
        else:
            # ignore all writes to closed documents:
            # those are echo writes of input to the terminal
            pass

    def iframe_close(self):
        self.linecontainer.iframe_close()
        self.iframe_mode = 'closed'

    def iframe_register_resource(self, name_b64, mimetype_b64, data_b64):
        name = base64.b64decode(name_b64)
        data = base64.b64decode(data_b64)
        mimetype = base64.b64decode(mimetype_b64)
        self.linecontainer.iframe_register_resource(str(self.iframe_id), name, mimetype, data)

    def iframe_respond(self, request_id, data_b64):
        """
        Respond to the request identified by request_id.
        data_b64 is the full, base64 encoded response data, includung
        HTTP status line, headers and data.
        """
        data = base64.b64decode(data_b64)
        self.linecontainer.iframe_respond(request_id, data)

    def iframe_debug(self, b64_debugmsg):
        """
        Write a string to sys stdout of the emulator process.
        """
        data = base64.b64decode(b64_debugmsg)
        self.linecontainer.iframe_debug(data)

    def iframe_execute(self, b64_source):
        source = base64.b64decode(b64_source)
        self.linecontainer.iframe_execute(source)

    def iframe_eval(self, b64_source):
        source = base64.b64decode(b64_source)
        self.linecontainer.iframe_eval(source)

    def remove_history(self, lines):
        """Remove the first n lines from the history."""
        self.linecontainer.remove_history(lines)


class SchirmStream(pyte.Stream):

    def __init__(self, *args, **kwargs):
        super(SchirmStream, self).__init__(*args, **kwargs)
        self.handlers.update({
                'iframe_write': self._iframe_write,
                'iframe_data': self._iframe_data,
                'iframe_data_esc': self._iframe_data_esc,
                'iframe_esc': self._iframe_esc,
                'escape': self._escape,
                })
        self._draw_buffer = []

    def feed(self, bytes):
        """
        Like feed() but directly use a stream and do not return until
        everything has been read.
        """
        chunksize = 8192
        src = bytes.decode('utf-8', 'ignore')
        i = 0
        l = len(src)
        while i < l:
            if self.state == 'iframe_data':
                # shortcut for iframe data to be able to
                # transmit large requests faster
                chunk = src[i:i+chunksize]
                esc_idx = chunk.find("\033")
                if esc_idx == -1:
                    # no escape commands in chunk, just lots of b64 data
                    self.current.append(chunk)
                    i += chunksize
                else:
                    # fallback to normal state machine
                    self.current.append(chunk[:esc_idx])
                    i += esc_idx
                    self.consume(src[i])
                    i += 1
            elif self.state == 'iframe_write':
                # short-circuit the state machine for iframe_writes
                chunk = src[i:i+chunksize]
                esc_idx = chunk.find("\033")
                if esc_idx == -1:
                    # no escape commands in chunk
                    self._iframe_write(chunk)
                    i += chunksize
                else:
                    # write the escape-free chars
                    self._iframe_write(chunk[:esc_idx])
                    # and continue parsing the rest
                    i += esc_idx
                    self.consume(src[i])
                    i += 1
            else:
                char = src[i]
                if char:
                    self.consume(char)
                    i += 1
                else:
                    break
        self._flush_draw()

    def consume(self, char):
        # same as super(SchirmStream, self).consume(char) bit without
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
            if kwargs.get("iframe", False): self.state = 'iframe_write'
        else:
            logging.warn("no listener set")


    # State transformers.
    # ...................

    def _flush_draw(self):
        if self._draw_buffer:
            self.dispatch('draw_string', "".join(self._draw_buffer))
            self._draw_buffer = []

    def _buf_draw(self, char):
        self._draw_buffer.append(char)

    def _stream(self, char):
        """Process a character when in the default ``"stream"`` state."""
        if char in self.basic:
            self._flush_draw()
            self.dispatch(self.basic[char])
        elif char == ctrl.ESC:
            self._flush_draw()
            self.state = "escape"
        elif char == ctrl.CSI:
            self._flush_draw()
            self.state = "arguments"
        elif char not in [ctrl.NUL, ctrl.DEL]:
            #self.dispatch("draw", char)
            self._buf_draw(char)

    # - ESC x leave iframe mode, interpreted at any time, ignored when
    #   not in iframe mode
    # - ESC R register-resource ESC ; <base64-encoded-resource-name> ESC ; <b64-encoded-mimetype> ESC ; <b64-encoded-data> ESC Q
    #   Register a given resource to be served to the webkit view upon
    #   request. Content-Type is determined by examining name (a file name).
    def _escape(self, char, **kwargs):
        """Like pyte.Stream._escape, but additionally capture all
        iframe commands: ESC R *args.
        """
        if char == "R":
            self.state = "iframe_data" # go read a list of strings
            self.current = []
        elif char == 'x':
            # leave iframe mode immediately/ignore this command
            self.dispatch('iframe_leave')
        else:
            super(SchirmStream, self)._escape(char)

    def _iframe_esc(self, char):
        if char == "R": # read a command
            self.state = 'iframe_data'
            self.current = []
        elif char == 'x':
            self.dispatch('iframe_leave')
        elif char == "\033":
            self.dispatch('iframe_write', "\033", iframe=True)
        else:
            # leave the iframe mode on invalid commands
            logging.debug("Invalid Iframe Mode Command: ESC {} ({})".format(char, ord(char)))
            self.dispatch('iframe_leave')

    def _iframe_data(self, char):
        """Decode an iframe command. These start with ESC R followed
           by a name followed by b64 argument data (may be empty)
           followed by ESC ; for more arguments or ESC Q to end the
           iframe command.
        """
        if char == '\033':
            self.state = "iframe_data_esc"
        else:
            self.current.append(char)

    def _iframe_data_esc(self, char):
        if char == ";":
            # read another argument
            self.params.append("".join(self.current))
            self.current = []
            self.state = 'iframe_data'
        elif char == "x":
            # immediately leave iframe mode and ignore the current
            # command
            self.dispatch('iframe_leave')
        elif char == "Q":
            # end parameter transmission and dispatch
            self.params.append("".join(self.current))
            # todo: check for valid commands
            cmd = "iframe_{}".format(self.params[0])
            args = self.params[1:]
            self.current = []
            self.dispatch(cmd, *args, iframe=True)
        else:
            logging.debug("Unknown escape sequence in iframe data: ESC-{}".format(repr(char)))

    def _iframe_write(self, char):
        """Read a normal char or string and write it to an iframe
        using document.write().  Advance state to 'escape' if an ESC
        is found.
        """
        if char == "\033":
            self.state = 'iframe_esc'
        else:
            self.dispatch('iframe_write', char, iframe=True)
