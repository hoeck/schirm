
import array

from pyte.screens import Char

DEFAULT_ATTRS = ('default', 'default', False, False, False, False, False)

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

_char_attr_class_cache = {}
def char_attr_to_class(char):
    """Convert cursor attributes into a class attribute string."""
    cached = _char_attr_class_cache.get(char)
    if cached:
        return cached
    else:
        fg, bg, bold, italics, underscore, strikethrough, _ = char
        class_string = ' '.join(('f-%s' % fg,
                                 'b-%s' % bg,
                                 'bold' if bold else '',
                                 'italics' if italics else '',
                                 'underscore' if underscore else '',
                                 'strikethrough' if strikethrough else ''))
        _char_attr_class_cache[char] = class_string
        return class_string

def compact_insert_overwrites(insert_events, cols):
    """Reduce the number of insert-overwrite operations for a single line.

    Take a group of (possibly overlapping) insert-overwrites (on the
    same line) and return a list of (string, class-string) tuples.
    """
    assert insert_events

    line_chars = [' '] * cols
    line_attrs = [DEFAULT_ATTRS] * cols

    # build
    for name, line, col, string, attr in insert_events:
        assert name == 'insert-overwrite'
        end = col+len(string)
        line_chars[col:end] = string
        line_attrs[col:end] = [attr]*len(string)

    # partition
    res = []
    prev_i = None
    prev_a = None
    for i,a in enumerate(line_attrs):
        if a != prev_a:
            if prev_a is not None:
                res.append((''.join(line_chars[prev_i:i]), char_attr_to_class(prev_a)))
            prev_i = i
            prev_a = a
    res.append((''.join(line_chars[prev_i:i]), a))

    return res

def compile_appends(events, max_lines=256):
    """Merge append-lines and insert-overwrites into a single operation.

    This reduces the client overhead in case a process is appending
    *lots* of lines to the terminal.

    Merge at most max_lines into a single append operation.
    """

    # a state machine to look for [append-line set-line-origin insert-overwrite*] event patterns
    res = []
    state = None
    group = []
    lines = []
    line_origin = None
    cols = None
    for e in events:
        cmd = e[0]
        if state is None:
            if cmd == 'append-line':
                state = 'append'
                cols = e[1]
            else:
                res.append(e)
        elif state == 'append':
            if cmd == 'set-line-origin':
                # A single set-line-origin must come after the append-line.
                # In case of many appended lines, use the last
                # set-line-origin as it increases anyway.
                line_origin = e
            elif cmd == 'insert-overwrite':
                group.append(e)
            else:
                # end of the appended line
                if group:
                    lines.append(compact_insert_overwrites(group, cols))
                else:
                    lines.append([])

                group = []

                if cmd == 'append-line' and len(lines) < max_lines:
                    # directly append another line
                    pass
                else:
                    res.append(('append-many-lines', lines))
                    res.append(line_origin)
                    lines = []
                    line_origin = None

                    if cmd == 'append-line':
                        cols = e[1]
                    else:
                        state = None
                        res.append(e)

    return res

class BrowserScreen(object):

    # The number of lines which are kept in the scrollback buffer
    # should be larger than the biggest imaginable terminal height.
    # The larger the scrollback, the more lines and thus DOM elements
    # have to be kept in the browser, making layout ops more
    # expensive and eating more memory.
    SCROLLBACK_SIZE = 4000 # conservative setting

    def __init__(self):
        self._events = []
        # the number of rendered lines on the screen and in the scrollback
        # we need to keep track of this on the server to be able to
        # compute the cursor offset when resizing the terminal scren
        self.total_lines = 0
        # offset splitting the line buffer in a scrollback and screen part
        self.line_origin = 0
        # current width, required for the compile step to determine
        # text inserts into appended lines
        self.cols = 0

        # Save total lines and origin when switching to alt-mode.
        # In alt-mode, the screen has no scrollback and uses a
        # different element to draw lines on (screen/AltScreen).
        self._saved_line_origin = 0
        self._saved_total_lines = 0
        self._alt_mode = False

    def _compile(self, events):
        events.append(('adjust',))
        return compile_appends(events)

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

    def append_line(self, columns):
        """Append a new line (increments the origin)."""
        self.total_lines += 1
        self._append(('append-line', columns))
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
        remaining_empty_lines = old_lines - (self.total_lines - self.line_origin) - 1

        if self._alt_mode:
            # no scrollback
            delta = 0

        elif line_delta > 0:
            # enlarge, try pulling additional lines from the scrollback first
            if self.line_origin > line_delta:
                delta = line_delta
            else:
                delta = self.line_origin

        elif line_delta < 0:
            # shrink, remove remaining_empty_lines first (a no-op),
            # then push lines to the history
            if remaining_empty_lines < abs(line_delta):
                delta = line_delta + remaining_empty_lines
            else:
                delta = 0

        else:
            # no resize necessary
            return 0

        if delta != 0:
            self.add_line_origin(-delta)

        self._append(('resize', new_lines))

        return delta # used to compute the new cursor pos

    def reverse_all_lines(self):
        TODO

    def enter_altbuf_mode(self):
        assert not self._events # events must have been flushed before

        if not self._alt_mode:
            self._alt_mode = True
            self._saved_total_lines = self.total_lines
            self._saved_line_origin = self.line_origin
            self.total_lines = 0
            self.line_origin = 0

        self._append(('enter-alt-mode',))

    def leave_altbuf_mode(self):
        assert not self._events # events must have been flushed before

        if self._alt_mode:
            self._alt_mode = False
            self.total_lines = self._saved_total_lines
            self.line_origin = self._saved_line_origin

        self._append(('leave-alt-mode',))

    # screen managing methods

    def check_scrollback(self):
        surplus_lines = self.total_lines - self.SCROLLBACK_SIZE
        if surplus_lines > 0:
            # remove them
            self._append(('scrollback-cleanup', surplus_lines))
            self.total_lines -= surplus_lines
            self.add_line_origin(-surplus_lines)

    def set_title(self, string):
        self._append(('set-title', string))

    # iframe_* methods

    def iframe_enter(self, iframe_id, line):
        self._update_total_lines(line)
        self._append(('iframe-enter', iframe_id, line))

    def iframe_close(self, iframe_id):
        self._append(('iframe-close', iframe_id))

    def iframe_leave(self, iframe_id):
        self._append(('iframe-leave', iframe_id))

    # sending data

    def iframe_write(self, iframe_id, data):
        self._append(('iframe-write', iframe_id, data))

    def iframe_string(self, iframe_id, data):
        self._append(('iframe-string', iframe_id, data))

    def iframe_resize(self, iframe_id, height):
        self._append(('iframe-resize', iframe_id, height))
