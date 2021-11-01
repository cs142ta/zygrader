"""Window: The zygrader window manager and input handling"""
import curses
import inspect
import typing

from zygrader.ui import themes, colors
from zygrader.config import preferences

from . import events
from .events import Event
from .layers import ComponentLayer
from .utils import add_str, resize_window


def get_stack_info(layer: ComponentLayer, skip=2):
    # Ignore this and the previous stack frame by default (2)
    stack = inspect.stack()[skip][0]
    caller = inspect.getframeinfo(stack)

    # Remove the beginning of the filepath
    index = caller.filename.find("zygrader/zygrader/")
    filename = caller.filename[index + len("zygrader/zygrader/"):]

    class_type = layer.__class__

    return (f"{filename}:{caller.lineno} in"
            f" {caller.function}\n\t{class_type} {layer}")


class WinContext:
    """A wrapper for the current window context when components execute a callback"""
    def __init__(self, window, event: Event, component, custom_data):
        self.window = window
        self.event = event
        self.component = component
        self.data = custom_data


DEBUG_CONSOLE_HEIGHT = 5


class Window:
    INSTANCE = None

    @staticmethod
    def get_window() -> "Window":
        if Window.INSTANCE:
            return Window.INSTANCE
        return None

    def update_preferences(self):
        theme_key = preferences.get("theme")
        new_theme = themes.THEMES[theme_key]
        if new_theme is not self.theme:
            new_theme.adjust_screen_colors()
        self.theme = new_theme
        self.unicode_mode = preferences.get("unicode_mode")
        self.clear_filter = preferences.get("clear_filter")

        self.update_window()

    def __init__(self, callback, window_name, user_name, args):
        """Initialize screen and run callback function"""
        Window.INSTANCE = self
        self.name = window_name
        self.__user_name = user_name

        self.theme = None

        # Debug console data
        self.__debug_mode = args.debug
        self.__debug_lines = []
        self.__debug_win = None

        self.layers: typing.List[ComponentLayer] = []
        self.active_layer: ComponentLayer = None

        try:
            curses.wrapper(self.__init_curses, callback, args)
        except Exception:
            curses.endwin()
            print("Zygrader layer stack:")
            self.print_stack()
            print()
            raise

        # Cleanup when finished accepting input
        self.stdscr.clear()
        self.stdscr.refresh()
        curses.endwin()

    def __init_curses(self, stdscr, callback, args):
        """Configure basic curses settings"""
        self.stdscr = stdscr

        colors.init_colors()

        self.__get_window_dimensions()

        # Hide cursor
        curses.curs_set(0)

        # Create header
        self.header = curses.newwin(1, self.cols, 0, 0)
        self.header.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))
        self.__header_title = "Main Menu"
        self.__header_dirty = True

        # All user input handling is done inside the EventManager class.
        self.event_manager = events.EventManager()

        if self.__debug_mode:
            self.__debug_win = curses.newwin(DEBUG_CONSOLE_HEIGHT, self.cols,
                                             self.rows, 0)

        # Execute callback with a reference to the window object
        callback(self, args)

    def __get_window_dimensions(self):
        # Restrict the window height if the debug console is open
        if self.__debug_mode:
            rows, cols = self.stdscr.getmaxyx()
            self.rows, self.cols = rows - DEBUG_CONSOLE_HEIGHT, cols
            return
        self.rows, self.cols = self.stdscr.getmaxyx()

    def __resize_terminal(self):
        """Function to run after resize events in the terminal"""
        self.__get_window_dimensions()
        curses.resize_term(self.rows, self.cols)

        resize_window(self.header, 1, self.cols)
        for layer in self.layers:
            layer.resize_component(self.rows, self.cols)

    def get_header_separator(self):
        if not self.unicode_mode:
            return themes.THEMES["Default"].separator
        return self.theme.separator

    def get_header_bookends(self):
        if not self.unicode_mode:
            return themes.THEMES["Default"].bookends
        return self.theme.bookends

    def draw_header(self):
        """Set the header text"""
        self.header.erase()
        separator = self.get_header_separator()

        # Store the cursor location
        loc = curses.getsyx()

        display_text = (f"{self.name} {separator} {self.__header_title}"
                        f" {separator} {self.__user_name}")

        if self.event_manager.insert_mode:
            display_text += f" {separator} INSERT"
        elif self.event_manager.mark_mode:
            display_text += f" {separator} VISUAL"

        bookend = self.get_header_bookends()
        display_text = f'{bookend} {display_text} {bookend}'

        # Centered header
        row = self.cols // 2 - len(display_text) // 2
        add_str(self.header, 0, row, display_text)

        color_a = curses.color_pair(colors.COLOR_PAIR_HEADER)
        color_b = curses.color_pair(colors.COLOR_PAIR_HEADER_ALT)
        try:
            for row in range(self.cols):
                if (row // 2) % 2 == 0:
                    self.header.chgat(0, row, color_a | curses.A_BOLD)
                else:
                    self.header.chgat(0, row, color_b | curses.A_BOLD)
        except:
            pass

        self.header.noutrefresh()
        self.__header_dirty = False

        curses.setsyx(*loc)

    def __update_header_title(self):
        """Set the text to be drawn centered in the header"""
        if self.active_layer and self.active_layer.title:
            self.__header_title = self.active_layer.title
        elif self.active_layer:
            # Find a lower layer with a title
            for layer in reversed(self.layers):
                if layer.title:
                    self.__header_title = layer.title
        else:
            # Use default text
            self.__header_title = "Main Menu"

        self.__header_dirty = True

    def print_stack(self):
        for i, layer in enumerate(reversed(self.layers)):
            print(f"[{i}]: {layer.stack_msg}")

    def register_layer(self, layer: ComponentLayer, header_title="", skip=2):
        """Register a layer in the event loop."""
        # Always disable insert or visual mode from previous layers
        self.event_manager.disable_modes()

        self.layers.append(layer)
        self.active_layer = layer
        layer.set_title(header_title)

        self.__update_header_title()

        # Run any finalizing actions this layer needs
        layer.build()

        # Create the stack message with the completed layer information
        layer.stack_msg = get_stack_info(layer, skip)

        if layer.is_text_input:
            self.event_manager.insert_mode = True

    def unregister_layer(self):
        """Remove the top layer from the stack."""
        layer = self.layers.pop()
        self.active_layer = self.layers[-1] if self.layers else None
        if self.active_layer:
            self.active_layer.redraw = True

        layer.destroy()

        self.__update_header_title()

        # Always disable insert or visual mode
        self.event_manager.disable_modes()

        # Clear search fields upon returning to lists
        if (self.clear_filter and self.active_layer
                and self.active_layer.is_clearable):
            self.active_layer.clear_search_text()

    def run_layer(self, layer: ComponentLayer, title=""):
        self.register_layer(layer, title, skip=3)

        while layer in self.layers:
            self.build()
            layer.update(self.event_manager)
            self.handle_events()
            self.draw()

    def loop(self):
        """Handle events in a loop until the program is exited."""
        # When there are no more layers, exit the main loop
        while self.layers:
            self.build()
            self.handle_events()
            # Recalculate windows and redraw
            self.draw()

    def build(self):
        for layer in self.layers:
            if layer.rebuild:
                layer.build()

    def handle_events(self):
        # Get the event on the front of the queue
        event = self.event_manager.get_event()

        # Events are either handled directly by the window manager or
        # are passed to the active component layer.
        if event.type == Event.QUIT:
            self.layers.clear()
        elif event.type == Event.HEADER_UPDATE:
            self.__header_dirty = True
        elif event.type == Event.LAYER_CLOSE:
            self.unregister_layer()
        elif event.type == Event.RESIZE:
            self.__resize_terminal()
        else:
            self.active_layer.event_handler(event, self.event_manager)

    def __tag_visible_layers(self):
        """If any layer needs drawing then tag all visible layers below it for redraw."""
        for layer in reversed(self.layers):
            layer.redraw = True
            if layer.blocking:
                break

    def draw(self):
        """Draw each component in the stack"""
        if not any(layer.redraw
                   for layer in self.layers) and not self.__header_dirty:
            return

        self.update_window()
        self.stdscr.erase()
        self.stdscr.noutrefresh()

        self.draw_header()
        if self.__debug_mode:
            self.draw_debug_console()

        self.__tag_visible_layers()
        for layer in self.layers:
            if layer.redraw:
                layer.draw()

        # All windows have been tagged for redraw with noutrefresh,
        # now do a single draw pass with doupdate.
        curses.doupdate()

    def draw_debug_console(self):
        self.__debug_win.erase()

        # First row is a separator line
        self.__debug_win.hline(0, 0, "_", self.cols)

        row_num = 1
        display_rows = self.__debug_lines[-(DEBUG_CONSOLE_HEIGHT - 1):]
        for row in display_rows:
            add_str(self.__debug_win, row_num, 0, row)
            row_num += 1

        self.__debug_win.noutrefresh()

    def debug(self, line: str):
        self.__debug_lines.append(line)

    def update_window(self):
        self.stdscr.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))
