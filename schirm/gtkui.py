# taken from pywebkitgtk browser.py example
# Copyright (C) 2007, 2008, 2009 Jan Michael Alonzo <jmalonzo@gmai.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import Queue
import threading
import simplejson
import logging
from gettext import gettext as _

import gobject
import gtk
import webkit

import tabbed_window
from promise import Promise
import webkitutils
import webserver

logger = logging.getLogger(__name__)

class attrdict(dict):
    def __getattr__(self, k):
        return self[k]

def gtk_invoke(f, *args, **kwargs):
    """Invoke f with the given args in the gtkthread and ignore the result.
    """
    # always return False so that this function is not executed again
    # see http://www.pygtk.org/pygtk2reference/gobject-functions.html#function-gobject--idle-add
    gobject.idle_add(lambda : bool(f(*args, **kwargs) and False))

def gtk_invoke_s(f, *args, **kwargs):
    """Invoke f with the given args in the gtkthread and wait for the invocations result.
    """
    p = Promise(f)
    gtk_invoke(p, *args, **kwargs)
    return p.get()

class Inspector (gtk.Window):
    def __init__ (self, inspector):
        """initialize the WebInspector class"""
        gtk.Window.__init__(self)
        self.set_default_size(600, 480)

        self._web_inspector = inspector

        self._web_inspector.connect("inspect-web-view",
                                    self._inspect_web_view_cb)
        self._web_inspector.connect("show-window",
                                    self._show_window_cb)
        self._web_inspector.connect("attach-window",
                                    self._attach_window_cb)
        self._web_inspector.connect("detach-window",
                                    self._detach_window_cb)
        self._web_inspector.connect("close-window",
                                    self._close_window_cb)
        self._web_inspector.connect("finished",
                                    self._finished_cb)

        self.connect("delete-event", self._close_window_cb)

    def _inspect_web_view_cb (self, inspector, web_view):
        """Called when the 'inspect' menu item is activated"""
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.props.hscrollbar_policy = gtk.POLICY_AUTOMATIC
        scrolled_window.props.vscrollbar_policy = gtk.POLICY_AUTOMATIC
        webview = webkit.WebView()
        scrolled_window.add(webview)
        scrolled_window.show_all()

        self.add(scrolled_window)
        return webview

    def _show_window_cb (self, inspector):
        """Called when the inspector window should be displayed"""
        self.present()
        return True

    def _attach_window_cb (self, inspector):
        """Called when the inspector should displayed in the same
        window as the WebView being inspected
        """
        return False

    def _detach_window_cb (self, inspector):
        """Called when the inspector should appear in a separate window"""
        return False

    def _close_window_cb (self, inspector, view):
        """Called when the inspector window should be closed"""
        self.hide()
        return True

    def _finished_cb (self, inspector):
        """Called when inspection is done"""
        self._web_inspector = 0
        self.destroy()
        return False

class TerminalWebview(webkit.WebView):

    def __init__(self):
        webkit.WebView.__init__(self)
        self._apply_settings()

        # scale other content besides from text as well
        self.set_full_content_zoom(True)

        # Placeholder for a function to paste to the pty and return
        # True or False when in iframe mode.
        self.paste_to_pty = lambda text: True

        self._track_last_frame()

    def _apply_settings(self):
        # from https://github.com/mackstann/htpicker/blob/dabf5cb377dce9e4b05b39d2b2afa7bb1f11baa7/htpicker/browser.py (public domain)
        # documentation: http://webkitgtk.org/reference/WebKitWebSettings.html
        settings_values = (
            ("enable-default-context-menu",            True,  '1.1.18'),
            ("enable-java-applet",                     False, '1.1.22'),
            ("enable-plugins",                         False, '???'   ),
            ("enable-universal-access-from-file-uris", False, '1.1.13'),
            ("enable-xss-auditor",                     False, '1.1.11'),
            ("tab-key-cycles-through-elements",        False, '1.1.17'),
            ("enable-developer-extras",                True,  '1.1.17'),
            ("user-stylesheet-uri",                    'file://{}'.format(os.path.abspath("schirmstyles.css")), '???'),
            ("default-font-size",                      9,     '???'   ),
            ("default-monospace-font-size",            9,     '???'   ),
            ("enable-caret-browsing",                  False, '1.1.6' ),
            ("enable-developer-extras",                True,  '1.1.13'),
        )

        settings = self.get_settings()
        for key, val, version in settings_values:
            try:
                settings.set_property(key, val)
            except TypeError:
                logger.warn(("Your version of WebKit does not support "
                             "the setting '%s'. This setting requires version "
                             "%s. For best compatibility, use at least version "
                             "1.1.22."), key, version)

    def set_proxy(self, uri):
        webkitutils.set_proxy(uri)

    def _track_last_frame(self):
        """
        Keep the last created child frame of the main webview frame in
        self._last_frame.
        """
        self._last_frame = None

        def frame_created_cb(view, frame, *user_data):
            if frame.get_parent() and not frame.get_parent().get_parent():
                self._last_frame = frame

        self.connect('frame_created', frame_created_cb)

    def eval_js_in_last_frame(self, script_uri, script_source):
        """
        Evaluate the given script in the context of self._last_frame
        and return the resulting string.
        """
        context = self._last_frame.get_global_context()
        return webkitutils.eval_js(context, script_uri, script_source)

    def execute_script(self, src):
        """Like WebView.execute_script but also accept a list of strings."""
        if isinstance(src, basestring):
            super(TerminalWebview, self).execute_script(src)
        else:
            for s in src:
                super(TerminalWebview, self).execute_script(s)

    def zoom_hundred(self):
        """Zoom 100%"""
        if not (self.get_zoom_level() == 1.0):
            self.set_zoom_level(1.0)

    def paste(self):
        """Paste from clipboard."""
        clipb = self.get_clipboard(gtk.gdk.SELECTION_CLIPBOARD)
        text = clipb.wait_for_text()
        if not (text and self.paste_to_pty(text)):
            self.paste_clipboard()

    def paste_xsel(self): # TODO: equivalent of copy_xsel()
        """Paste the current X selection."""
        xclipb = self.get_clipboard(gtk.gdk.SELECTION_PRIMARY)
        text = xclipb.wait_for_text()
        if not (text and self.paste_to_pty(text)):
            self.paste_clipboard()

    # search

    def search(self, s, jump_to=True, mark=True, forward=True, case_sensitive=False, wrap=True):
        # gboolean            webkit_web_view_search_text         (WebKitWebView *webView,
        #                                                          const gchar *text,
        #                                                          gboolean case_sensitive,
        #                                                          gboolean forward,
        #                                                          gboolean wrap);
        if mark:
            # guint               webkit_web_view_mark_text_matches   (WebKitWebView *webView,
            #                                                          const gchar *string,
            #                                                          gboolean case_sensitive,
            #                                                          guint limit);
            res = self.mark_text_matches(s, case_sensitive, 0)
            self.set_highlight_text_matches(True)

        if jump_to:
            res = self.search_text(s, case_sensitive, forward, wrap)

        return res

    def unmark(self):
        self.unmark_text_matches()

    def enable_autoscroll(self, scrolled_window):
        """Setup auto scrolling for this webview.

        Assumes that the webview is embedded inside the
        gtk.ScrolledWindow scrolled_window.

        Autoscrolling keeps the webview scrolled to the bottom when it
        increases its height. It is disabled when the user scrolls up
        and enabled again when he scrolls to the bottom.
        """
        self.__autoscroll = True

        last_adjustment = [0]
        last_upper = [0]
        def value_changed_cb(adjustment, *user_data):
            d_value = adjustment.value - last_adjustment[0]
            d_upper = adjustment.get_upper() - last_upper[0]

            last_adjustment[0] = adjustment.value
            last_upper[0] = adjustment.get_upper()

            if d_upper == 0.0:
                if d_value > 0:
                    if adjustment.value >= (adjustment.get_upper() - adjustment.page_size - 20):
                        # scrolled to (within 20px of) bottom
                        self.__autoscroll = True
                elif d_value < 0:
                    # scrolled up
                    self.__autoscroll = False
            elif d_upper > 0:
                # webview gets bigger
                if self.__autoscroll:
                    # Queue up the required set_value call in the main gtk thread,
                    # otherwise, it won't work (e.g. the set_value call will be
                    # ignored or set back to its original value immediately).
                    gobject.idle_add(lambda : adjustment.set_value(adjustment.get_upper() - adjustment.page_size))

        va = scrolled_window.get_vadjustment()
        # use both events to track upper-bound and value changes
        va.connect('value-changed', value_changed_cb)
        va.connect('changed', value_changed_cb)


class PageProxy (object):
    """Proxy to keep non-webview state in one object."""

    pages = []
    window = None
    schirm_type = None

    @classmethod
    def keypress_cb(self, window, event):
        # all key events are handled in the toplevel window
        # dispatch them to the current tabpage
        tabpage = self.window.get_current_page_component()
        if tabpage:
            page_proxy = tabpage.user_data.get('page_proxy')
            if not self.window.focus_widget:
                self.window.set_focus(page_proxy.webview)
            return page_proxy.handle_keypress(event)
        else:
            return True

    @classmethod
    def _switch_page_cb(self, notebook, page, page_num):
        # called whenever the selected tabpage changes
        # set the window title to the tabs title
        #child = self.window.content_tabs.get_nth_page(self.window.get_current_page())
        child = self.window.get_current_page_component()
        title = self.window.get_tab_label(child)
        self.window.set_title(title)

    @classmethod
    def start(self, schirm_type):
        """Start the ui."""
        self.window = tabbed_window.TabbedWindow()
        self.window.content_tabs.connect('switch-page', self._switch_page_cb)
        self.window.connect('key_press_event', self.keypress_cb)
        self.window.connect('destroy', lambda w: self.quit())
        self.window.connect_tab_close(self.close_tab_cb)

        self.window.set_events(gtk.gdk.KEY_PRESS_MASK | gtk.gdk.KEY_RELEASE_MASK)

        self.schirm_type = schirm_type

        self.new_tab()

        gtk.main()

    @classmethod
    def new_tab(self):
        """Open a tabpage."""
        def _new_tab():
            t = PageProxy()
            self.pages.append(t)
            self.window.new_tab(t.get_component())
            return t
        t = gtk_invoke(_new_tab)

    @classmethod
    def close_tab_cb(self, window, child):
        p = child.user_data.get('page_proxy')
        if p:
            p.destroy()

    @classmethod
    def quit(self):
        gtk.main_quit()

    def __init__(self):
        # communication
        # schirm -> webview communication
        self.input_queue = Queue.Queue()

        # list of scripts to be executed after load_uri/document-load-finished
        self._execute_script_list = []
        self._document_loaded     = False

        # terminal
        self.schirm = self.schirm_type(self)

        # webview <-> schirm http communication
        self.webserver = webserver.Server(self.schirm)

        # webview
        self.webview = TerminalWebview()
        self.webview.set_proxy("http://localhost:{}".format(self.webserver.getport()))
        # webview right-click popup menu: make sure the items will be
        # added in the end, hence the reason for the connect_after
        self.webview.connect_after("populate-popup", self.populate_popup_cb)

        # gtk
        self.box = None
        self.search_forward = True
        self.pages.append(self)
        self.set_title('schirm - loading')
        gtk_invoke(self.webview.grab_focus)

        # gtk setup
        self._construct()
        self.setup_handlers()

        # setup the input queue worker
        self.input_worker = threading.Thread(target=self.input_worker_f)
        self.input_worker.setDaemon(True)
        self.input_worker.start()

    def _construct_search_box(self, parent_box):
        searchbox = gtk.HBox(homogeneous=False)
        searchentry = gtk.Entry() #editable=True, width_chars=80)
        searchentry.set_property('editable', True)
        searchentry.set_property('width_chars', 40)
        searchentry.set_name('search-entry')
        searchlabel = gtk.Label("Search:")

        searchclose = gtk.Button(stock=gtk.STOCK_CLOSE)
        alignment = searchclose.get_children()[0]
        hbox = alignment.get_children()[0]
        image, label = hbox.get_children()
        label.set_text('')

        searchbox.pack_start(searchclose, expand=False, fill=False)
        searchbox.pack_start(searchlabel, expand=False, fill=False, padding=5)
        searchbox.pack_start(searchentry, expand=False, fill=False) #expand=True, fill=False, padding=0)

        searchframe = gtk.Frame()
        searchframe.set_border_width(0)
        searchframe.add(searchbox)
        searchframe.connect_after('realize', lambda w: w.hide()) # hide the searchbar by default

        def entry_changed_cb(editable):
            self.webview.unmark()
            val = editable.get_property('text')
            if val:
                self.webview.search(val, jump_to=True, forward=self.search_forward)
        searchentry.connect('changed', entry_changed_cb)

        searchclose.connect('clicked', lambda *_: self.hide_searchframe())

        parent_box.pack_start(searchframe, expand=False)

        self.searchentry = searchentry
        self.searchframe = searchframe

    def _construct(self):
        """Return a gtk component containing the terminal webview."""
        self.inspector = Inspector(self.webview.get_web_inspector())

        # put the webview inside a ScrolledWindow
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.props.hscrollbar_policy = gtk.POLICY_NEVER #gtk.POLICY_AUTOMATIC
        scrolled_window.props.vscrollbar_policy = gtk.POLICY_AUTOMATIC
        scrolled_window.add(self.webview)
        # gtk.POLICY_NEVER seems to be ignored, hscrollbar renders anyway
        # using styles to hide it, see init_styles()
        scrolled_window.get_hscrollbar().set_name("term_hscrollbar")
        scrolled_window.set_property('border-width', 0)
        scrolled_window.show_all()
        self.scrolled_window = scrolled_window
        self.webview.enable_autoscroll(scrolled_window)

        # vbox to place the webview on top of the searchbox (hidden by
        # default)
        box = gtk.VBox(homogeneous=False, spacing=0)
        box.pack_start(scrolled_window, expand=True, fill=True, padding=0);
        self._construct_search_box(box)
        self.component = box
        self.component.user_data = {'page_proxy': self}

    # building the right-click popup menu
    def populate_popup_cb(self, view, menu):
        # remove all items but the 'inspect element' one
        for ch in list(menu.get_children())[:-2]:
            menu.remove(menu.get_children()[0])

        # customizing the menu
        zoom_in = gtk.ImageMenuItem(gtk.STOCK_ZOOM_IN)
        zoom_in.connect('activate', lambda _: self.webview.zoom_in())
        menu.prepend(zoom_in)

        zoom_out = gtk.ImageMenuItem(gtk.STOCK_ZOOM_OUT)
        zoom_out.connect('activate', lambda _: self.webview.zoom_out())
        menu.prepend(zoom_out)

        zoom_hundred = gtk.ImageMenuItem(gtk.STOCK_ZOOM_100)
        zoom_hundred.connect('activate', lambda _: self.webview.zoom_hundred())
        menu.prepend(zoom_hundred)

        sep = gtk.SeparatorMenuItem()
        menu.prepend(sep)

        new_tab = gtk.ImageMenuItem(gtk.STOCK_ADD) # TODO: set text
        new_tab.set_label("Open Tab")
        new_tab.connect('activate', lambda _: self.new_tab())
        menu.prepend(new_tab)

        sep = gtk.SeparatorMenuItem()
        menu.prepend(sep)

        find = gtk.ImageMenuItem(gtk.STOCK_FIND)
        find.set_label('Search')
        find.connect('activate', lambda _: self.search())
        menu.prepend(find)

        paste = gtk.ImageMenuItem(gtk.STOCK_PASTE)
        paste.connect('activate', lambda _: self.webview.paste()) # TODO: refactor paste to use the queues
        menu.prepend(paste)

        copy = gtk.ImageMenuItem(gtk.STOCK_COPY)
        copy.connect('activate', lambda _: self.webview.copy_clipboard())
        menu.prepend(copy)

        menu.show_all()
        return False

    def get_component(self):
        """Return the gtk component for this terminal."""
        return self.component

    def hide_searchframe(self):
        self.webview.unmark()
        self.searchentry.set_property('text', '')
        self.searchframe.hide()
        self.webview.grab_focus()

    def scroll_page_up(self):
        va = self.scrollview.get_vadjustment()
        va.set_value(max(va.get_value() - va.page_increment, va.lower))

    def scroll_page_down(self):
        va = self.scrollview.get_vadjustment()
        va.set_value(min(va.get_value() + va.page_increment, va.upper - va.page_size))

    def scroll_to_top(self):
        va = self.scrollview.get_vadjustment()
        va.set_value(va.lower)

    def scroll_to_bottom(self):
        va = self.scrollview.get_vadjustment()
        va.set_value(va.upper - va.page_size)

    def search(self, forward=None):
        """Shows the searchbox and performs a search using the boxes current text."""
        if forward != None:
            self._search_forward = bool(forward)

        self.searchframe.show()
        self.searchentry.grab_focus()

        # searching backwards does not work???
        val = self.searchentry.get_property('text')
        if val:
            self.webview.search(val, jump_to=True, forward=self._search_forward)

    def _set_title(self, title):
        # todo: set the tabpage label
        def _set_title():
            self.window.set_tab_label(self.box, title)
            self.window.set_title(title)

        gtk_invoke(_set_title)

    def _execute_script(self, src):
        # do not start executing scripts until the document is loaded
        if self._document_loaded:
            gtk_invoke_s(self.webview.execute_script, src)
        else:
            self._execute_script_list.append(src)

    # public interface

    def execute_script(self, src):
        self.input_queue.put(lambda: self._execute_script(src))

    def load_uri(self, uri):
        self.input_queue.put(lambda: self._load_uri(uri))

    def respond(self, requestid, data, close=True):
        self.input_queue.put(lambda : self.webserver.respond(requestid, data, close))

    def set_title(self, title):
        self.input_queue.put(lambda : self._set_title(title))

    def close(self):
        # close the tab
        self.input_queue.put(lambda : gtk_invoke(self.window.close_tab, self.get_component()))

    # webview implementations

    def handle_keypress(self, event):
        """Handle directly or put keypress envents onto the output_queue.

        Intercept some standard terminal key combos, like shift +
        PageUp/Down for scrolling and deal with them withing gtkui
        directly. All other key events are put on the output queue.
        """
        # keypresses are collected in the tabwindow and dispatched to the active
        # PageProxy tabpage in order to disable default gtk gui behaviour

        # KEY_PRESS
        # KEY_RELEASE            time
        #                        state
        #                        keyval
        #                        string
        name = gtk.gdk.keyval_name(event.keyval)
        string = event.string
        shift = event.state == gtk.gdk.SHIFT_MASK
        alt = event.state == gtk.gdk.MOD1_MASK
        control = event.state == gtk.gdk.CONTROL_MASK

        focus_widget = self.window.focus_widget
        focus_widget_name = focus_widget.get_name() if focus_widget else None

        # handle key commands

        # common ui commands
        if name == 'Page_Up' and shift:
            self.scroll_page_up()
            return True
        elif name == 'Page_Down' and shift:
            self.scroll_page_down()
            return True
        elif name == 'Home' and shift:
            self.scroll_to_top()
            return True
        elif name == 'End' and shift:
            self.scroll_to_bottom()
            return True
        elif name == 'Insert' and shift:
            self.webview.paste_xsel()
            return True

        # custom schirm commands

        elif name == 'S' and event.string == '\x13': # gtk weirdness: uppercase S and \x13 to catch a shift-control-s
            # control-shift-s to search forward
            self.search(forward=True)
            return True
        elif name == 'R' and event.string == '\x12':
            # control-shift-r to search backward
            self.search(forward=False)
            return True
        elif focus_widget_name == 'search-entry' and name == 'g' and control:
            # while searching: control-g to hide the searchframe and the searchresult
            self.hide_searchframe()
            return True

        elif focus_widget is self.webview:
            # terminal input
            self.schirm.keypress(attrdict({'name':name,
                                           'shift':shift,
                                           'alt':alt,
                                           'control':control,
                                           'string':string}))

            # let the webview handle this event too when in iframe mode (-> return False)
            # TODO: add an 'iframe_mode' flag to not propagate keyevents
            #       to the terminal when not in iframe mode
            # in plain terminal mode, don't let the webview handle the event (-> return True)
            return True
        else:
            return False

    def setup_handlers(self):
        """Connect console.log and other handlers."""
        # console.log
        def _console_message_cb(view, msg, line, source_id):

            self.schirm.console_log(msg, line, source_id)
            # 1 .. do not invoke the default console message handler
            # 0 .. invoke other handlers
            return 1

        self.webview.connect('console-message', _console_message_cb)

        # terminal focus
        self.webview.connect('focus-in-event',  lambda *_: self.schirm.set_focus(True))
        self.webview.connect('focus-out-event', lambda *_: self.schirm.set_focus(False))

    def input_worker_f(self):
        """Process the messages from the input_message queue."""
        while True:
            msg_f = self.input_queue.get()
            msg_f()

    def _load_uri(self, uri):
        """Load uri.

        Do not start executing javascript before the document has loaded.
        """
        def execute_pending_scripts():
            for src in self._execute_script_list:
                gtk_invoke_s(self.webview.execute_script, src)
            self._execute_script_list = []
            self._document_loaded = True

        load_finished_id = None
        def load_finished_cb(webview, frame):
            self.input_queue.put(execute_pending_scripts)
            if load_finished_id:
                webview.disconnect(load_finished_id)

        load_finished_id = gtk_invoke_s(lambda : self.webview.connect('document-load-finished', load_finished_cb))

        # load uri
        gtk_invoke(lambda : self.webview.load_uri(uri))

    def destroy(self):
        # TODO:
        # self.webview.destroy()
        # self.webserver.stop()
        # self.box.destroy()
        # ... ???
        pass
