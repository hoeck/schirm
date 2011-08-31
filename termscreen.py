# -*- coding: utf-8 -*-
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! HERE !!!
# works great so far except for resizing lines:

# create a screen proxy which dispatches calls to different screens
# depending on the current mode ?????
# allows better iframe mode support?

# also: change the resizte function to take into account how the
#  browser already handles the resizing!!!!


from UserList import UserList

import pyte
from pyte.screens import Char, Margins, Cursor
from pyte import modes as mo, graphics as g, charsets as cs

# When iframe mode is set, use another screen??
IFRAME_MODE = 21


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


class IframeLine(Line):
  
    def __init__(self):
        self.changed = False

    def set_size(self, size):
        pass

    def reverse(self):
        pass

    def insert_characters(self, pos, count, char):
        pass

    def replace_character(self, pos, char):
        pass

    def delete_characters(self, pos, count, char):
        pass

    def erase_characters(self, pos, count, char):
        pass

    def erase_in_line(self, type_of, pos, char):
        pass


class LineContainer():
    
    def __init__(self):
        self.height = 0
        self.lines  = []
        self.events = []

    def realLineIndex(self, i):
        return len(self.lines) - self.height + i
       
    def get_and_clear_events(self):
        ret = self.events
        self.events = []
        return ret

    def reset(self, lines):
        self.height = len(lines)
        self.lines = lines # a list of Line objects
        for l in lines:
            l.changed = False
        self.events.append(('reset', lines))

    def pop(self, index):
        ri = self.realLineIndex(index)
        line = self.lines.pop(ri)
        self.events.append(('pop', index))
        return line

    def pop_bottom(self):
        line = self.lines.pop(len(self.lines)-1)
        self.events.append(('pop_bottom',))
        return line

    def append(self, line):
        self.lines.append(line)
        line.changed = False
        self.events.append(('append', line))

    def insert(self, index, line):
        ri = self.realLineIndex(index)
        self.lines.insert(ri, line)
        line.changed = False
        self.events.append(('insert', index, line))

    def __getitem__(self, index):
        return self.lines[self.realLineIndex(index)]

    def __iter__(self):
        return self.lines[self.realLineIndex(0):].__iter__() #???
    
    def iframecharinsert(self, char):
        self.events.append(('iframe', char))


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

    _default_char = Char(data=" ", fg="default", bg="default")
    def _create_line(self):
        return Line(self.columns, self._default_char)

    def _is_empty_line(self, line):
        return all(c == self._default_char for c in line)

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

        self.iframe_mode = False
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
                  -> but we don't do this here
        :param int lines: number of lines in the new screen.
        :param int columns: number of columns in the new screen.
        """
        lines = lines or self.lines
        columns = columns or self.columns

        lc = self.linecontainer

        #print "screen.resize 0:", (self.lines, "->", lines, "lc.lines:", len(lc.lines))

        # cursor: make sure that it 'stays' on its current line

        if self.lines < lines:
            # enlarge
            if len(lc.lines) < lines:
                for _ in range(lines - len(lc.lines)):
                    lc.append(self._create_line())
                cursordelta = len(lc.lines) - lines
            else:
                cursordelta = lines - self.lines
        else:
            # try to remove blank lines from the bottom first
            lines_to_remove = self.lines - lines;
            while self._is_empty_line(lc.lines[-1]) and lines_to_remove > 0:
                lc.pop_bottom();
                lines_to_remove -= 1;

            cursordelta = lines_to_remove

        newcursory = self.cursor.y + cursordelta
        self.cursor.y = min(max(newcursory, 0), lines)
        self.cursor.x = min(max(self.cursor.x, 0), columns)

        #print "new cursor is row:{} col:{}".format(self.cursor.y, self.cursor.x)

        lc.height = lines
        #print "screen.resize 1:", (self.lines, "->", lines, "lc.lines:", len(lc.lines))

        # First resize the lines:
        #diff = self.lines - lines

        # a) if the current display size is less than the requested
        #    size, add lines to the bottom.
        ### TODO: add resize command to LineContainer
        ### on the html-render side:
        ### when the new size has more lines
        ### grab lines from the history first instead of appending
        ### blank ones at the top
        # if diff < 0: # enlarge terminal screen
        #     # self.extend(take(self.columns, self.default_line)
        #     #             for _ in range(diff, 0))
        #     #self.extend(self._create_line() for _ in range(diff, 0))
        #     for _ in range(diff, 0):
        #         self.linecontainer.append(self._create_line())

        # # b) if the current display size is greater than requested
        # #    size, take lines off the top.
        # elif diff > 0:
        #     # self[:diff] = ()
        #     #[self.pop(0) for _ in range(diff)]
        #     for _ in range(diff):
        #         self.linecontainer.pop(0)

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

        # don't reset the cursorpos
        #self.reset_mode(mo.DECOM) # resets the cursor position

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
            print "Application Mode Set"

        # Iframe mode yippee
        if IFRAME_MODE in modes:
            # move cursor to last line
            # insert an iframe line
            # all following chars are written to that frame via
            # iframe.document.write

            self.index()
            self.linecontainer.pop(self.cursor.y)
            self.linecontainer.insert(self.cursor.y, IframeLine())
            self.iframe_mode = True

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

    def _application_mode(self):
        return mo.DECAPP in self.mode

    def _iframe_mode(self):
        return IFRAME_MODE in self.mode

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
            print "Application Mode _RE_set"

        # leave Iframe mode
        if IFRAME_MODE in modes:
            self.index()
            self.iframe_mode = False

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

    def draw(self, char):
        """Display a character at the current cursor position and advance
        the cursor if :data:`~pyte.modes.DECAWM` is set.

        :param unicode char: a character to display.
        """

        #print self.iframe_mode
        if self.iframe_mode:
            self.linecontainer.iframecharinsert(char)
            return # ignore all other modes

        # Translating a given character.
        if self.charset != 0:
            # somehoe, the latin 1 encoding done here is wrong,
            # json.dumps does not correctly convert the resulting
            # string into browser-utf-8
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

    def index(self):
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        top, bottom = self.margins

        if self.cursor.y == bottom:
            #self.linecontainer.pop(top) # don't handle history manually
            #self.insert(bottom, take(self.columns, self.default_line))
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
            #self.insert(top, take(self.columns, self.default_line))
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
