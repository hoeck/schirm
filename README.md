Schirm
======

A Linux compatible terminal emulator which exposes additional HTML
rendering modes to client programs.

![Demo](https://raw.githubusercontent.com/hoeck/schirm/master/doc/demo.gif)

Installing
==========

Requires Python 2.7 and PyQT4 (and ClojureScript for development).

Get the source:

    $ git clone https://github.com/hoeck/schirm.git

Optionally install xsel (<https://github.com/kfish/xsel> or
`apt-get install xsel`) to be able to paste the current X
selection using Shift-Insert. Middle-click selection works without
additional programs.

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

In the terminal window, right click for the context menu and select
`inspect` to open the webkit devtools. Right-click on the very left of
the terminal window to open a context menu containing the `reload` item
to restart the terminal

Client API
==========

Escape-sequence based, works with every programming language which can write bytes to
stdout. See ``support/schirmclient.py``.

Missing Features/Defects
========================

- no terminal mouse click support
- only 16 colors
- only UTF-8
- slow Application mode (e.g. fullscreen ncurses apps)
- `cat <1G file>` will bring everything to a halt
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
- <https://github.com/shockone/black-screen>: built on electron, blends shell features (e.g. autocompletion) into the terminal, aims to be VT100 compatible
- <https://github.com/substack/exterminate>: nodejs, runs in chrome, VT100, web features such as image and html display
- <https://github.com/CGamesPlay/hterminal>: electron, alpha, augments commands such as ls and git status, uses fish shell, special HTerminal protocol for extensions
- <https://github.com/sedwards2009/extraterm>: electron, typescriptm codemirror for displaying, solid emulation based on term.js
- <https://github.com/PerBothner/DomTerm>: terminal emulation in JS, Server or GUI in Java, extension via escape sequences
- <https://github.com/zeit/hyperterm>: electron, focus on emulation and plugin-like extensions
- <https://github.com/vshatskyi/black-screen>: electron, integrates with the actual shell to e.g. provide an autocompletion popup

Licence
=======

Copyright (C) 2012 Erik Soehnel

Licenced under the GPLv3.

Client library is BSD licenced.
