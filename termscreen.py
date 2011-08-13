
from UserList import UserList

import pyte
from pyte.screens import Char, Margins, Cursor
from pyte import modes as mo, graphics as g, charsets as cs


# create an explicit interface to Lines and the seq of Lines to be
# able to create better js dom-update instructions

class Line(UserList):
    """
    A line of characters
    """
    # Later, add an iframe line implementation
  
    def __init__(self, size, default_char):
        self.size = size
        self.default_char = default_char
        self.data = [self.default_char] * self.size
        self.changed = True

    def set_size(self, size):
        """ set the size in columns for this line """
        self.changed = True
        if size > self.size:
            self.extend([self.default_char] * (size - self.size))

        self.size = size

    def reverse(self):
        """ swap foreground and background for each character """
        self.changed = True
        for char in self:
            char._replace(reverse=True)

    def insert_characters(self, pos, count, char):
        """ 
        Inserts count chars at pos.
        (see Screen insert_characters)
        """
        self.changed = True
        for _ in range(min(self.size - pos, count)):
            self.insert(pos, char)
            self.pop()

    def replace_character(self, pos, char):
        self.changed = True
        self[pos] = char

    def delete_characters(self, pos, count, char):
        """
        Delete count characters at pos, characters after pos move left.
        Use char to fill holes at the current end of the line.
        """
        self.changed = True
        for _ in range(min(self.size - pos, count)):
            self.pop(pos)
            self.insert(self.size, char)

    def erase_characters(self, pos, count, char):
        """ Replace count characters beginning at pos with char. """
        self.changed = True
        for p in range(pos, min(pos + count, self.size)):
            self[p] = char

    def erase_in_line(self, type_of, pos, char):
        """ implements Screen.erase_in_line for a Line. """
        self.changed = True

        interval = (
            # a) erase from the cursor to the end of line, including
            # the cursor,
            range(pos, self.size),
            # b) erase from the beginning of the line to the cursor,
            # including it,
            range(0, pos + 1),
            # c) erase the entire line.
            range(0, self.size)
        )[type_of]

        for column in interval:
            self[column] = char


class LineContainer():
    
    def __init__(self):
        self.events = []

    def get_and_clear_events(self):
        ret = self.events
        self.events = []
        return ret

    def reset(self, lines):
        self.lines = lines # a list of Line objects
        for l in lines:
            l.changed = False
        self.events.append(('reset', lines))

    def pop(self, index):
        ret = self.lines.pop(index)
        self.events.append(('pop', index))
        return ret

    def append(self, line):
        self.lines.append(line)
        line.changed = False
        self.events.append(('append', line))

    def insert(self, index, line):
        self.lines.insert(index, line)
        line.changed = False
        self.events.append(('insert', index, line))

    def __getitem__(self, index):
        return self.lines[index]

    def __iter__(self):
        return self.lines.__iter__()
    

# highlight-regexp:
# self\(\.extend\|\.append\|\.pop\|\.insert\|\.remove\|\[.*\]\)

class TermScreen(pyte.Screen):

    def __init__(self, columns, lines):
        self.savepoints = []
        self.lines, self.columns = lines, columns
        self.linecontainer = LineContainer()
        self.reset()

    def __before__(self, command):
        pass

    def __after__(self, command):
        pass

    def _create_line(self, default_char=Char(data=" ", fg="default", bg="default")):
        return Line(self.columns, default_char)

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
        # self[:] = (take(self.columns, self.default_line)
        #            for _ in range(self.lines))
        #self[:] = (self._create_line() for _ in range(self.lines))
        lines = [self._create_line() for _ in range(self.lines)]
        self.linecontainer.reset(lines)

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
        """Resize the screen to the given dimensions.

        If the requested screen size has more lines than the existing
        screen, lines will be added at the bottom. If the requested
        size has less lines than the existing screen lines will be
        clipped at the top of the screen. Similarly, if the existing
        screen has less columns than the requested screen, columns will
        be added at the right, and if it has more -- columns will be
        clipped at the right.

        .. note:: According to `xterm`, we should also reset origin
                  mode and screen margins, see ``xterm/screen.c:1761``.

        :param int lines: number of lines in the new screen.
        :param int columns: number of columns in the new screen.
        """
        lines = lines or self.lines
        columns = columns or self.columns

        # First resize the lines:
        diff = self.lines - lines

        # a) if the current display size is less than the requested
        #    size, add lines to the bottom.
        if diff < 0:
            # self.extend(take(self.columns, self.default_line)
            #             for _ in range(diff, 0))
            #self.extend(self._create_line() for _ in range(diff, 0))
            for _ in range(diff, 0):
                self.linecontainer.append(self._create_line())

        # b) if the current display size is greater than requested
        #    size, take lines off the top.
        elif diff > 0:
            # self[:diff] = ()
            #[self.pop(0) for _ in range(diff)]
            for _ in range(diff):
                self.linecontainer.pop(0)

        # Then resize the columns:
        for line in self.linecontainer:
            line.set_size(columns)

        # diff = self.columns - columns

        # a) if the current display size is less than the requested
        #   size, expand each line to the new size.
        #if diff < 0:
        #    for y in range(lines):
        #        self[y].extend(take(abs(diff), self.default_line))
        # b) if the current display size is greater than requested
        #    size, trim each line from the right to the new size.
        #elif diff > 0:
        #    self[:] = (line[:columns] for line in self)

        self.lines, self.columns = lines, columns
        self.margins = Margins(0, self.lines - 1)
        self.reset_mode(mo.DECOM)

#    def set_margins(self, top=None, bottom=None):
#        """Selects top and bottom margins for the scrolling region.
#
#        Margins determine which screen lines move during scrolling
#        (see :meth:`index` and :meth:`reverse_index`). Characters added
#        outside the scrolling region do not cause the screen to scroll.
#
#        :param int top: the smallest line number that is scrolled.
#        :param int bottom: the biggest line number that is scrolled.
#        """
#        if top is None or bottom is None:
#            return
#
#        # Arguments are 1-based, while :attr:`margins` are zero based --
#        # so we have to decrement them by one. We also make sure that
#        # both of them is bounded by [0, lines - 1].
#        top = max(0, min(top - 1, self.lines - 1))
#        bottom = max(0, min(bottom - 1, self.lines - 1))
#
#        # Even though VT102 and VT220 require DECSTBM to ignore regions
#        # of width less than 2, some programs (like aptitude for example)
#        # rely on it. Practicality beats purity.
#        if bottom - top >= 1:
#            self.margins = Margins(top, bottom)
#
#            # The cursor moves to the home position when the top and
#            # bottom margins of the scrolling region (DECSTBM) changes.
#            self.cursor_position()
#
#    def set_charset(self, code, mode):
#        """Set active ``G0`` or ``G1`` charset.
#
#        :param unicode code: character set code, should be a character
#                             from ``"B0UK"`` -- otherwise ignored.
#        :param unicode mode: if ``"("`` ``G0`` charset is set, if
#                             ``")"`` -- we operate on ``G1``.
#
#        .. warning:: User-defined charsets are currently not supported.
#        """
#        print(code, code in cs.MAPS, cs.MAPS.keys())
#        if code in cs.MAPS:
#            setattr(self, {"(": "g0_charset", ")": "g1_charset"}[mode],
#                    cs.MAPS[code])

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
            # self[:] = ([char._replace(reverse=True) for char in line]
            #            for line in self)
            for line in self.linecontainer:
                line.reverse()
            self.select_graphic_rendition(g._SGR["+reverse"])

        # Make the cursor visible.
        if mo.DECTCEM in modes:
            self.cursor.hidden = False

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

        # Lines below follow the logic in :meth:`set_mode`.
        if mo.DECCOLM in modes:
            self.resize(columns=80)
            self.erase_in_display(2)
            self.cursor_position()

        if mo.DECOM in modes:
            self.cursor_position()

        if mo.DECSCNM in modes:
            # self[:] = ([char._replace(reverse=False) for char in line]
            #            for line in self)
            for line in self.linecontainer:
                line.reverse()
            self.select_graphic_rendition(g._SGR["-reverse"])

        # Hide the cursor.
        if mo.DECTCEM in modes:
            self.cursor.hidden = True

#    def shift_in(self):
#        """Activates ``G0`` character set."""
#        self.charset = 0
#
#    def shift_out(self):
#        """Activates ``G1`` character set."""
#        self.charset = 1

    def draw(self, char):
        """Display a character at the current cursor position and advance
        the cursor if :data:`~pyte.modes.DECAWM` is set.

        :param unicode char: a character to display.
        """
        # Translating a given character.
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

        # If Insert mode is set, new characters move old characters to
        # the right, otherwise terminal is in Replace mode and new
        # characters replace old characters at cursor position.
        if mo.IRM in self.mode:
            self.insert_characters(1)

        # self[self.cursor.y][self.cursor.x] = self.cursor.attrs \
        #     ._replace(data=char)
        self.linecontainer[self.cursor.y] \
            .replace_character(self.cursor.x,
                               self.cursor.attrs._replace(data=char))

        # .. note:: We can't use :meth:`cursor_forward()`, because that
        #           way, we'll never know when to linefeed.
        self.cursor.x += 1

#    def carriage_return(self):
#        """Move the cursor to the beginning of the current line."""
#        self.cursor.x = 0

    def index(self):
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        top, bottom = self.margins

        if self.cursor.y == bottom:
            self.linecontainer.pop(top)
            #self.insert(bottom, take(self.columns, self.default_line))
            self.linecontainer.insert(bottom, self._create_line())
        else:
            self.cursor_down()

    def reverse_index(self):
        """Move the cursor up one line in the same column. If the cursor
        is at the first line, create a new line at the top.
        """
        top, bottom = self.margins

        if self.cursor.y == top:
            self.linecontainer.pop(bottom)
            #self.insert(top, take(self.columns, self.default_line))
            self.linecontainer.insert(top, self._create_line())
        else:
            self.cursor_up()

#    def linefeed(self):
#        """Performs an index and, if :data:`~pyte.modes.LNM` is set, a
#        carriage return.
#        """
#        self.index()
#
#        if mo.LNM in self.mode:
#            self.carriage_return()
#
#    def tab(self):
#        """Move to the next tab space, or the end of the screen if there
#        aren't anymore left.
#        """
#        for stop in sorted(self.tabstops):
#            if self.cursor.x < stop:
#                column = stop
#                break
#        else:
#            column = self.columns - 1
#
#        self.cursor.x = column
#
#    def backspace(self):
#        """Move cursor to the left one or keep it in it's position if
#        it's at the beginning of the line already.
#        """
#        self.cursor_back()
#
#    def save_cursor(self):
#        """Push the current cursor position onto the stack."""
#        self.savepoints.append(Savepoint(copy.copy(self.cursor),
#                                         self.g0_charset,
#                                         self.g1_charset,
#                                         self.charset,
#                                         mo.DECOM in self.mode,
#                                         mo.DECAWM in self.mode))
#
#    def restore_cursor(self):
#        """Set the current cursor position to whatever cursor is on top
#        of the stack.
#        """
#        if self.savepoints:
#            savepoint = self.savepoints.pop()
#
#            self.g0_charset = savepoint.g0_charset
#            self.g1_charset = savepoint.g1_charset
#            self.charset = savepoint.charset
#
#            if savepoint.origin:
#                self.set_mode(mo.DECOM)
#            if savepoint.wrap:
#                self.set_mode(mo.DECAWM)
#
#            self.cursor = savepoint.cursor
#            self.ensure_bounds(use_margins=True)
#        else:
#            # If nothing was saved, the cursor moves to home position;
#            # origin mode is reset. :todo: DECAWM?
#            self.reset_mode(mo.DECOM)
#            self.cursor_position()

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
                #self.insert(line, take(self.columns, self.default_line))
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
                # self.insert(bottom, list(
                #     repeat(self.cursor.attrs, self.columns)))
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

        # for _ in range(min(self.columns - self.cursor.x, count)):
        #     self[self.cursor.y].insert(self.cursor.x, self.cursor.attrs)
        #     self[self.cursor.y].pop()
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

        # for _ in range(min(self.columns - self.cursor.x, count)):
        #     self[self.cursor.y].pop(self.cursor.x)
        #     self[self.cursor.y].append(self.cursor.attrs)
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

        # for column in range(self.cursor.x,
        #                     min(self.cursor.x + count, self.columns)):
        #     self[self.cursor.y][column] = self.cursor.attrs
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
        :param bool private: when ``True`` character attributes aren left
                             unchanged **not implemented**.
        """
        # interval = (
        #     # a) erase from the cursor to the end of line, including
        #     # the cursor,
        #     range(self.cursor.x, self.columns),
        #     # b) erase from the beginning of the line to the cursor,
        #     # including it,
        #     range(0, self.cursor.x + 1),
        #     # c) erase the entire line.
        #     range(0, self.columns)
        # )[type_of]

        # for column in interval:
        #     self[self.cursor.y][column] = self.cursor.attrs
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
        interval = (
            # a) erase from cursor to the end of the display, including
            # the cursor,
            range(self.cursor.y + 1, self.lines),
            # b) erase from the beginning of the display to the cursor,
            # including it,
            range(0, self.cursor.y),
            # c) erase the whole display.
            range(0, self.lines)
        )[type_of]

        for line in interval:
            # self[line][:] = \
            #     (self.cursor.attrs for _ in range(self.columns))
            # erase the whole line
            self.linecontainer[line].erase_in_line(2, 0, self.cursor.attrs)

        # In case of 0 or 1 we have to erase the line with the cursor.
        if type_of in [0, 1]:
            self.erase_in_line(type_of)
#
#    def set_tab_stop(self):
#        """Sest a horizontal tab stop at cursor position."""
#        self.tabstops.add(self.cursor.x)
#
#    def clear_tab_stop(self, type_of=None):
#        """Clears a horizontal tab stop in a specific way, depending
#        on the ``type_of`` value:
#
#        * ``0`` or nothing -- Clears a horizontal tab stop at cursor
#          position.
#        * ``3`` -- Clears all horizontal tab stops.
#        """
#        if not type_of:
#            # Clears a horizontal tab stop at cursor position, if it's
#            # present, or silently fails if otherwise.
#            self.tabstops.discard(self.cursor.x)
#        elif type_of == 3:
#            self.tabstops = set()  # Clears all horizontal tab stops.
#
#    def ensure_bounds(self, use_margins=None):
#        """Ensure that current cursor position is within screen bounds.
#
#        :param bool use_margins: when ``True`` or when
#                                 :data:`~pyte.modes.DECOM` is set,
#                                 cursor is bounded by top and and bottom
#                                 margins, instead of ``[0; lines - 1]``.
#        """
#        if use_margins or mo.DECOM in self.mode:
#            top, bottom = self.margins
#        else:
#            top, bottom = 0, self.lines - 1
#
#        self.cursor.x = min(max(0, self.cursor.x), self.columns - 1)
#        self.cursor.y = min(max(top, self.cursor.y), bottom)
#
#    def cursor_up(self, count=None):
#        """Moves cursor up the indicated # of lines in same column.
#        Cursor stops at top margin.
#
#        :param int count: number of lines to skip.
#        """
#        self.cursor.y -= count or 1
#        self.ensure_bounds(use_margins=True)
#
#    def cursor_up1(self, count=None):
#        """Moves cursor up the indicated # of lines to column 1. Cursor
#        stops at bottom margin.
#
#        :param int count: number of lines to skip.
#        """
#        self.cursor_up(count)
#        self.carriage_return()
#
#    def cursor_down(self, count=None):
#        """Moves cursor down the indicated # of lines in same column.
#        Cursor stops at bottom margin.
#
#        :param int count: number of lines to skip.
#        """
#        self.cursor.y += count or 1
#        self.ensure_bounds(use_margins=True)
#
#    def cursor_down1(self, count=None):
#        """Moves cursor down the indicated # of lines to column 1.
#        Cursor stops at bottom margin.
#
#        :param int count: number of lines to skip.
#        """
#        self.cursor_down(count)
#        self.carriage_return()
#
#    def cursor_back(self, count=None):
#        """Moves cursor left the indicated # of columns. Cursor stops
#        at left margin.
#
#        :param int count: number of columns to skip.
#        """
#        self.cursor.x -= count or 1
#        self.ensure_bounds()
#
#    def cursor_forward(self, count=None):
#        """Moves cursor right the indicated # of columns. Cursor stops
#        at right margin.
#
#        :param int count: number of columns to skip.
#        """
#        self.cursor.x += count or 1
#        self.ensure_bounds()
#
#    def cursor_position(self, line=None, column=None):
#        """Set the cursor to a specific `line` and `column`.
#
#        Cursor is allowed to move out of the scrolling region only when
#        :data:`~pyte.modes.DECOM` is reset, otherwise -- the position
#        doesn't change.
#
#        :param int line: line number to move the cursor to.
#        :param int column: column number to move the cursor to.
#        """
#        column = (column or 1) - 1
#        line = (line or 1) - 1
#
#        # If origin mode (DECOM) is set, line number are relative to
#        # the top scrolling margin.
#        if mo.DECOM in self.mode:
#            line += self.margins.top
#
#            # Cursor is not allowed to move out of the scrolling region.
#            if not self.margins.top <= line <= self.margins.bottom:
#                return
#
#        self.cursor.x, self.cursor.y = column, line
#        self.ensure_bounds()
#
#    def cursor_to_column(self, column=None):
#        """Moves cursor to a specific column in the current line.
#
#        :param int column: column number to move the cursor to.
#        """
#        self.cursor.x = (column or 1) - 1
#        self.ensure_bounds()
#
#    def cursor_to_line(self, line=None):
#        """Moves cursor to a specific line in the current column.
#
#        :param int line: line number to move the cursor to.
#        """
#        self.cursor.y = (line or 1) - 1
#
#        # If origin mode (DECOM) is set, line number are relative to
#        # the top scrolling margin.
#        if mo.DECOM in self.mode:
#            self.cursor.y += self.margins.top
#
#            # FIXME: should we also restrict the cursor to the scrolling
#            # region?
#
#        self.ensure_bounds()
#
#    def bell(self, *args):
#        """Bell stub -- the actual implementation should probably be
#        provided by the end-user.
#        """
#
#    def alignment_display(self):
#        """Fills screen with uppercase E's for screen focus and alignment."""
#        for line in self:
#            for column, char in enumerate(line):
#                line[column] = char._replace(data="E")
#
#    def select_graphic_rendition(self, *attrs):
#        """Set display attributes.
#
#        :param list attrs: a list of display attributes to set.
#        """
#        replace = {}
#
#        for attr in attrs or [0]:
#            if attr in g.FG:
#                replace["fg"] = g.FG[attr]
#            elif attr in g.BG:
#                replace["bg"] = g.BG[attr]
#            elif attr in g.TEXT:
#                attr = g.TEXT[attr]
#                replace[attr[1:]] = attr.startswith("+")
#            elif not attr:
#                replace = self.default_char._asdict()
#
#        self.cursor.attrs = self.cursor.attrs._replace(**replace)
#
#
