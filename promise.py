
import threading

class Promise(object):
    
    def __init__(self, deliver=None):
        """
        Optionally specify a function called when the promise instance
        is called. This functions return value is used to deliver
        this promise value.

        If deliver is None and the promise is called, ignore all
        arguments, deliver 'True' and return None.
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
            self.deliver(True)

    def deliver(self, value=True):
        """
        Set the value (once) of this promise. Defaults to True.
        """
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
            self._condition.wait()

        v = self._value
        self._condition.release()

        return v

