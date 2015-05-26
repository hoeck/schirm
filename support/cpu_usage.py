#!/usr/bin/env python

# plot cpu usage using cubism.js

import os
import json
import threading
import time
import argparse

import bottle
import schirmclient
import psutil # pip install psutil


def cpu_percent_thread(step=1000, backlog=1000*60*60):

    starttime = int(time.time()*1000)
    values = [(t, 0) for t in range(starttime-backlog,starttime,step)]

    def log_cpu():
        while True:
            now = int(time.time() * 1000)
            x = psutil.cpu_percent(interval=(step/1000.0))
            values.append((now, x))

            # remove old data
            if values[0][0] < (now - (2*backlog)):
                values[:] = [(t,v) for t,v in values if t > (now - (2*backlog))]

    t = threading.Thread(target=log_cpu)
    t.setDaemon(True)
    t.start()

    return values


main_html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>

body {
  font-family: "Helvetica Neue", Helvetica, sans-serif;
  position: relative;
  height:30px;
  margin:3px;
}

header {
  padding: 6px 0;
}

.group {
  margin-bottom: 1em;
}

.axis {
  font: 10px sans-serif;
  position: fixed;
  pointer-events: none;
  z-index: 2;
}

.axis text {
  -webkit-transition: fill-opacity 250ms linear;
}

.axis path {
  display: none;
}

.axis line {
  stroke: #000;
  shape-rendering: crispEdges;
}

.axis.top {
  background-image: linear-gradient(top, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -o-linear-gradient(top, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -moz-linear-gradient(top, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -webkit-linear-gradient(top, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -ms-linear-gradient(top, #fff 0%, rgba(255,255,255,0) 100%);
  top: 0px;
  padding: 0 0 24px 0;
}

.axis.bottom {
  background-image: linear-gradient(bottom, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -o-linear-gradient(bottom, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -moz-linear-gradient(bottom, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -webkit-linear-gradient(bottom, #fff 0%, rgba(255,255,255,0) 100%);
  background-image: -ms-linear-gradient(bottom, #fff 0%, rgba(255,255,255,0) 100%);
  bottom: 0px;
  padding: 24px 0 0 0;
}

.horizon {
  border-bottom: solid 1px #000;
  overflow: hidden;
  position: relative;
}

.horizon {
  border-top: solid 1px #000;
  border-bottom: solid 1px #000;
}

.horizon + .horizon {
  border-top: none;
}

.horizon canvas {
  display: block;
}

.horizon .title,
.horizon .value {
  bottom: 0;
  line-height: 30px;
  margin: 0 6px;
  position: absolute;
  text-shadow: 0 1px 0 rgba(255,255,255,.5);
  white-space: nowrap;
}

.horizon .title {
  left: 0;
}

.horizon .value {
  right: 0;
}

.line {
  background: #000;
  z-index: 2;
}

</style>
<script src="/static/d3.js"></script>
<script src="/static/cubism.v1.js"></script>
</head>
<body id="demo">

<script>

makeGraph = function(step) {
  var context = cubism.context()
      .serverDelay(10) // minimal collection lag
      .clientDelay(10)
      .step(step) // in milliseconds
      .size(document.body.clientWidth);

  d3.select("body").selectAll(".horizon")
      .data(["CPU"].map(createMetric))
    .enter().insert("div", ".bottom")
      .attr("class", "horizon")
    .call(context.horizon().extent([0, 100]));

  context.on("focus", function(i) {
    d3.selectAll(".value").style("right", i == null ? null : context.size() - i + "px");
  });

  function createMetric(name) {
    return context.metric(function(start, stop, step, callback) {
        d3.json('metric/'+name+'?start='+(+start)+'&stop='+(+stop)+'&step='+step, function(err, val) {
          if (err) {
            context.stop();
          } else {
            callback(null, val);
          }
      });
    }, name);
  };
};

schirm.ready(function() {
  var width = window.innerWidth,
      alive = true;

  d3.json('step', function(err, val) {
    makeGraph(val);
  });

  window.onresize = function() {
    if (width !== window.innerWidth && alive) {
      d3.text('ping', function(err, val) {
        // only reload if the iframe is still active
        if (err) {
          alive = false;
        } else {
          // todo: instead of reloading - dump and recreate cubism graph
          window.location.reload();
        }
      });
    }
  }
});

</script>
</body>
</html>
"""


@bottle.route('/static/<path:path>')
def static(path):
    return bottle.static_file(path, root=os.path.normpath(os.path.join(os.path.dirname(__file__), '../misc')))


@bottle.route('/metric/CPU')
def get_cpu_percent():
    start = int(bottle.request.query.start)
    stop  = int(bottle.request.query.stop)
    step  = int(bottle.request.query.step)

    return json.dumps([v
                       for t,v
                       in values
                       if t <= stop+(step/2) and t >= start-(step/2)])


@bottle.route('/ping')
def ping():
    return 'pong'


@bottle.route('/step')
def get_step():
    return json.dumps(interval)


@bottle.route('/main')
def main():
    return main_html


def parse_args():
    parser = argparse.ArgumentParser(description="Plot CPU usage using cubism.js")
    parser.add_argument('-i', '--interval', help="interval between measurements in milliseconds (default: 500)", type=int, default='500')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    interval = args.interval
    values = cpu_percent_thread(step=interval)
    schirmclient.wsgi_run(bottle.app(), url='/main')
