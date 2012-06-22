import gobject
import gtk
import pango

# provide tabbed gui

class TabLabel (gtk.HBox):
    """A class for Tab labels"""

    __gsignals__ = {
        "close": (gobject.SIGNAL_RUN_FIRST,
                  gobject.TYPE_NONE,
                  (gobject.TYPE_OBJECT,))
        }

    def __init__(self, title, child):
        """initialize the tab label"""
        gtk.HBox.__init__(self, False, 4)
        self.title = title
        self.child = child
        self.label = gtk.Label(title)
        self.label.props.max_width_chars = 30
        self.label.set_ellipsize(pango.ELLIPSIZE_MIDDLE)
        self.label.set_alignment(0.0, 0.5)

        icon = gtk.image_new_from_stock(gtk.STOCK_ORIENTATION_PORTRAIT, gtk.ICON_SIZE_BUTTON)
        close_image = gtk.image_new_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
        close_button = gtk.Button()
        close_button.set_relief(gtk.RELIEF_NONE)
        close_button.connect("clicked", self._close_tab, child)
        close_button.set_image(close_image)
        self.pack_start(icon, False, False, 0)
        self.pack_start(self.label, True, True, 0)
        self.pack_start(close_button, False, False, 0)

        self.set_data("label", self.label)
        self.set_data("close-button", close_button)
        self.connect("style-set", tab_label_style_set_cb)

    def set_label(self, text):
        """sets the text of this label"""
        self.label.set_label(text)

    def get_label(self):
        return self.label.get_text()

    def _close_tab(self, widget, child):
        self.emit("close", child)


def tab_label_style_set_cb (tab_label, style):
    context = tab_label.get_pango_context()
    metrics = context.get_metrics(tab_label.style.font_desc, context.get_language())
    char_width = metrics.get_approximate_digit_width()
    (width, height) = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)
    tab_label.set_size_request(20 * pango.PIXELS(char_width) + 2 * width,
                               pango.PIXELS(metrics.get_ascent() +
    metrics.get_descent()) + 8)


class ContentPane (gtk.Notebook):

    __gsignals__ = {
        "focus-view-title-changed": (gobject.SIGNAL_RUN_FIRST,
                                     gobject.TYPE_NONE,
                                     (gobject.TYPE_OBJECT, gobject.TYPE_STRING,)),
        }

    def __init__ (self):
        """initialize the content pane"""
        gtk.Notebook.__init__(self)
        self.props.scrollable = True
        self.props.homogeneous = True
        self.show_all()
        self._hovered_uri = None

    def new_tab (self, content):
        """creates a new tab with the given content as its child"""
        self._construct_tab_view(content)

    def _construct_tab_view (self, content):
        # create the tab
        label = TabLabel("labeltext", content)
        label.connect("close", self._close_tab)
        label.show_all()

        new_tab_number = self.append_page(content, label)
        self.set_tab_label_packing(content, False, False, gtk.PACK_START)
        self.set_tab_label(content, label)

        # hide the tab if there's only one
        self.set_show_tabs(self.get_n_pages() > 1)

        self.show_all()
        self.set_current_page(new_tab_number)

    def _populate_page_popup_cb(self, view, menu):
        # misc
        # if self._hovered_uri:
        #     open_in_new_tab = gtk.MenuItem(_("Open Link in New Tab"))
        #     open_in_new_tab.connect("activate", self._open_in_new_tab, view)
        #     menu.insert(open_in_new_tab, 0)
        #     menu.show_all()
        pass

    def _close_tab(self, label, child):
        page_num = self.page_num(child)
        if page_num != -1:
            view = child.get_child()
            view.destroy()
            self.remove_page(page_num)
        self.set_show_tabs(self.get_n_pages() > 1)

    # set the tabs label
    def _title_changed_cb(self, view, frame, title):
        child = self.get_nth_page(self.get_current_page())
        label = self.get_tab_label(child)
        label.set_label(title)

class TabbedWindow(gtk.Window):

    def __init__(self):
        gtk.Window.__init__(self)

        self.set_title("Schirm")
        self.content_tabs = ContentPane()

        # example: add toolbar + tab panel:
        # vbox = gtk.VBox(spacing=1)
        # vbox.pack_start(toolbar, expand=False, fill=False)
        # vbox.pack_start(self.content_tabs)
        # self.add(vbox)

        self.add(self.content_tabs)

        self.set_default_size(800, 600)
        self.show_all()

    def new_tab(self, content):
        self.content_tabs.new_tab(content)

    def get_current_page_component(self):
        n = self.content_tabs.get_current_page()
        if n <= -1:
            return None
        else:
            return self.content_tabs.get_nth_page(n)

    def set_tab_label(self, child_component, title):
        child = self.content_tabs.get_nth_page(self.content_tabs.get_current_page())
        label = self.content_tabs.get_tab_label(child)
        label.set_label(title)

    def get_tab_label(self, child_component):
        child = self.content_tabs.get_nth_page(self.content_tabs.get_current_page())
        label = self.content_tabs.get_tab_label(child)
        return label.get_label()

if __name__ == '__main__':
    w = TabbedWindow()
    # test content
    w.new_tab(gtk.Button(stock=gtk.STOCK_CLOSE))
    w.new_tab(gtk.Button(stock=gtk.STOCK_CLOSE))
    w.new_tab(gtk.Button(stock=gtk.STOCK_CLOSE))
    gtk.main()
