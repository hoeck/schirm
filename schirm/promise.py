# -*- coding: utf-8 -*-

# Schirm - a linux compatible terminal emulator providing html modes.
# Copyright (C) 2011  Erik Soehnel
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

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

