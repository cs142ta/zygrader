import calendar
import curses
import datetime
from collections import Iterable
from typing import Callable, List

from .utils import add_str, resize_window
from zygrader.config import preferences
from . import colors
from zygrader.ui.displaystring import DisplayStr


class Component:
    def resize(self, rows, cols):
        raise NotImplementedError

    def draw(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class Popup(Component):
    # Semi-arbitrary max/min restrictions for popups
    ROWS_MAX = 20
    COLS_MAX = 100
    PADDING = 3

    ALIGN_LEFT = 0
    ALIGN_CENTER = 1

    def __init__(self, height, width, title, message):
        self.available_rows = height
        self.available_cols = width

        self.title = title
        self.message = message
        self.align = Popup.ALIGN_LEFT

        self.__calculate_size()

        self.window = curses.newwin(self.rows, self.cols, self.y, self.x)
        self.window.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))

        curses.curs_set(0)

    def __calculate_size(self):
        self.rows = min(Popup.ROWS_MAX,
                        self.available_rows - (Popup.PADDING * 2))
        self.cols = min(Popup.COLS_MAX,
                        self.available_cols - (Popup.PADDING * 2))
        self.y = (self.available_rows - self.rows) // 2
        self.x = (self.available_cols - self.cols) // 2

    def __find_wrap_index(self, line: str, max_line_len: int) -> int:
        WRAP_CHARS = {" ", "/"}

        max_line_len = self.cols - 2 * Popup.PADDING
        max_cutoff = min(len(line), max_line_len)

        cutoff = max_cutoff
        while cutoff > 0 and str(line[cutoff]) not in WRAP_CHARS:
            cutoff -= 1

        return max_cutoff if cutoff == 0 else cutoff

    def __calculate_wrapping(self, line: str) -> list:
        wrapped_lines = []
        if line == "":
            return [line]

        max_line_len = self.cols - 2 * Popup.PADDING

        while line:
            if len(line) > max_line_len:
                wrap_index = self.__find_wrap_index(line, max_line_len)
                wrapped_lines.append(line[:wrap_index])

                # If it's too long, wrap again
                line = line[wrap_index:]
            else:
                wrapped_lines.append(line)
                break
        return wrapped_lines

    def __draw_message(self, message):
        display_lines = [
            disp_line for msg_line in message
            for disp_line in self.__calculate_wrapping(msg_line)
        ]
        longest_line = max((displayline for displayline in display_lines),
                           key=len)

        left_align_x = self._centered_start_x(longest_line)
        message_y = self._centered_start_y(display_lines)
        message_row = 0
        for line in display_lines:
            add_str(
                self.window, message_y + message_row, left_align_x if self.align
                == Popup.ALIGN_LEFT else self._centered_start_x(line), line)
            message_row += 1

    def draw_title(self):
        title_x = self._centered_start_x(self.title)
        add_str(self.window, 0, title_x, self.title)

    def draw_text(self):
        self.window.erase()
        self.window.border()

        if isinstance(self.message, Iterable):
            message = list(self.message)
        else:
            message = self.message()

        # Draw lines of message
        self.__draw_message(message)

        self.draw_title()

    def draw(self):
        self.draw_text()

        # Draw prompt to exit popup
        enter_string = "Press Enter"

        y = self._text_bottom_y()
        x = self._text_right_x() - len(enter_string)
        add_str(self.window, y, x, enter_string)

        self.window.noutrefresh()

    def resize(self, rows, cols):
        self.available_rows = rows
        self.available_cols = cols

        self.__calculate_size()

        try:
            self.window.mvwin(self.y, self.x)
        except:
            pass

        resize_window(self.window, self.rows, self.cols)

    def set_message(self, message):
        self.message = message

    def set_align(self, align):
        self.align = align

    def _text_bottom_y(self):
        return self.rows - 2

    def _text_right_x(self):
        return self.cols - 1 - Popup.PADDING

    def _centered_start_x(self, line):
        return self.cols // 2 - len(line) // 2

    def _centered_start_y(self, line_list):
        return self.rows // 2 - len(line_list) // 2


class OptionsPopup(Popup):
    def __init__(self, height, width, title, message, options=[]):
        super().__init__(height, width, title, message)
        self.set_options(options)

    def draw(self):
        super().draw_text()
        y = self._text_bottom_y()

        previous_length = 0
        index = 0
        for option in self.options:
            x = self.__options_start_x() + previous_length
            if index == self.index:
                add_str(self.window, y, x, option, curses.A_STANDOUT)
            else:
                add_str(self.window, y, x, option)

            previous_length += len(option) + 2
            index += 1

        curses.curs_set(0)
        self.window.noutrefresh()

    def set_options(self, options):
        self.options = options
        self.index = len(options) - 1

        options_strs_len = sum([len(o) for o in options])
        spaces_between_len = 2 * (len(options) - 1)
        self.options_length = options_strs_len + spaces_between_len

    def next(self):
        self.index = (self.index + 1) % len(self.options)

    def previous(self):
        self.index = (self.index - 1) % len(self.options)

    def first(self):
        self.index = 0

    def last(self):
        self.index = len(self.options) - 1

    def selected(self):
        return self.options[self.index]

    def __options_start_x(self):
        return self._text_right_x() - self.options_length


class DatetimeSpinner(Popup):
    NO_DATE = "datetime_no_date"

    # All available fields are fixed-width and intuitively spinnable
    # Other fields would likely require higher complexity to be safe
    __FIELDS = {
        'b': {
            'name': 'month',
            'unit': None,
            'formatter': lambda time: time.strftime('%b')
        },
        'm': {
            'name': 'month',
            'unit': None,
            'formatter': lambda time: time.strftime('%m')
        },
        'd': {
            'name': 'day',
            'unit': datetime.timedelta(days=1),
            'formatter': lambda time: time.strftime('%d')
        },
        'Y': {
            'name': 'year',
            'unit': None,
            # The built in Y formatter does not zero-pad
            'formatter': lambda time: f"{time.year:0>4}"
        },
        'I': {
            'name': 'hour-12',
            'unit': datetime.timedelta(hours=1),
            'formatter': lambda time: time.strftime('%I')
        },
        'H': {
            'name': 'hour-24',
            'unit': datetime.timedelta(hours=1),
            'formatter': lambda time: time.strftime('%H')
        },
        'M': {
            'name': 'minute',
            'unit': datetime.timedelta(minutes=1),
            'formatter': lambda time: time.strftime('%M')
        },
        'S': {
            'name': 'second',
            'unit': datetime.timedelta(seconds=1),
            'formatter': lambda time: time.strftime('%S')
        },
        'p': {
            'name': 'period',
            'unit': datetime.timedelta(hours=12),
            'formatter': lambda time: time.strftime('%p')
        },
        'confirm': {
            'name': 'confirm',
            'unit': None,
            'formatter': lambda _: "Confirm"
        },
        'no_date': {
            'name': 'no_date',
            'unit': None,
            'formatter': lambda _: "No Date"
        },
    }

    def __init__(self, height, width, title):
        super().__init__(height, width, title, [])
        super().set_align(Popup.ALIGN_CENTER)

        self.time = datetime.datetime.now()
        self.quickpicks = None
        self.optional = False
        self.include_date = True
        self.custom_time_format = None

        self.__init_fields()
        self.__init_input_str()

        curses.curs_set(0)

    def set_quickpicks(self, quickpicks):
        self.quickpicks = sorted(quickpicks)

    def set_time(self, time):
        # Some methods expect the time to be a datetime.datetime
        if isinstance(time, datetime.time):
            time = datetime.datetime.combine(datetime.datetime.today(), time)
        self.time = time

    def set_optional(self, optional):
        self.optional = optional
        self.__init_fields()

    def set_include_date(self, include_date):
        self.include_date = include_date
        self.__init_fields()

    def set_time_format(self, time_format):
        """Provide a time format string to use
        If provided (and not None), this will override include_date"""
        self.custom_time_format = time_format
        self.__init_fields()

    def __resolve_date(self, date, year, month, day) -> datetime.datetime:
        """Find the closest valid date to an invalid date"""

        # Handle leap year
        if month == 2 and day > 28 and not calendar.isleap(year):
            day = 28

        # Handle out-of-range days in a month month:
        if month in {2, 4, 6, 9, 11} and day == 31:
            day = 30

        if month == 2 and day > 28:
            day = 28

        return date.replace(year, month, day)

    def __replace_date(self,
                       date: datetime.date,
                       year=None,
                       month=None,
                       day=None) -> datetime.datetime:
        """A wrapper around datetime.datetime.replace that checks for out-of range dates
        like a Feb 29 on a non-leap year"""

        if not year:
            year = date.year
        if not month:
            month = date.month
        if not day:
            day = date.day

        try:
            date = date.replace(year, month, day)
        except ValueError:
            date = self.__resolve_date(date, year, month, day)

        return date

    def __init_fields(self):
        time_format = self.custom_time_format
        if not time_format:
            time_format = (f"{'%b %d, %Y at ' if self.include_date else ''}"
                           f"%I:%M:%S%p")

        self.fields = []
        self.field_index = 0

        format_pieces = [[]]

        prev_c = None
        for c in time_format:
            if prev_c == '%':
                if c in DatetimeSpinner.__FIELDS:
                    if not format_pieces[-1]:
                        format_pieces[-1] = len(self.fields)
                    else:
                        format_pieces.append(len(self.fields))
                    format_pieces.append([])
                    field = DatetimeSpinner.__FIELDS[c]
                    self.fields.append(field)
                else:
                    format_pieces[-1].append(c)
            elif c != '%':
                format_pieces[-1].append(c)
            prev_c = c
        if not format_pieces[-1]:
            del format_pieces[-1]

        self.format_pieces = [
            piece if isinstance(piece, int) else ''.join(piece)
            for piece in format_pieces
        ]

        self.format_pieces += [" | ", len(self.fields)]
        self.fields.append(DatetimeSpinner.__FIELDS['confirm'])

        # If the date is optional (show 'No Date')
        if self.optional:
            self.format_pieces += [" | ", len(self.fields)]
            self.fields.append(DatetimeSpinner.__FIELDS['no_date'])

    def __init_input_str(self):
        self.input_str = ""
        self.input_str_last_field_index = None
        self._reset_month_str_position()

    # TODO (maybe): turn piece into a class with __str__ method
    def __str_from_format_piece(self, piece):
        if isinstance(piece, int):
            return self.fields[piece]['formatter'](self.time)
        else:
            return piece

    def __get_date_str(self):
        before_selected = []
        selected = None
        after_selected = []

        add_to = before_selected

        for format_piece in self.format_pieces:
            disp_str = self.__str_from_format_piece(format_piece)
            if (isinstance(format_piece, int)
                    and format_piece == self.field_index):
                selected = DisplayStr(f"[s:{disp_str}]")
                add_to = after_selected
            else:
                add_to.append(disp_str)

        return ''.join(before_selected) + selected + ''.join(after_selected)

    def draw(self):
        date_str = self.__get_date_str()
        self.message = [date_str]
        super().draw_text()
        self.window.noutrefresh()

    def is_confirmed(self) -> str:
        return self.fields[self.field_index]["name"] in {"confirm", "no_date"}

    def get_time(self):
        if self.fields[self.field_index]["name"] == "no_date":
            return DatetimeSpinner.NO_DATE
        return self.time if self.include_date else self.time.time()

    def next_field(self):
        self.field_index = (self.field_index + 1) % len(self.fields)

    def previous_field(self):
        self.field_index = (self.field_index - 1) % len(self.fields)

    def first_field(self):
        self.field_index = 0

    def last_field(self):
        self.field_index = len(self.fields) - 1

    def increment_field(self):
        field = self.fields[self.field_index]
        if field["name"] == "minute" and self.quickpicks:
            self._increment_quickpick()
        else:
            self._increment_field()

    def decrement_field(self):
        field = self.fields[self.field_index]
        if field["name"] == "minute" and self.quickpicks:
            self._decrement_quickpick()
        else:
            self._decrement_field()

    def alt_increment_field(self):
        self._increment_field()

    def alt_decrement_field(self):
        self._decrement_field()

    def _increment_field(self):
        field = self.fields[self.field_index]
        if field["unit"]:
            self.time = self.time + field["unit"]
        else:
            if field["name"] == "month":
                # month is in 1..12, this incs 12->1
                new_month = (self.time.month % 12) + 1
                self.time = self.__replace_date(self.time, month=new_month)
            elif field["name"] == "year":
                new_year = min(max(self.time.year + 1, datetime.MINYEAR),
                               datetime.MAXYEAR)
                self.time = self.__replace_date(self.time, year=new_year)

    def _decrement_field(self):
        field = self.fields[self.field_index]
        if field["unit"]:
            self.time = self.time - field["unit"]
        else:
            if field["name"] == "month":
                new_month = self.time.month - 1
                if new_month == 0:
                    new_month = 12
                self.time = self.__replace_date(self.time, month=new_month)
            elif field["name"] == "year":
                new_year = min(max(self.time.year - 1, datetime.MINYEAR),
                               datetime.MAXYEAR)
                self.time = self.__replace_date(self.time, year=new_year)

    def _increment_quickpick(self):
        new_minute, new_second = self.quickpicks[0]
        for minute, second in self.quickpicks:
            if minute > self.time.minute:
                new_minute, new_second = minute, second
                break

        self.time = self.time.replace(minute=new_minute, second=new_second)

    def _decrement_quickpick(self):
        new_minute, new_second = self.quickpicks[-1]
        for minute, second in self.quickpicks[::-1]:
            if minute < self.time.minute:
                new_minute, new_second = minute, second
                break

        self.time = self.time.replace(minute=new_minute, second=new_second)

    def addchar(self, c):
        if self.input_str_last_field_index != self.field_index:
            self.input_str = ""
        self.input_str_last_field_index = self.field_index

        if c.isdigit():
            self.input_str += c

            if self._set_field_numerically():
                self.input_str = ""
                self.next_field()
        else:
            if self.fields[self.field_index]["name"] == "month":
                if self._set_month_from_chars(c):
                    self._reset_month_str_position()
                    self.next_field()
            if self.fields[self.field_index]["name"] == "period":
                c = c.lower()
                if c in "ap":
                    current_period = self.time.strftime("%p")[0].lower()
                    delta = datetime.timedelta()
                    if c == "p" and current_period == "a":
                        delta = datetime.timedelta(hours=12)
                    elif c == "a" and current_period == "p":
                        delta = datetime.timedelta(hours=-12)
                    self.time = self.time + delta
                    self.next_field()

    def _set_field_numerically(self):
        """Attempts to set the current field to
        the current input_str interpreted as a number
        Returns true if the input_str completely fills the current field"""
        try:
            new_val = int(self.input_str)
            field_name = self.fields[self.field_index]["name"]
            str_len = len(self.input_str)

            if field_name == "month":
                self.time = self.__replace_date(self.time, month=new_val)
                # 1 could be Jan or Oct-Dec,
                # but other single digits are complete
                return new_val > 1 or str_len >= 2
            elif field_name == "day":
                self.time = self.__replace_date(self.time, day=new_val)
                # 1-3 could have a second digit,
                # but other single digits are complete
                return new_val > 3 or str_len >= 2
            elif field_name == "year":
                self.time = self.__replace_date(self.time, year=new_val)
                # user only enters 4-digit years
                return len(self.input_str) >= 4
            elif field_name in {"hour-12", "hour-24"}:
                self.time = self.time.replace(hour=new_val)
                # 1 (or 2 for 24-hour) could have a second digit,
                # but other single digits are complete
                single_digit_cap = 1 if field_name == "hour-12" else 2
                return new_val > single_digit_cap or str_len >= 2
            elif field_name == "minute":
                self.time = self.time.replace(minute=new_val)
                # 1-5 could have a second digit,
                # but other single digits are complete
                return new_val > 5 or str_len >= 2
            elif field_name == "second":
                self.time = self.time.replace(second=new_val)
                # 1-5 could have a second digit,
                # but other single digits are complete
                return new_val > 5 or str_len >= 2

        except ValueError:
            return False

    MONTH_STR_PATH = {
        "j": (
            1,
            False,
            {
                "a": (1, True, {
                    "n": (1, True, "uary")
                }),
                "u": (6, False, {
                    "n": (6, True, "e"),
                    "l": (7, True, "y")
                }),
            },
        ),
        "f": (2, True, {
            "e": (2, True, {
                "b": (2, True, "ruary")
            })
        }),
        "m": (3, False, {
            "a": (3, False, {
                "r": (3, True, "ch"),
                "y": (5, True, "")
            })
        }),
        "a": (
            4,
            False,
            {
                "p": (4, True, {
                    "r": (4, True, "il")
                }),
                "u": (8, True, {
                    "g": (8, True, "ust")
                })
            },
        ),
        "s": (9, True, {
            "e": (9, True, {
                "p": (9, True, "tember")
            })
        }),
        "o": (10, True, {
            "c": (10, True, {
                "t": (10, True, "ober")
            })
        }),
        "n": (11, True, {
            "o": (11, True, {
                "v": (11, True, "ember")
            })
        }),
        "d": (12, True, {
            "e": (12, True, {
                "c": (12, True, "ember")
            })
        }),
    }

    def _reset_month_str_position(self):
        self.month_str_position = DatetimeSpinner.MONTH_STR_PATH
        self.month_str_len = 0

    def _set_month_from_chars(self, newchar, recursed=False):
        """Attempts to set the month based on inputted chars
        Returns true once the input chars completely fill the month field"""
        newchar = newchar.lower()
        if newchar in self.month_str_position:
            guess, _, position = self.month_str_position[newchar]
            self.month_str_len += 1
            self.month_str_position = position

            self.time = self.time.replace(month=guess)

            return self.month_str_len >= 3
        elif not recursed:
            self._reset_month_str_position()
            return self._set_month_from_chars(newchar, recursed=True)


class ScrollableList(Component):
    """Base class for scrollable, sortable, searchable lists."""

    SELECTED_PREFIX = "| "
    UNSELECTED_PREFIX = " " * len(SELECTED_PREFIX)

    class Line:
        def __init__(self, index, text, color=0, sort_index=0, attrs=0):
            self.index = index
            self.text = text
            self.color = color
            self.sort_index = sort_index
            self.attrs = attrs

    def __init__(self):
        self._rows = 0

        self._lines: List[ScrollableList.Line] = []
        self._display_lines: List[ScrollableList.Line] = []

        self._searchable = False
        self._search_fn = None
        self._search_prompt = ""
        self._search_text = ""

        self._sortable = False

        self._scroll = 0
        self._selected_index = 1

        self._paged = False

        self._exit_line = ScrollableList.Line(0, "Back")

    def set_lines(self, lines):
        self._lines = [
            ScrollableList.Line(i, line.text, line.color, line.sort_index,
                                line.attrs) for i, line in enumerate(lines, 1)
        ]
        self.__create_display_lines()

        # If all content is filtered then select the exit row
        if len(self._display_lines) == 1:
            self._selected_index = 0

    def set_searchable(self, prompt: str, search_fn: Callable):
        self._searchable = True
        self._search_prompt = prompt
        self._search_fn = search_fn

    def set_sortable(self):
        self._sortable = True

    def set_paged(self):
        self._paged = True

    def set_exit_text(self, text: str):
        self._exit_line = ScrollableList.Line(0, text)
        self.__create_display_lines()

    def __create_display_lines(self):
        """Filter then sort the input lines."""
        # The top line is never filtered or sorted
        self._display_lines = [self._exit_line]

        filtered = self._filter() if self._searchable else self._lines

        if self._sortable:
            self._display_lines.extend(self._sort(filtered))
        else:
            self._display_lines.extend(filtered)

    def _filter(self):
        filtered = []
        for line in self._lines:
            if self._search_fn(line.text, self._search_text):
                filtered.append(line)
        return filtered

    def _sort(self, lines):
        lines.sort(key=lambda line: line.sort_index)
        return lines

    def __should_show_selected(self, number):
        return number + self._scroll == self._selected_index and not self._paged

    def _draw_list_lines(self, window, lines, y_start, x_start):
        for line_number, line in enumerate(lines):
            prefix = ScrollableList.UNSELECTED_PREFIX
            attributes = line.attrs
            if self.__should_show_selected(line_number):
                prefix = ScrollableList.SELECTED_PREFIX

                # Don't make the line bold if it is dim (diabled)
                if not (attributes & curses.A_DIM):
                    attributes = curses.A_BOLD

            add_str(window, y_start + line_number, x_start,
                    f"{prefix}{line.text}", attributes | line.color)
        window.noutrefresh()

    def __scroll_to_top(self):
        self._selected_index = 0
        self.set_scroll()
        self._selected_index = 1

    def set_scroll(self):
        # Cursor set below view
        if (self._selected_index + 1) > self._scroll + self._rows - 1:
            self._scroll = self._selected_index + 2 - self._rows

        # Cursor set above view
        elif self._selected_index < self._scroll:
            self._scroll = self._selected_index

    def down(self):
        if self._paged:
            self._scroll = min(self._scroll + 1,
                               len(self._display_lines) - self._rows + 1)
        else:
            self._selected_index = (self._selected_index + 1) % len(
                self._display_lines)
            self.set_scroll()

    def up(self):
        if self._paged:
            self._scroll = max(0, self._scroll - 1)
        else:
            self._selected_index = (self._selected_index - 1) % len(
                self._display_lines)
            self.set_scroll()

    def to_top(self):
        self._selected_index = 0
        self.set_scroll()

    def to_bottom(self):
        self._selected_index = len(self._display_lines) - 1
        self.set_scroll()

    def delchar(self):
        self._search_text = self._search_text[:-1]
        self.__scroll_to_top()

    def addchar(self, c):
        self._search_text += c
        self.__scroll_to_top()

    def clear_search_text(self):
        self._search_text = ""
        self.__scroll_to_top()

    def is_close_selected(self):
        return self._selected_index == 0

    def get_selected_index(self):
        """Get the original index of the selected line."""
        return self._display_lines[self._selected_index].index - 1


class FilteredList(ScrollableList):
    def __init__(self, y, x, rows, cols):
        super().__init__()

        self.x = x
        self.y = y
        self._rows = rows
        self.cols = cols

        # List box
        self.window = curses.newwin(self._rows, self.cols, y, x)
        self.window.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))

        # Text input area
        self.text_input = curses.newwin(1, self.cols, self._rows, 0)
        self.text_input.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))

    def draw(self):
        self.window.erase()

        # Draw the list lines
        # TODO: Can we avoid slicing here?
        visible_lines = self._display_lines[self._scroll:self._scroll +
                                            self._rows - 1]
        self._draw_list_lines(self.window, visible_lines, 0, 0)

        # Draw the optional search field
        if self._searchable:
            self.text_input.erase()
            add_str(self.text_input, 0, 0,
                    f"{self._search_prompt}: {self._search_text}")
            self.text_input.noutrefresh()
            curses.curs_set(1)
        else:
            curses.curs_set(0)

    def resize(self, rows, cols):
        self._rows = rows - 1
        self.cols = cols

        try:
            self.window.mvwin(self.y, self.x)
            self.text_input.mvwin(self._rows, 0)
        except:
            pass

        resize_window(self.window, self._rows - 1, self.cols)
        resize_window(self.text_input, 1, self.cols)


class ListPopup(Popup, ScrollableList):
    V_PADDING = Popup.PADDING * 2

    def __init__(self, rows, cols, title):
        Popup.__init__(self, rows, cols, title, [])
        ScrollableList.__init__(self)

        self._rows = self.rows - ListPopup.V_PADDING + 1

        # Text input area
        self.text_input = curses.newwin(1, self.cols - Popup.PADDING * 2,
                                        self.y + self.rows - Popup.PADDING + 1,
                                        self.x + Popup.PADDING)
        self.text_input.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))

    def draw(self):
        self.window.erase()
        self.window.border()

        self.draw_title()

        visible_lines = self._display_lines[self._scroll:self._scroll +
                                            self.rows - ListPopup.V_PADDING]
        self._draw_list_lines(self.window, visible_lines, Popup.PADDING,
                              Popup.PADDING)

        if self._searchable:
            self.text_input.erase()
            add_str(self.text_input, 0, 0,
                    f"{self._search_prompt}: {self._search_text}")
            curses.curs_set(1)
            self.text_input.noutrefresh()
        else:
            curses.curs_set(0)

    def resize(self, rows, cols):
        Popup.resize(self, rows, cols)

        try:
            self.text_input.mvwin(self.y + self.rows - Popup.PADDING + 1,
                                  self.x + Popup.PADDING)
        except:
            pass

        resize_window(self.text_input, 1, self.cols - Popup.PADDING * 2)


class TextInput(Popup):
    TEXT_NORMAL = 0
    TEXT_MASKED = 1

    PADDING = 2
    # 1 Row for prompt, 4 for text
    TEXT_HEIGHT = 5

    def __init__(self, height, width, title, prompt, text, mask=TEXT_NORMAL):
        super().__init__(height, width, title, [prompt])

        self.prompt = prompt
        self.masked = mask is TextInput.TEXT_MASKED

        self.set_text(text)
        self.text_width = self.cols - (TextInput.PADDING * 2)

        # Set selection marks
        self.reset_marks()

        # Create a text input
        self.text_input = curses.newwin(
            TextInput.TEXT_HEIGHT,
            self.text_width,
            self.__text_win_start_y(),
            self.__text_win_start_x(),
        )
        self.text_input.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))
        curses.curs_set(1)

    def set_text(self, text: str):
        self.text = text
        self.cursor_index = len(text)

    def resize(self, rows, cols):
        super().resize(rows, cols)

        self.text_width = self.cols - (TextInput.PADDING * 2)

        try:
            self.text_input.mvwin(self.__text_win_start_y(),
                                  self.__text_win_start_x())
        except:
            pass
        resize_window(self.text_input, TextInput.TEXT_HEIGHT, self.text_width)

    def draw_text_chars(self, row, col, display_text):
        attrs = 0

        start_select = len(display_text)
        end_select = start_select
        if self.marks:
            start_select = min(self.marks)
            end_select = max(self.marks)

        index = 0
        for char in display_text:
            if index == start_select:
                attrs = curses.A_STANDOUT

            add_str(self.text_input, row, col, char, attrs)
            col += 1
            if col >= self.text_width:
                col = 0
                row += 1

            if index == end_select:
                attrs = 0
            index += 1

    def draw(self):
        super().draw_text()
        self.text_input.erase()

        curses.curs_set(0 if self.marks else 1)

        # Draw input prompt
        add_str(self.text_input, 0, 0, f"Input:")

        # Draw text and wrap on end of line
        if self.masked:
            display_text = "*" * len(self.text)
        else:
            display_text = self.text
        self.draw_text_chars(1, 0, display_text)

        # Set cursor index
        cursor_x = self.cursor_index % self.text_width
        cursor_y = (self.cursor_index // self.text_width) + 1
        self.text_input.move(cursor_y, cursor_x)

        self.window.noutrefresh()
        self.text_input.noutrefresh()

    def addchar(self, c):
        before_index = self.cursor_index
        after_index = self.cursor_index

        # If text selected, use marks
        if self.marks:
            before_index = min(self.marks)
            after_index = max(self.marks) + 1
            self.reset_marks()

        # Insert character at cursor location and set cursor one past insert
        self.text = self.text[:before_index] + c + self.text[after_index:]
        self.cursor_index = before_index
        self.right()

    def delselection(self):
        left = self.text[:min(self.marks)]
        right = self.text[max(self.marks) + 1:]
        self.text = left + right
        self.cursor_index = min(self.marks)
        self.reset_marks()

    def delchar(self):
        if self.marks:
            self.delselection()
            return

        if self.cursor_index == 0:
            return

        # Remove character at cursor location
        self.text = (self.text[:self.cursor_index - 1] +
                     self.text[self.cursor_index:])
        self.left()

    def delcharforward(self):
        if self.marks:
            self.delselection()
            return

        if self.cursor_index == len(self.text):
            return

        # Remove character just forward of cursor location
        self.text = (self.text[:self.cursor_index] +
                     self.text[self.cursor_index + 1:])

    def _cursor_mover(move_func):
        """Wrap a cursor-moving function without moving marks"""
        def wrapped(self, shift_pressed=False):
            if shift_pressed:
                if not self.marks:
                    self.marks = [self.cursor_index] * 2
                move_func(self)
                self.marks[1] = self.cursor_index
            else:
                move_func(self)
                self.reset_marks()

        return wrapped

    @_cursor_mover
    def right(self):
        self.cursor_index = min(len(self.text), self.cursor_index + 1)

    @_cursor_mover
    def left(self):
        self.cursor_index = max(0, self.cursor_index - 1)

    @_cursor_mover
    def up(self):
        self.cursor_index = max(0, self.cursor_index - self.text_width)

    @_cursor_mover
    def down(self):
        self.cursor_index = min(len(self.text),
                                self.cursor_index + self.text_width)

    @_cursor_mover
    def cursor_to_beginning(self):
        self.cursor_index = 0

    @_cursor_mover
    def cursor_to_end(self):
        self.cursor_index = len(self.text)

    def reset_marks(self):
        self.marks = []

    def __text_win_start_y(self):
        return self.y + self.rows - TextInput.TEXT_HEIGHT - 1

    def __text_win_start_x(self):
        return self.x + TextInput.PADDING


class Logger(Component):
    PADDING = 2

    def __init__(self, height, width, y, x):
        self.height = height
        self.width = width

        self.window = curses.newwin(height, width, y, x)
        self.window.bkgd(" ", curses.color_pair(colors.COLOR_PAIR_DEFAULT))
        curses.curs_set(0)

        # Maintain a log (list) of data to display
        self.__log = []

    def resize(self, rows, cols):
        self.height = rows
        self.width = cols

        resize_window(self.window, self.height, self.width)

    def draw(self):
        self.window.erase()

        # Draw the last n elements of the log, with n being the available height
        # minus PADDING to give a border on the top and bottom

        NUM_LINES = self.height - Logger.PADDING

        liney = Logger.PADDING // 2
        for line in self.__log[-NUM_LINES:]:
            add_str(self.window, liney, 0, line)
            liney += 1

        self.window.noutrefresh()

    def log(self, entry):
        self.__log.append(entry)

        self.draw()

    def append(self, entry):
        self.__log[-1] += entry
        self.draw()
