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

Optionally, install xsel (<https://github.com/kfish/xsel> or `apt-get install xsel`)
to be able to paste the current X selection using Shift-Insert.

Run:

    $ cd schirm
    $ python -m schirm

or install and then run it:

    $ python setup.py install
    $ schirm

Runs all your favorite commandline applications, including:

  mc, htop, vim, grep --color ...

HTML Demos
==========

See the demos in `support/`

  - add them to your `PATH`::

      $ PATH="$PATH:<path-to-schirm>/support"

    or invoke them with `<path-to-schirm>/support/<sXXX>`

  - get and view some html:

    $ curl news.ycombinator.com | sview

  - preview a document::

    $ markdown README.md | sview

  - show a tree of a directory (uses d3.js, slow/crashing for large directories)::

    $ stree .

  - view an image::

    $ sview schirm-logo.png

    with interactive rescaling buttons:

    $ sview -i schirm-logo.png

  - edit text using codemirror:

    $ sedit README.md

Client API
==========

Escape-sequence based, works with every programming language which can write bytes to
stdout. See ``support/schirmclient.py``.

Missing Features/Defects
========================

- Application mode (fullscreen ncurses apps use this) is not implemented properly.
- Slower than any other terminal emulator, becomes slower with each
  page of terminal output due to the overhead of rendering the HTML
  document.
- UTF-8 only
- Alpha Software (expect lots of bugs)

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
