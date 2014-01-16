Schirm
======

A Linux compatible terminal emulator which exposes additional HTML
rendering modes to client programs.

Written in Python and JavaScript.

Installing
==========

Requires Python 2.7.


Get the source:

    $ git clone https://github.com/hoeck/schirm.git

Optionally install xsel (<https://github.com/kfish/xsel> or
`apt-get install xsel`) to be able to paste the current X
selection using Shift-Insert. Middle-click selection works without
additional programs.

Make sure that you have either chromium, chrome or firefox installed.

Run:

    $ cd schirm
    $ python -m schirm

or install and then run it:

    $ python setup.py install
    $ schirm

Runs all your favorite commandline applications, including:

    mc, htop, vim, grep --color ...

Example Programs
================

See the demos in `support/`

  - they use the schirmclient.py lib to show HTML documents in the terminal

  - add them to your `PATH`:

        $ PATH="$PATH:<path-to-schirm>/support"

    or invoke them with `<path-to-schirm>/support/<sXXX>`

  - get and view some html:

        $ curl news.ycombinator.com | sview

  - preview a Markdown document:

        $ markdown README.md | sview

  - show a tree of a directory (uses d3.js, slow/crashing for large directories):

        $ stree .

    or

        $ stree --circle

  - view an image:

        $ sview schirm-logo.png

    with interactive rescaling buttons:

        $ sview -i schirm-logo.png

  - edit text using codemirror:

        $ sedit README.md

Styling
=======

Place your own styles into `~/.schirm/user.css` and restart the terminal.
See `schirm/resources/user.css` for the default stylesheet.
In the terminal window, press F12 to open the chrome/firefox devtools
or right click to open the browsers contextmenu.
Right-clicking on the very left of the terminal window (first 25
pixels) opens a contextmenu containing the `reload` item - use this to
quickly restart the terminal without closing the window.

Client API
==========

Escape-sequence based, works with every programming language which can write bytes to
stdout. See ``support/schirmclient.py``.

Missing Features/Defects
========================

- no terminal mouse click support
- only 16 colors
- UTF-8 only
- slow Application mode
- emulation glitches (e.g. when resizing htop)

Similar Programs
================

- <https://github.com/mitotic/graphterm>: terminal emulator supporting HTML iframes and serving files, server written in Python
- <https://github.com/breuleux/terminus>: terminal emulator allowing inline HTML and javascript
- <https://github.com/unconed/TermKit>: not an emulator but a completely new terminal, built on WebKit and Node.js
- <https://github.com/liftoff/GateOne>: HTML5 Terminal emulator
- <http://code.google.com/p/shellinabox/>: a complete browser terminal emulator with server
- <http://www.enlightenment.org/p.php?p=about/terminology>: nextgen Terminal Emulator of the Enlightment Project
- <http://www.logilab.org/project/pyqonsole>: QT python terminal emulator
- <https://github.com/selectel/pyte>: beautiful VTXXX compatible terminal emulator library
- <http://www.masswerk.at/termlib/> (referenced by Fabrice Bellard on his tech details page. Bellard uses his own proprietary terminal emulator though)
- <https://github.com/chjj/tty.js> ([actual terminal emulator here](https://raw.github.com/chjj/tty.js/master/static/term.js))
- <http://mister-muffin.de/scriptreplay/VT100.js> (Frank Bi's unmaintained terminal emulator, outdated by now)
- <https://github.com/s-macke/jor1k/blob/master/js/terminal.js> (from jor1k, the JavaScript OpenRISC emulator)

Licence
=======

Copyright (C) 2012 Erik Soehnel

Licenced under the GPLv3.

Client library is BSD licenced.
