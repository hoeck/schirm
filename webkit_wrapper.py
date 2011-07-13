import time
import Queue
import thread
import threading
import urllib
import traceback
import logging

import gtk
import gobject

import webkit
#import jswebkit

from promise import Promise

class Webkit(object):

    @classmethod
    def create(self):
        return self(webkit.WebView())

    def __init__(self, browser):
        self.browser = browser
        self.my_settings()

    def exec_js(self, script):
        self.browser.execute_script(script)

    def connect_title_changed(self, f):
        # connect title changed events
        # javascript code should use document.title to return values
        # to python
        def f_wrapper(widget, frame, title):
            f(title)
        self.browser.connect('title-changed', f_wrapper)

    def connect_navigation_requested(self, f):
        """
        f is called with (view, frame, networkRequest) whenever the
        webview requests something from the network (clicking on
        links, ajax requests ...).
        """
        self.browser.connect('navigation-requested', f)

    def connect(self, *args, **kwargs):
        return self.browser.connect(*args, **kwargs)
        
    def open_uri(self, uri):
        self.browser.open(uri)

    def my_settings(self):
        # from https://github.com/mackstann/htpicker/blob/dabf5cb377dce9e4b05b39d2b2afa7bb1f11baa7/htpicker/browser.py (public domain)
        settings_values = (
            ("enable-default-context-menu",           False, '1.1.18'),
            ("enable-java-applet",                    False, '1.1.22'),
            ("enable-plugins",                        False, '???'   ),
            ("enable-universal-access-from-file-uris", True, '1.1.13'),
            ("enable-xss-auditor",                    False, '1.1.11'),
            ("tab-key-cycles-through-elements",       False, '1.1.17'),
        )

        settings = self.browser.get_settings()
        for key, val, version in settings_values:
            try:
                settings.set_property(key, val)
            except TypeError:
                logging.warn(("Your version of WebKit does not support "
                    "the setting '{0}'.  This setting requires version "
                    "{1}.  For best compatibility, use at least version "
                    "1.1.22.").format(key, version))



class GtkThread(object):
    
    def __init__(self):
        self._start()

    def _start(self):
        try:
            if __IPYTHON__:
                print "IPython detected -> gtk.set_interactive(False)"
                gtk.set_interactive(False)
        except NameError:
            pass
        # Start GTK in its own thread:
        gtk.gdk.threads_init()
        thread.start_new_thread(gtk.main, ())

    def kill():
        self.invoke(gtk.main_quit)

    def invoke(self, f, *args, **kwargs):
        """
        Invoke f with the given args in the gtkthread and ignore the
        result.
        """
        # always return False so that this function is not executed again
        # see http://www.pygtk.org/pygtk2reference/gobject-functions.html#function-gobject--idle-add
        gobject.idle_add(lambda : f(*args, **kwargs) and False)

    def invoke_s(self, f, *args, **kwargs):
        """
        Invoke f with the given args in the gtkthread and wait for the
        invocations result.
        """
        p = Promise(f)
        self.invoke(p, *args, **kwargs)
        return p.get()

    
def launch_browser():

    window = gtk.Window()
    browser = Webkit.create()

    box = gtk.VBox(homogeneous=False, spacing=0)
    window.add(box)

    scrollview = gtk.ScrolledWindow()
    scrollview.add(browser.browser)

    # if quit_function is not None:
    #     file_menu = gtk.Menu()
    #     quit_item = gtk.MenuItem('Quit')
    #     accel_group = gtk.AccelGroup()
    #     quit_item.add_accelerator('activate',
    #                               accel_group,
    #                               ord('Q'),
    #                               gtk.gdk.CONTROL_MASK,
    #                               gtk.ACCEL_VISIBLE)
    #     window.add_accel_group(accel_group)
    #     file_menu.append(quit_item)
    #     quit_item.connect('activate', quit_function)
    #     quit_item.show()
    #
    #     menu_bar = gtk.MenuBar()
    #     menu_bar.show()
    #     file_item = gtk.MenuItem('File')
    #     file_item.show()
    #     file_item.set_submenu(file_menu)
    #     menu_bar.append(file_item)
    #     box.pack_start(menu_bar, expand=False, fill=True, padding=0)

    # if quit_function is not None:
    #     window.connect('destroy', quit_function)

    box.pack_start(scrollview, expand=True, fill=True, padding=0)

    window.set_default_size(800, 600)
    window.show_all()

    #browser.open_uri(uri)

    return browser


def establish_browser_channel(gtkthread, browser):
    """
    return two functions, receive and execute.
    
    Receive pops a string of a message queue filled up with
    javascript console messages.

    Execute executes the given javascript string in the browser.
    """
    message_queue = Queue.Queue()

    def title_changed(title):
        if title != 'null': message_queue.put(title)

    def console_message(msg):
        message_queue.put(msg)
        return 1 # do not invoke the default console message handler

    #browser.connect_title_changed(title_changed)
    browser.connect('console-message', lambda view, msg, *args: console_message(msg))

    def receive(block=True, timeout=None):
        """
        Like Queue.get but return None if nothing is available
        (instead of raising Empty).
        """
        try:
            return message_queue.get(block=block, timeout=timeout)
        except Queue.Empty:
            return None

    def execute(msg):
        gtkthread.invoke(browser.exec_js, msg)

    return receive, execute

