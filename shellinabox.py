


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



# shellinabox server functions
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
        ret = "".join(map(lambda a,b: chr(int(str(a) + str(b), 16)), keys[0::2], keys[1::2]))
        return ret
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

    #// Encode the buffer using JSON string escaping
    dst = ""
    # char *dst                   = result;  the pointer into the string
    #ptr                         = buf;
    def unicode_escape(c):
        return "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')

    for c in src:
        if c < ord(' '):
            dst += "\\"
            if c == "\b":
                dst += "b"
            elif c == "\f":
                dst += "f"
            elif c == "\b":
                dst += "b"
            elif c == "\r":
                dst += "r"
            elif c == "\t":
                dst += "t"
            else:
                dst += unicode_escape(c)
        elif c in ['"','\\','/']:
            dst += "\\" + c
        elif ord(c) > 0x7f:
            dst += "\\" + unicode_escape(c)
        else:
            dst += c

    return dst


def json_escape_all_u(src):
    dst = ""
    for c in src:
        dst += "\\u00%s" % ("%x" % ord(c)).rjust(2,'0')
    return dst

import simplejson
class Pty(object):
            
    def __init__(self):
        pid, master = os.forkpty()
        if pid == 0:
            # child
            os.execl("/bin/bash", "bash")
        else:
            # parent
            pass
        self._size = [0,0]
        self._pty = master

    def write_keys(self, keyparam):
        os.write(self._pty, decode_keyparam(keyparam))

    def set_size(self, w, h):
        oldw, oldh = self._size
        if oldw != w or oldh != h and w > 0 and h > 0:
            # TIOCSSIZE
            #win = struct.pack('HHHH',0,0,0,0)
            #fcntl.ioctl(pty, termios.TIOCGSIZE, win)
            #w,h,x,y = struct.unpack('HHHH', win)
            #win = struct.pack('HHHH', widht, height, x, y)
            #fcntl.ioctl(pty, termios.TIOCSSIZE, win)

            # TIOCGWINSZ
            empty_win = struct.pack('HHHH',0,0,0,0)
            win = fcntl.ioctl(self._pty, termios.TIOCGWINSZ, empty_win)
            _h,_w,x,y = struct.unpack('HHHH', win)
            #print "set size is:", [_w, _h], "my size is:", [w, h], "(",[oldw, oldh],")"
            win = struct.pack('HHHH', h, w, x, y)
            fcntl.ioctl(self._pty, termios.TIOCSWINSZ, win)

            self._size = [w, h]
    
    def read(self):
        #return json_escape(os.read(self._pty, 1024))
        return json_escape_all_u(os.read(self._pty, 2048))
        #return simplejson.dumps(os.read(self._pty, 1024))
