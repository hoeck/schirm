import cgi
import json

def json_escape_all_u(src):
    dst = ""
    for c in src:
        dst += "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')
    return dst

### creating html to render the terminal contents

def create_class_string(chartuple, additional_classes=[]):
    data, fg, bg, bold, italics, underscore, strikethrough, reverse = chartuple
    c = []
    if reverse:
        if bg == 'default':
            c.append("f-default-reversed")
        else:
            c.append("f-{0}".format(bg))
        if fg == 'default':
            c.append("b-default-reversed")
        else:
            c.append("b-{0}".format(fg))
    else:
        if fg != 'default':
            c.append("f-{0}{1}".format('bold-' if bold else '',fg))
        if bg != 'default':
            c.append("b-{0}".format(bg))

    if bold: c.append("bold")
    if italics: c.append("italics")
    if underscore: c.append("underscore")
    if strikethrough: c.append("strikethrough")
    if reverse:
        c.append("reverse")
    c.extend(additional_classes)
    return " ".join(c)

def equal_attrs(chartuple0, chartuple1):
    """
    Return True if both _Char tuples have the same attributes set.
    """
    return \
        chartuple0 \
        and chartuple1 \
        and (chartuple0[1:] == chartuple1[1:])

class CursorMarker():
    def __init__(self, ch, cursorclass):
        self.char = ch
        self.cursorclass = cursorclass

def group_by_attrs(line):
    """
    Return a list of groups of _Char tuples having the same attributes.
    """
    prev_tuple = None
    groups = []
    cursorpos = line.cursorpos
    cursorclass = line.cursorclass

    for i, chartuple in enumerate(line):
        if cursorpos==i:
            groups.append(CursorMarker(chartuple, cursorclass))
            prev_tuple = None
        elif equal_attrs(prev_tuple, chartuple):
            groups[-1].append(chartuple)
            prev_tuple = chartuple
        else:
            groups.append([chartuple])
            prev_tuple = chartuple

    return groups

def unicode_escape_char(c):
    return "\\u%s" % ("%x" % ord(c)).rjust(4,'0')

def create_span(group):
    def _span(cl, contents):
        if cl:
            return '<span class="{0}">{1}</span>'.format(cl, contents)
        else:
            return '<span>{0}</span>'.format(contents)
    if isinstance(group, list):
        cl = create_class_string(group[0])
        return _span(cl, cgi.escape("".join(map(lambda ch: ch.data, group))))
    elif isinstance(group, CursorMarker):
        cl = create_class_string(group.char, [group.cursorclass])
        return _span(cl, cgi.escape(group.char.data))
    else:
        return _span("", "")

def renderline(line):
    """
    Given a line of pyte.Chars, create a string of spans with appropriate style.
    """
    return "".join(map(lambda x:  create_span(x), group_by_attrs(line)))

def wrap_in_span(s):
    return '<span>{0}</span>'.format(s)

def set_line_to(i, content):
    return """term.setLine({0}, {1});""".format(i, json.dumps(content))

# screen events, return a js string
class Events():

    @staticmethod
    def reset():
        return "term.reset();"

    @staticmethod
    def set_screen0(screen0):
        return "term.setScreen0({})".format(screen0)

    @staticmethod
    def pop(index, line):
        return "term.removeLine({});".format(index)

    @staticmethod
    def pop_bottom():
        return "term.removeLastLine();"

    @staticmethod
    def append(line):
        content = renderline(line)
        return "term.appendLine({});".format(json.dumps(content))

    @staticmethod
    def insert(index, line):
        # if False and isinstance(line, termscreen.IframeLine):
        #     assert False, "Insert line semantics are only defined for plain lines!"
        # else:
        content = renderline(line)
        return "term.insertLine({}, {});".format(index, json.dumps(content))

    @staticmethod
    def set(index, line):
        #if isinstance(line, termscreen.IframeLine):
        #    # TODO: close leave the current iframe (if any)
        #    #return 'term.insertIframe({}, {});'.format(index, json.dumps(line.id))
        #    def _iframe_insert(schirm):
        #        schirm.iframe_insert(index, line.id)
        #    return _iframe_insert
        #else:
        content = renderline(line)
        return set_line_to(index, content)

    @staticmethod
    def modify(index, line):
        content = renderline(line)
        return set_line_to(index, content)

    @staticmethod
    def remove_history_lines(n):
        return "term.removeHistoryLines(%s);" % n

    @staticmethod
    def check_history_size():
        return "term.checkHistorySize();"

    @staticmethod
    def iframe_resize(iframe_id, height):
        return "term.iframeResize(\"%s\", %s);" % (iframe_id, int(height))
