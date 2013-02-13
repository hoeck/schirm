# -*- coding: utf-8 -*-
"""
    pyte.modes
    ~~~~~~~~~~

    This module defines terminal mode switches, used by
    :class:`~pyte.screens.Screen`. There're two types of terminal modes:

    * `non-private` which should be set with ``ESC [ N h``, where ``N``
      is an integer, representing mode being set; and
    * `private` which should be set with ``ESC [ ? N h``.

    The latter are shifted 5 times to the right, to be easily
    distinguishable from the former ones; for example `Origin Mode`
    -- :data:`DECOM` is ``192`` not ``6``.

    >>> DECOM
    192

    :copyright: (c) 2011 by Selectel, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""

#: *Line Feed/New Line Mode*: When enabled, causes a received
#: :data:`~pyte.control.LF`, :data:`pyte.control.FF`, or
#: :data:`~pyte.control.VT` to move the cursor to the first column of
#: the next line.
LNM = 20

#: *Insert/Replace Mode*: When enabled, new display characters move
#: old display characters to the right. Characters moved past the
#: right margin are lost. Otherwise, new display characters replace
#: old display characters at the cursor position.
IRM = 4


# Private modes.
# ..............

# Private mode codes are shifted, to be distingiushed from non
# private ones.
PRIVATE_MODE_SHIFT = 5

#: *Text Cursor Enable Mode*: determines if the text cursor is
#: visible.
DECTCEM = 25 << PRIVATE_MODE_SHIFT

#: *Screen Mode*: toggles screen-wide reverse-video mode.
DECSCNM = 5 << PRIVATE_MODE_SHIFT

#: *Origin Mode*: allows cursor addressing relative to a user-defined
#: origin. This mode resets when the terminal is powered up or reset.
#: It does not affect the erase in display (ED) function.
DECOM = 6 << PRIVATE_MODE_SHIFT

#: *Auto Wrap Mode*: selects where received graphic characters appear
#: when the cursor is at the right margin.
DECAWM = 7 << PRIVATE_MODE_SHIFT

#: *Column Mode*: selects the number of columns per line (80 or 132)
#: on the screen.
DECCOLM = 3 << PRIVATE_MODE_SHIFT

#: *Application Cursor Keys Mode*: Use slightly different keysequences for
#: function, numpad and arrow keys
#: (see also ESC + ``=`` and ESC + ``>`` sequences, which seem to do
#   the same as setting and resetting this mode)
DECAPPKEYS = 1 << PRIVATE_MODE_SHIFT

#: *Alternate Buffer Mode*: Use a different draw buffer when this mode
#: is activated. Fullscreen terminal applications such as less, htop
#: and the Midnight Commander use this mode.
#: see also: http://www.xfree86.org/4.8.0/ctlseqs.html
DECALTBUF = 47 << PRIVATE_MODE_SHIFT
DECALTBUF_ALT = 1047 << PRIVATE_MODE_SHIFT

#: *Save Cursor Mode*: Save cursor as in DECSC.
DECSAVECUR = 1048 << PRIVATE_MODE_SHIFT

#: *Save Cursor, Clear And Use Alternate Buffer Mode*:
#: Combination of two DECALTBUF and DECSAVECUR modes.
DECAPPMODE = 1049 << PRIVATE_MODE_SHIFT
