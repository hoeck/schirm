#!/bin/sh

NAME='demo'
WINDOWID=$(xdotool selectwindow)

# video friendly size
xdotool windowsize $WINDOWID 480 129

# record
recordmydesktop --windowid=$WINDOWID --no-sound --no-cursor --no-wm-check --fps=10 --height=128 -y 1 -o $NAME.ogv

# single images
mplayer -ao null <video file name> -vo jpeg:outdir=$NAME

# gif
convert $NAME/* $NAME.gif

# optimized gif
convert $NAME.gif -fuzz 10% -layers Optimize $NAME-optimised.gif
