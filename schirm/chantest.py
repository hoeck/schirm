
import sys
import time
import random

from chan import Chan, quickthread

def info(*s):
    sys.stdout.write(' '.join(map(str, s) + ['\n']))

def send(c, items, name):
    while True:
        val = random.choice(items)
        info(name, "sending", val)
        c.put(val)

def main():
    c = Chan()
    quickthread(send, c, [1,2,3], 'thread-1')
    quickthread(send, c, ['a','b','c'], 'thread-2')
    quickthread(send, c, ['X','Y','Z'], 'thread-3')

    while True:
        time.sleep(1)
        info("RECV:", c.get())
        

if __name__ == '__main__':
    main()
