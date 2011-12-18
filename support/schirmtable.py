import cgi

import schirmclient as schirm

css = """
body {
  margin:0px;
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
      </body>
    </html>
    """

    res = []
    for r in rows:
        #res.append('<tr{}>'.format(' class="{}"'.format(" ".join(classes)) if classes else ''))
        res.append('<tr>')
        res.extend('<td>{}</td>'.format(cgi.escape(str(r[c]))) for c in cols)
        res.append('</tr>')

    return tmpl.format(css=css,
                       header="".join("<th>{}</th>".format(cgi.escape(header[c]))
                                      for c
                                      in cols),
                       rows="".join(res))

def main():

    rows = [{'column 1': 'X'*20,
             'column 2': 'Y'*20,
             'column 3': 'Z'*20,
             'column 4': 'A'*20}] * 100
    header = {'column 1': 'C1',
              'column 2': 'C2',
              'column 3': 'C3',
              'column 4': 'C4'}
    cols = ['column 1','column 2','column 3','column 4']
    with schirm.frame(height='auto', width='100%'):
        print table(cols, header, rows)

if __name__ == '__main__':
    main()
