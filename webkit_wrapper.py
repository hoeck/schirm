import time
import Queue
import thread
import threading
import urllib
import traceback

import gtk
import gobject

from promise import Promise

try:
    import webkit
except:
    pass

class Webkit(object):

    @classmethod
    def create(self):
        return self(webkit.WebView())

    def __init__(self, browser):
        self.browser = browser

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

    def open_uri(self, uri):
        self.browser.open(uri)


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
    message_queue = Queue.Queue()

    def title_changed(title):
        if title != 'null': message_queue.put(title)

    browser.connect_title_changed(title_changed)

    def receive(block=False):
        if message_queue.empty() and not block:
            return None
        else:
            return message_queue.get()

    def send(msg):
        gtkthread.invoke(browser.exec_js, msg)

    return receive, send

