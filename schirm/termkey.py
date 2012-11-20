# -*- coding: utf-8 -*-
## mapping keypresses to escape codes

# VT100 Key    Standard    Applications     IBM Keypad
# =====================================================
#
#                                           NUMLOK - On
# Keypad:
#
#    0            0           ESC O p           0
#    1            1           ESC O q           1
#    2            2           ESC O r           2
#    3            3           ESC O s           3
#    4            4           ESC O t           4
#    5            5           ESC O u           5
#    6            6           ESC O v           6
#    7            7           ESC O w           7
#    8            8           ESC O x           8
#    9            9           ESC O y           9
#    -            -           ESC O m           -
#    ,            ,           ESC O l      * (on PrtSc key)
#    .            .           ESC O n           .
# Return       Return         ESC O M           +
#
#
#                                          NUMLOK - Off
# Arrows:
#
#    Up        ESC [ A        ESC O A           Up
#   Down       ESC [ B        ESC O B          Down
#   Right      ESC [ C        ESC O C          Right
#   Left       ESC [ D        ESC O D          Left
#
#    Up        ESC [ A        ESC O A          Alt 9
#   Down       ESC [ B        ESC O B          Alt 0
#   Right      ESC [ C        ESC O C          Alt -
#   Left       ESC [ D        ESC O D          Alt =
#   Note that either set of keys may be used to send VT100 arrow keys.
#   The Alt 9,0,-, and = do not require NumLok to be off.
#
# Functions:
#
# PF1 - Gold   ESC O P        ESC O P           F1
# PF2 - Help   ESC O Q        ESC O Q           F2
# PF3 - Next   ESC O R        ESC O R           F3
# PF4 - DelBrk ESC O S        ESC O S           F4

_keycodes = {
    # gtk-keyname: (cursor-positioning-mode, applications-mode)
    # gtk-keyname: cursor-positioning-mode
    'Up'   : ("\x1b[A", "\x1bOA"),
    'Down' : ("\x1b[B", "\x1bOB"),
    'Right': ("\x1b[C", "\x1bOC"),
    'Left' : ("\x1b[D", "\x1bOD"),

    'F1'   : "\x1bOP",
    'F2'   : "\x1bOQ",
    'F3'   : "\x1bOR",
    'F4'   : "\x1bOS",
    'F5'   : "\x1b[15~",
    'F6'   : "\x1b[17~",
    'F7'   : "\x1b[18~",
    'F8'   : "\x1b[19~",
    'F9'   : "\x1b[20~",
    'F10'  : "\x1b[21~",
    'F11'  : "\x1b[23~",
    'F12'  : "\x1b[24~",

    'Insert'    : "\x1b[2~",
    'Delete'    : "\x1b[3~",
    'Home'      : "\x1bOH",
    'End'       : "\x1bOF",
    'Page_Up'   : "\x1b[5~",
    'Page_Down' : "\x1b[6~",

    # those need a mapping because gtk doesn't supply strings for
    # them:
    'BackSpace' : "\x08",
    'Tab'       : "\t",

    # keycodes generated in term.js
    'Enter'     : chr(13),
    'Esc'       : chr(27),
}

ASCII_A = 65
ASCII_Z = 90

def control_key_code(name):
    if name and ord(name) >= ASCII_A and ord(name) <= ASCII_Z:
        # 'A' -> '\x01'
        # 'B' -> '\x02'
        # 'X' -> '\x18'
        # ...
        return chr(abs(ASCII_A - ord(name.upper())) + 1)
    else:
        return None

# see: http://rtfm.etla.org/xterm/ctlseq.html, xterm behaviour
# append ';' and this id before the final character in the escseq
# from _keycodes to encode modifier keys
# 2    Shift
# 3    Alt
# 4    Shift + Alt
# 5    Control
# 6    Shift + Control
# 7    Alt + Control
# 8    Shift + Alt + Control
_mod_map = {
    # (shift, alt, control): id
    (True,  False, False): 2,
    (False, True,  False): 3,
    (True,  True,  False): 4,
    (False, False, True ): 5,
    (True,  False, True ): 6,
    (False, True,  True ): 7,
    (True,  True,  True ): 8,
}

def map_key(keyname, modifiers, screen_mode=False):
    """Map gtk keynames to vt100 keysequences.

    Return None if there is no mapping for a given key, meaning
    that the reported string value will work just fine.
    Modifiers should be a tuple of 3 booleans: (shift, alt,
    control) denoting the state of the modifier keys.

    Depending on the terminals screen_mode (pyte.mo.DECAPP in
    screen.mode), return different sequences.
    """

    def _add_modifier(esc_seq):
        if esc_seq and any(modifiers):
            return "".join((esc_seq[:-1],
                            ";", str(_mod_map.get(modifiers)),
                            esc_seq[-1]))
        else:
            return esc_seq

    keydef = _keycodes.get(keyname)
    if keydef:
        if isinstance(keydef, tuple):
            if screen_mode:
                return _add_modifier(keydef[1])
            else:
                return _add_modifier(keydef[0])
        else:
            return _add_modifier(keydef)

    else:
        shift, alt, control = modifiers
        if control and keyname:
            return control_key_code(keyname.upper())
        else:
            return keyname
