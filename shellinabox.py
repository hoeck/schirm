


# shellinabox http API

# === keypresses ===
#BOOKMARK: keypress handler
# client:
# query:
#   width
#   height
#   keys
#   rooturl

# server-reply:
#   typical session stuff?
#   body: "\007"

def decode_keyparam(keys): # 'keys' from the ajax GET
    # def no_hex_digit(c):
    #     return \
    #         (c < ord('0')) or \
    #         (c > ord('9') and c < ord('A')) or \
    #         (c > ord('F') and c < ord('a')) or \
    #         (c > ord(f))

    # if any(map(no_hex_digit, keys)):
    #     return None

    try:
        return map(int(map(str, keys[0::2], keys[1::2])))
    except ValueError:
        return None
    
# code to handle keypresses
# keys is the query param 'keys'
  # if (keys) {
  #   char *keyCodes;
  #   check(keyCodes        = malloc(strlen(keys)/2));
  #   int len               = 0;
  #   for (const unsigned char *ptr = (const unsigned char *)keys; ;) {
  #     unsigned c0         = *ptr++;
  #     if (c0 < '0' || (c0 > '9' && c0 < 'A') ||
  #         (c0 > 'F' && c0 < 'a') || c0 > 'f') {
  #       break;
  #     }
  #     unsigned c1         = *ptr++;
  #     if (c1 < '0' || (c1 > '9' && c1 < 'A') ||
  #         (c1 > 'F' && c1 < 'a') || c1 > 'f') {
  #       break;
  #     }
  #     keyCodes[len++]     = 16*((c0 & 0xF) + 9*(c0 > '9')) +
  #                               (c1 & 0xF) + 9*(c1 > '9');
  #   }

import os
def write_keys(pty, keyparam):
    os.write(pty, decode_keyparam(keys))

# keycodes are written directly to the pty
# if (write(session->pty, keyCodes, len) < 0 && errno == EAGAIN) {
#       completePendingRequest(session, "\007", 1, MAX_RESPONSE);
# }

# === tracking term size ===
# call this when width/height has changed
# pty is session->pty
# void setWindowSize(int pty, int width, int height) {
#   if (width > 0 && height > 0) {
#     #ifdef TIOCSSIZE
#     {
#       struct ttysize win;
#       ioctl(pty, TIOCGSIZE, &win);
#       win.ts_lines = height;
#       win.ts_cols  = width;
#       ioctl(pty, TIOCSSIZE, &win);
#     }
#     #endif
#     #ifdef TIOCGWINSZ
#     {
#       struct winsize win;
#       ioctl(pty, TIOCGWINSZ, &win);
#       win.ws_row   = height;
#       win.ws_col   = width;
#       ioctl(pty, TIOCSWINSZ, &win);
#     }
#     #endif
#   }
# }

import fcntl
import termios
import struct
def set_window_size(pty, width, height):
    if width > 0 and height > 0:
        # TIOCSSIZE
        #win = struct.pack('HHHH',0,0,0,0)
        #fcntl.ioctl(pty, termios.TIOCGSIZE, win)
        #w,h,x,y = struct.unpack('HHHH', win)
        #win = struct.pack('HHHH', widht, height, x, y)
        #fcntl.ioctl(pty, termios.TIOCSSIZE, win)

        # TIOCGWINSZ
        win = struct.pack('HHHH',0,0,0,0)
        fcntl.ioctl(pty, termios.TIOCGWINSZ, win)
        _,_,x,y = struct.unpack('HHHH', win)
        win = struct.pack('HHHH', widht, height, x, y)
        fcntl.ioctl(pty, termios.TIOCSWINSZ, win)

# === sending screen updates ===
# normal terminal updates
# reading directly from the pty and send that to the client:
# len = MAX_RESPONSE - session->len
# bytes                       = NOINTR(read(session->pty, buf, len));
# if (bytes <= 0) {
#   return 0;
# }
      
import os  
def read_pty(pty):
    return os.read(pty, 2048)

# then that data is run through jsonEscape
# session->buffered = bytes
#jsonEscape(session->buffered, session->len);

def json_escape(src):
    hexDigit = "0123456789ABCDEF"

    if isinstance(src, str):
        src = src.decode('utf-8') # to make ord working with unicode chars

    #// Encode the buffer using JSON string escaping
    dst = ""
    # char *dst                   = result;  the pointer into the string
    #ptr                         = buf;
    def unicode_escape(c):
        return "u00" + ord(c)

    for c in src:
        if x < ord(c):
            dst += "\\"
            if x == "\b":
                dst += "b"
            elif x == "\f":
                dst += "f"
            elif x == "\b":
                dst += "b"
            elif x == "\r":
                dst += "r"
            elif x == "\t":
                dst += "t"
            else:
                dst = unicode_escape(c)
        elif c == '"' or c == '\\' or c == '/':
            dst += "\\" + c
        elif ord(c) > 0x7f:
            dst += \\ + unicode_escape(c)
        else:
            dst += c
    return dst


# === getting a pty ===
import os
# man openpty


master, pty = os.openpty(...)

