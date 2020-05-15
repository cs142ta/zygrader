import curses
import os
import queue
import threading

from . import components
from .utils import add_str, resize_window
from .. import config
from .. import data

from . import UI_GO_BACK

UI_LEFT = 0
UI_RIGHT = 1
UI_CENTERED = 2

class Event:
    NONE = -1
    BACKSPACE = 0
    ENTER = 1
    UP = 2
    DOWN = 3
    LEFT = 4
    RIGHT = 5
    INPUT = 6
    ESC = 7

    def __init__(self, event_type, value):
        self.type = event_type
        self.value = value

class Window:
    EVENT_REFRESH_LIST = "flags_and_locks"
    CANCEL = -1

    instance = None

    @staticmethod
    def get_window() -> "Window":
        if Window.instance:
            return Window.instance
        return None

    def update_preferences(self):
        self.dark_mode = config.user.is_preference_set("dark_mode")
        self.christmas_mode = config.user.is_preference_set("christmas_mode")
        self.vim_mode = config.user.is_preference_set("vim_mode")
        self.left_right_menu_nav = config.user.is_preference_set("left_right_arrow_nav")
        self.clear_filter = config.user.is_preference_set("clear_filter")

    def get_input(self, input_win):
        """Get input and handle resize events"""
        event = Event.NONE
        event_value = Event.NONE

        # Nodelay causes exception when no input is given
        input_code = input_win.getch()
        if input_code == -1:
            event = Event.NONE
            return event, event_value

        # Cases for each type of input
        if input_code == curses.KEY_RESIZE:
            self.__resize_terminal()
            curses.flushinp()
        elif input_code in {curses.KEY_ENTER, ord('\n'), ord('\r')}:
            event = Event.ENTER
        elif input_code == curses.KEY_UP:
            event = Event.UP
        elif input_code == curses.KEY_DOWN:
            event = Event.DOWN
        elif input_code == curses.KEY_LEFT:
            event = Event.LEFT
        elif input_code == curses.KEY_RIGHT:
            event = Event.RIGHT
        elif self.vim_mode:
            event, event_value = self.get_input_vim(input_code)
        elif input_code == "\x1b":
            event = Event.ESC
        elif input_code == curses.KEY_BACKSPACE:
            event = Event.BACKSPACE
        elif input_code:
            event = Event.INPUT
            event_value = chr(input_code)

        self.header_offset += 1
        return event, event_value

    def get_input_vim(self, input_code):
        event = Event.NONE
        event_value = Event.NONE

        if input_code == curses.KEY_BACKSPACE and self.insert_mode:
            event = Event.BACKSPACE
        elif input_code == 27:
            if self.insert_mode:
                self.insert_mode = False
                self.draw_header()
                event = Event.NONE
            else:
                event = Event.ESC
        elif not self.insert_mode and chr(input_code) == "i":
            self.insert_mode = True
            self.draw_header()
            event = Event.NONE
        elif not self.insert_mode:
            if chr(input_code) == "h":
                event = Event.LEFT
            elif chr(input_code) == "j":
                event = Event.DOWN
            elif chr(input_code) == "k":
                event = Event.UP
            elif chr(input_code) == "l":
                event = Event.RIGHT
            else:
                event = Event.NONE
        elif self.insert_mode:
            event = Event.INPUT
            event_value = chr(input_code)

        return event, event_value

    def input_thread_fn(self):
        # Create window for input
        input_win = curses.newwin(0, 0, 1, 1)
        input_win.keypad(True)
        input_win.nodelay(True)

        while True:
            flush = False
            if not self.take_input.is_set():
                flush = True
            self.take_input.wait()
            if flush:
                curses.flushinp()
            event, event_value = self.get_input(input_win)
            if not self.take_input.is_set():
                continue
            if event != Event.NONE:
                self.event_queue.put_nowait(Event(event, event_value))

            # Kill thread at end
            if self.stop_input:
                break

    def consume_input(self) -> Event:
        """Consume one token of input from the user"""
        return self.event_queue.get()

    def file_system_event(self, identifier, component):
        if identifier == Window.EVENT_REFRESH_LIST:
            component.create_lines(None)
            component.draw()
            self.draw()

    def __init__(self, callback, window_name):
        Window.instance = self

        """Initialize screen and run callback function"""
        self.name = window_name
        self.insert_mode = False
        self.event = Event.NONE
        self.event_value = Event.NONE

        self.event_queue = queue.Queue()

        # Create a thread to handle input separately
        # The main thread handles drawing
        self.input_thread = threading.Thread(target=self.input_thread_fn, name="Input", daemon=True)
        self.stop_input = False

        # Add an event to toggle input thread
        self.take_input = threading.Event()
        self.take_input.set()

        # Set user preference variables
        self.update_preferences()

        curses.wrapper(self.__init_curses, callback)

        # Cleanup when finished accepting input
        self.stop_input = True
        self.stdscr.clear()
        self.stdscr.refresh()
        curses.endwin()

    def __init_curses(self, stdscr, callback):
        """Configure basic curses settings"""
        self.stdscr = stdscr

        self.__get_window_dimensions()

        # Hide cursor
        curses.curs_set(0)

        self.__init_colors()

        # Create header
        self.header = curses.newwin(1, self.cols, 0, 0)
        self.header.bkgd(" ", curses.color_pair(1))

        # Stacks for Components and header titles
        self.components = []
        self.header_titles = [""]

        # Used for animated themes
        self.header_offset = 0
        self.__header_title = ""
        self.__header_title_load = ""
        self.__email_text = ""

        # Input is now ready to start
        self.input_thread.start()

        # Execute callback with a reference to the window object
        callback(self)
    
    def __get_window_dimensions(self):
        self.rows, self.cols = self.stdscr.getmaxyx()

    def __init_colors(self):
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)

        # Holiday LIGHT variant
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_GREEN)
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_RED)

        # Holiday DARK variant
        curses.init_pair(5, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(6, curses.COLOR_RED, curses.COLOR_BLACK)

        curses.init_pair(7, curses.COLOR_CYAN, curses.COLOR_BLACK)

    def __resize_terminal(self):
        """Function to run after resize events in the terminal"""
        self.__get_window_dimensions()
        curses.resize_term(self.rows, self.cols)

        for component in self.components:
            component.resize(self.rows, self.cols)

        self.draw(True)

    def get_header_colors(self):
        if self.dark_mode:
            return curses.color_pair(5), curses.color_pair(6)
        return curses.color_pair(3), curses.color_pair(4)

    def set_email(self, email):
        self.__email_text = email

    def set_header(self, text):
        """Load a string to be used for the next component"""
        self.__header_title_load = text

    def draw_header(self, text=""):
        """Set the header text"""        
        self.header.erase()
        resize_window(self.header, 1, self.cols)

        if self.header_titles[-1]:
            self.__header_title = self.header_titles[-1]

        if self.__header_title:
            display_text = f"{self.name} | {self.__header_title}"
        else:
            display_text = self.name

        if self.__email_text:
            display_text += f" | {self.__email_text}"

        if self.insert_mode:
            display_text += " | INSERT"

        # Centered header
        x = self.cols // 2 - len(display_text) // 2
        add_str(self.header, 0, x, display_text)

        # Christmas theme
        if self.christmas_mode:
            red, green = self.get_header_colors()

            for x in range(self.cols):
                if ((x // 2) + self.header_offset) % 2 is 0:
                    self.header.chgat(0, x, red | curses.A_BOLD)
                else:
                    self.header.chgat(0, x, green | curses.A_BOLD)

        self.header.refresh()

    def draw(self, flush=False):
        """Draw each component in the stack"""
        self.update_window()
        self.stdscr.erase()
        self.stdscr.refresh()
        
        self.draw_header()
        
        # Find last blocking component
        block_index = 0
        for index in reversed(range(len(self.components))):
            if self.components[index].blocking:
                block_index = index
                break

        for component in self.components[block_index:]:
            component.draw()
        
        if flush:
            pass
            # curses.flushinp()

    def update_window(self):
        if self.dark_mode:
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        else:
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.draw_header()

    def component_init(self, component):
        # Disable insertion mode on component change
        self.insert_mode = False

        self.components.append(component)
        if self.__header_title_load:
            self.header_titles.append(self.__header_title_load)
            self.__header_title_load = ""
        else:
            self.header_titles.append(self.header_titles[-1])

        self.draw()

    def component_deinit(self):
        # Disable insertion mode on component change
        self.insert_mode = False

        self.components.pop()
        self.header_titles.pop()
        self.draw()

    def create_popup(self, title, message, align=components.Popup.ALIGN_CENTER):
        """Create a popup with title and message that returns after enter"""
        pop = components.Popup(self.rows, self.cols, title, message, align)
        self.component_init(pop)
        
        while True:
            event = self.consume_input()

            if event.type == Event.ENTER:
                break

        self.component_deinit()
    
    def create_bool_popup(self, title, message, align=components.Popup.ALIGN_CENTER):
        """Create a popup with title and message that returns true/false"""
        options = ["YES", "NO"]
        popup = components.OptionsPopup(self.rows, self.cols, title, message, options, align)
        self.component_init(popup)
        
        while True:
            event = self.consume_input()

            if event.type in {Event.LEFT, Event.UP}:
                popup.previous()
            elif event.type in {Event.RIGHT, Event.DOWN}:
                popup.next()
            elif event.type == Event.ENTER:
                break

            self.draw()

        self.component_deinit()

        return popup.selected() == options[0]

    def create_options_popup(self, title, message, options, align=components.Popup.ALIGN_CENTER):
        """Create a popup with multiple options that can be selected with the keyboard"""
        popup = components.OptionsPopup(self.rows, self.cols, title, message, options, align)
        self.component_init(popup)

        while True:
            event = self.consume_input()

            if event.type in {Event.LEFT, Event.UP}:
                popup.previous()
            elif event.type in {Event.RIGHT, Event.DOWN}:
                popup.next()
            elif event.type == Event.ENTER:
                break

            self.draw()

        self.component_deinit()

        return popup.selected()

    def create_list_popup(self, title, input_data=None, callback=None, list_fill=None):
        """Create a popup with a list of options that can be scrolled and selected

        If input_data (list) is supplied, the list will be drawn from the string representations
        of that data. If list_fill (function) is supplied, then list_fill will be called to generate
        a list to be drawn.
        """
        popup = components.ListPopup(self.rows, self.cols, title, input_data, list_fill)
        self.component_init(popup)

        while True:
            event = self.consume_input()

            if event.type == Event.DOWN:
                popup.down()
            elif event.type == Event.UP:
                popup.up()
            elif event.type == Event.LEFT and self.left_right_menu_nav:
                break
            elif (event.type == Event.ENTER) or (event.type == Event.RIGHT and self.left_right_menu_nav):
                if popup.selected() is UI_GO_BACK:
                    break
                elif callback:
                    callback(popup.selected())
                else:
                    break

            self.draw()

        self.component_deinit()

        return popup.selected()

    def create_filename_input(self, purpose):
        """Get a valid filename from the user"""
        full_prompt = f"Enter the path and filename for {purpose} [~ is supported]"

        while True:
            path = self.create_text_input(full_prompt)
            if path == Window.CANCEL:
                return None

            path = os.path.expanduser(path)
            if os.path.exists(os.path.dirname(path)):
                return path

            msg = [f"Path {os.path.dirname(path)} does not exist!"]
            self.create_popup("Invalid Path", msg)
    
    def create_text_input(self, prompt, text="", mask=components.TextInput.TEXT_NORMAL):
        """Get text input from the user"""
        text = components.TextInput(1, 0, self.rows, self.cols, prompt, text, mask)
        self.component_init(text)

        if self.vim_mode:
            self.insert_mode = True
            self.draw()

        while True:
            event = self.consume_input()

            if event.type == Event.ENTER:
                break
            elif event.type == Event.BACKSPACE:
                text.delchar()
            elif event.type == Event.INPUT:
                text.addchar(event.value)
            elif event.type == Event.LEFT:
                text.left()
            elif event.type == Event.RIGHT:
                text.right()
            elif event.type == Event.ESC:
                break

            self.draw()

        self.component_deinit()
        text.close()
        
        if self.event == Event.ESC:
            return Window.CANCEL
        return text.text

    def create_filtered_list(self, prompt, input_data=None, callback=None, list_fill=None, filter_function=None, watch=None):
        """
        If input_data (list) is supplied, the list will be drawn from the string representations
        of that data. If list_fill (function) is supplied, then list_fill will be called to generate
        a list to be drawn.
        """
        list_input = components.FilteredList(1, 0, self.rows - 1, self.cols, input_data, list_fill, prompt, filter_function)
        self.component_init(list_input)

        if watch:
            # Register paths to trigger file system events
            data.fs_watch.fs_watch_register(watch, Window.EVENT_REFRESH_LIST, lambda identifier: self.file_system_event(identifier, list_input))

        while True:
            event = self.consume_input()

            if event.type == Event.DOWN:
                list_input.down()
            elif event.type == Event.UP:
                list_input.up()
            elif event.type == Event.LEFT and self.left_right_menu_nav:
                break
            elif event.type == Event.BACKSPACE:
                list_input.delchar()
            elif event.type == Event.INPUT:
                list_input.addchar(event.value)
            elif (event.type == Event.ENTER) or (event.type == Event.RIGHT and self.left_right_menu_nav):
                if callback and list_input.selected() != UI_GO_BACK:
                    list_input.dirty = True
                    callback(list_input.selected())

                    if self.clear_filter:
                        list_input.clear_filter()
                    list_input.flag_dirty()

                else:
                    break
            
            list_input.draw()

        if watch:
            data.fs_watch.fs_watch_unregister(Window.EVENT_REFRESH_LIST)

        list_input.clear()
        self.component_deinit()

        if self.event == Event.LEFT and self.left_right_menu_nav:
            return UI_GO_BACK

        return list_input.selected()

    def new_logger(self):
        logger = components.Logger(1, 0, self.rows - 1, self.cols)
        self.component_init(logger)

        return logger

    def remove_logger(self, logger):
        self.component_deinit()
