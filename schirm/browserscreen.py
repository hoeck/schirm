
def char_to_attr(char):
    """Convert cursor attributes to the format used in schirm-cljs."""
    # TODO: reduce the number of attributes in pyte.Char!!! so we do not need this function any more
    data, fg, bg, bold, italics, underscore, strikethrough, reverse = char
    # TODO: consider moving the details of the reverse
    #       implementation to the clojurescript client
    if reverse:
        _fg = bg
        _bg = fg
        if _fg == "default":
            _fg = "default-reversed"
        if _bg == "default":
            _bg = "default-reversed"
        return (_fg, _bg, bold, italics, underscore, strikethrough, False)
    else:
        return (fg, bg, bold, italics, underscore, strikethrough, False)

class BrowserScreen(object):

    def __init__(self):
        self._events = []
        # the number of rendered lines on the screen and in the scrollback
        # we need to keep track of this on the server to be able to
        # compute the cursor offset when resizing the terminal scren
        self.total_lines = 0
        # offset splitting the line buffer in a scrollback and screen part
        self.line_origin = 0

        # Save total lines and origin when switching to alt-mode.
        # In alt-mode, the screen has no scrollback and uses a
        # different element to draw lines on (screen/AltScreen).
        self._saved_line_origin = 0
        self._saved_total_lines = 0

    def _compile(self, events):
        events.append(('adjust',))
        return events

    ### consuming events

    def pop_events(self):
        e = self._events
        self._events = []
        return self._compile(e)

    ### tools

    def _append(self, ev):
        self._events.append(ev)

    def _update_total_lines(self, current_line):
        """Track how many real lines are on the display.

        Lines on the client are rendered lazily but we need to know
        how many lines have been rendered to be able to compute the
        new line origin when a resize happens.
        """
        visible_lines = self.total_lines - self.line_origin
        self.total_lines += max(0, current_line - visible_lines)

    ### events

    # common args:
    #   cursor position:
    #     x (col, pos)
    #     y (line)
    #   string - a string to insert/replace
    #   attr - tuple of the attributes defined in schirm-cljs.screen.CharacterStyle

    def insert(self, line, col, string, attr):
        """Insert string in line at col using the given attributes."""
        self._update_total_lines(line)
        self._append(('insert', line, col, string, char_to_attr(attr)))

    def insert_overwrite(self, line, col, string, attr):
        """Insert string in line starting at col overwriting existing chars."""
        self._update_total_lines(line)
        self._append(('insert-overwrite', line, col, string, char_to_attr(attr)))

    def remove(self, line, col, n):
        """Delete n characters from line starting at col."""
        self._update_total_lines(line)
        self._append(('remove', line, col, n))

    def insert_line(self, y, attrs=None):
        """Insert a new line at y."""
        # TODO: attrs ????
        #       and why do only some line inserts use 'attrs'?
        self._update_total_lines(y)
        self._append(('insert-line', y))

    def append_line(self, attrs):
        """Append a new line (increments the origin)."""
        # TODO: attrs ????
        #       and why do only some line inserts use 'attrs'?
        self._append(('append-line', ))
        self.add_line_origin(1) # total lines do not change as we increase the origin

    def remove_line(self, y):
        """remove the line at index y."""
        self._update_total_lines(y)
        self._append(('remove-line', y))

    def cursor(self, line, col):
        self._append(('cursor', line, col))

    # modify the line origin
    # TODO: move the resize code into the screen-compiler, so that the
    #       BrowserScreen does not have any state except the list of
    #       events
    #       when a resize happens, compile a previous events to
    #       determine the current state of the screen
    def set_line_origin(self, line_origin):
        self.line_origin = max(0, min(self.total_lines, line_origin))
        self._append(('set-line-origin', self.line_origin))

    def add_line_origin(self, delta):
        self.set_line_origin(self.line_origin + delta)

    def reset(self, lines):
        """Reset the browser screen."""
        assert not self._events
        self.total_lines = 0
        self._append(('reset', lines))

    def resize(self, old_lines, new_lines):
        """Resize the browserscreen from old_lines to new_lines height."""
        assert not self._events # events must have been flushed before

        line_delta = new_lines - old_lines
        remaining_empty_lines = old_lines - (self.total_lines - self.line_origin)

        if line_delta < remaining_empty_lines:
            # when resizing and there are empty lines below the last visible line,
            # keep this line in same place (measured from the top of the terminal window)
            cursor_delta = 0
        else:
            line_origin = self.line_origin
            self.set_line_origin(self.total_lines - new_lines)
            cursor_delta = line_origin - self.line_origin

        self._append(('resize', new_lines))
        return cursor_delta # to be able to compute the new cursorpos

    def reverse_all_lines(self):
        TODO

    def enter_altbuf_mode(self):
        assert not self._events # events must have been flushed before
        self._saved_total_lines = self.total_lines
        self._saved_line_origin = self.line_origin
        self.total_lines = 0
        self.line_origin = 0
        self._append(('enter-alt-mode',))

    def leave_altbuf_mode(self):
        assert not self._events # events must have been flushed before
        self.total_lines = self._saved_total_lines
        self.line_origin = self._saved_line_origin
        self._append(('leave-alt-mode',))

    # TODO: iframe_* methods

    # def iframe_*(self):
    #     pass

    def remove_history(self, lines):
        TODO

    def set_title(self, string):
        # TODO
        pass
