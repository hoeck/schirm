#!/usr/bin/env python

import os
import sys
import cgi
import random
import time
import base64
import termios
import fcntl
from contextlib import contextmanager

import schirmclient

css = """
html {
}

body {
  /* margin:0px; */
}

div.tablecontainer {
  float:left;
  border-radius: 1ex;
  background: none repeat scroll 0 0 #eaeaea;
  border-style: solid;
  border-width: 0.3ex;
  border-color: #ccc;
  padding: 0.0ex;
  overflow:hidden;
}

table {
    display:none;
    border-spacing: 0px;
    border-collapse: collapse;
    font-family: "Lucida Sans Unicode","Lucida Grande",Sans-Serif;
    font-size: 12px;
    text-align: left;
    margin: 0 0 0.5ex 0;
}
table th {
    border-bottom: 2px solid #6678B1;
    color: #003399;
    font-size: 14px;
    font-weight: normal;
    padding: 3px 2px;
}
table td {
    color: #558;
    padding: 0.5ex;
}

table tbody tr:hover td {
    color: #008;
    background-color: #c9c9f0;
}

table tr:nth-child(even) {
    background-color: #ffffff;
}
"""

def table(cols, header, rows):
    tmpl = """
    <html>
      <head>
        <style type="text/css">
          {css}
        </style>
      </head>
      <body>
        <div class="tablecontainer">
        <table>
          <thead>
            <tr>
              {header}
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
</div>
<script type="text/javascript" src="/schirm.js"></script>
<script type="text/javascript">

function resize() {{
  schirm.resize(document.querySelector(".tablecontainer").getBoundingClientRect().height);
}}

schirm.ready(function() {{
  document.querySelector("table").style.display = 'block';
  schirm.resize('fullscreen');
}});

</script>
</body>
</html>
    """

    res = []
    for r in rows:
        res.append('<tr>')
        res.extend('<td>{}</td>'.format(cgi.escape(str(r[c]))) for c in cols)
        res.append('</tr>')

    return tmpl.format(css=css,
                       header="".join("<th>{}</th>".format(cgi.escape(header[c]))
                                      for c
                                      in cols),
                       rows="".join(res))

def table_test():

    rows = [{'column 1': 'X'*20,
             'column 2': 'Y'*20,
             'column 3': 'Z'*20,
             'column 4': 'A'*20}] * 3
    header = {'column 1': 'C1',
              'column 2': 'C2',
              'column 3': 'C3',
              'column 4': 'C4'}
    cols = ['column 1','column 2','column 3','column 4']
    with schirmclient.frame():
        print table(cols, header, rows)

if __name__ == '__main__':
    table_test()
