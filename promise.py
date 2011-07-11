
import threading

class Promise(object):
    
    def __init__(self, deliver=None):
        """
        Optionally specify a function called when the promise instance
        is called. This functions return value is used to delivers
        this promise value.
        """
        self._condition = threading.Condition()
        if deliver:
            self._f = deliver

    def __call__(self, *args, **kwargs):
        if hasattr(self, '_f'):
            r = self._f(*args, **kwargs)
            self.deliver(r)
            return r
        else:
            raise Exception("Promise contains no function")

    def deliver(self, value):
        """
        Set the value (once) of this promise.
        """
        # race condition here (multiple threads shouldn't try to
        # deliver a promise anyway)
        self._condition.acquire()
        if not hasattr(self, '_value'):
            self._value = value
            self._condition.notify()
            self._condition.release()
        else:
            self._condition.release()
            raise Exception("Promise has already been delivered!")

    def get(self):
        """
        Return the value of a promise or block until someone delivers
        it first.
        """
        self._condition.acquire()

        if not hasattr(self, '_value'):
            self._condition.acquire()
            self._condition.wait()

        v = self._value
        self._condition.release()

        return v


