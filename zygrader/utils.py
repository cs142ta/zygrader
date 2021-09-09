"""
utils.py

General algorithms/utilities to be shared between modules
"""

import curses
import difflib
import getpass
import os
import subprocess
import tempfile
from subprocess import DEVNULL, PIPE

from zygrader import data, ui
from zygrader.zybooks import Zybooks

OPENED_DIRECTORES = []


def get_username() -> str:
    """
    Get the username of a TA (env $USER)
    Any . characters are removed because . is used as a separator for lock filenames
    """
    return getpass.getuser().replace(".", "")


def create_tempdir(prefix="zy") -> str:
    """Create and return a temporary directory with an optional prefix

    We use this wrapper over tempfile.TemporaryDirectory() to avoid cluttering
    the /tmp directory. Although this path is automatically cleared by the OS
    regularly, we can easily clear these files on our own.

    The files returned by TemporaryDirectory are automatically deleted when
    the object is destroyed. So we keep a global list of all files and when
    zygrader is closed these files are also deleted.

    Because these directories are used in subprocesses we can't rely on the
    directories being used before the Python objects are destroyed, so the
    list prevents any issues.

    See #94 for more information.
    """

    _file = tempfile.TemporaryDirectory(prefix=prefix)
    OPENED_DIRECTORES.append(_file)
    return _file.name


def suspend_curses(callback_fn):
    """A decorator for any subprocess that must suspend access to curses (zygrader)"""
    def wrapper(*args, **kwargs):
        events = ui.get_events()
        # Clear remaining events in event queue
        events.clear_event_queue()
        curses.endwin()

        callback_fn(*args, **kwargs)

        curses.flushinp()
        curses.initscr()
        events.clear_event_queue()
        curses.doupdate()

    return wrapper


def get_diff_name(path, title_a, title_b) -> str:
    # The names can be the same between parts (main.cpp) so we should
    # Also include the part's subfolder in the name
    path, name = os.path.split(path)
    path, folder_name = os.path.split(path)
    file_name = os.path.join(folder_name, name)
    return f"{file_name} - {title_a} against {title_b}"


def diff_files(first, second, title_a, title_b, use_html):
    """Given two lists of equal length containing file paths, return a diff of each pair of files"""
    diffs = {}

    num_files = len(first)

    for index in range(num_files):
        path_a = first[index]
        path_b = second[index]

        diff_name = get_diff_name(path_a, title_a, title_b)

        diff = ""
        if use_html:
            with open(path_a, "r") as file_a:
                with open(path_b, "r") as file_b:
                    html = difflib.HtmlDiff(4, 80)
                    diff = html.make_file(file_a.readlines(),
                                          file_b.readlines(),
                                          title_a,
                                          title_b,
                                          context=True)
        else:
            diff_process = subprocess.Popen(
                ["diff", "-w", "-u", "--color=always", path_a, path_b],
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                universal_newlines=True,
            )
            diff = str(diff_process.communicate()[0])

        diffs[diff_name] = diff

    return diffs


def make_diff_string(first, second, title_a, title_b, use_html=False):
    """Given to lists of equal length containing file paths, return a string containing the diffs"""
    diffs = diff_files(first, second, title_a, title_b, use_html)

    diff_str = ""

    for diff in diffs:
        if use_html:
            diff_str += f"<h1>{diff}</h1>\n"
        else:
            diff_str += f"\n\nFILE: {diff}\n"
        diff_str += diffs[diff]

    return diff_str


@suspend_curses
def view_string(string, file_name, use_html=False):
    """Given a string, open in `less` or the grader's default browser"""

    tmp_dir = create_tempdir()
    file_path = f"{os.path.join(tmp_dir, file_name)}"

    with open(file_path, "w") as _file:
        _file.write(string)

    if use_html:
        subprocess.Popen(f"xdg-open {file_path}",
                         shell=True,
                         stdout=DEVNULL,
                         stderr=DEVNULL)
    else:
        subprocess.run(["less", "-r", f"{file_path}"], stderr=DEVNULL)


def __format_file(_file) -> str:
    decoded = ""
    try:
        decoded = _file.decode("UTF-8")
    except UnicodeDecodeError:
        # Rarely a file may have some strange characters encoded in a Windows-
        # specific format. In that case, try decoding this way.
        decoded = _file.decode("windows-1252")

    return decoded.replace("\r\n", "\n").replace("\r", "\n")


def extract_zip(input_zip, file_prefix=None):
    """Given a ZipFile object, return a dictionary of the files of the form
    {"filename": "contents...", ...}
    """
    if file_prefix:
        return {
            f"{file_prefix}_{name}": __format_file(input_zip.read(name))
            for name in input_zip.namelist()
        }
    else:
        return {
            f"{name}": __format_file(input_zip.read(name))
            for name in input_zip.namelist()
        }


def get_source_file_paths(directory):
    """Get the file path for each source file

    Each file is in a subfolder so os.walk is needed to get the full path
    """
    paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            paths.append(os.path.join(root, file))
    return paths


def prep_lab_score_calc():
    """A simple calculator for determining the score for a late prep lab"""
    window = ui.get_window()

    try:
        text_input = ui.layers.TextInputLayer("Original Score")
        text_input.set_prompt(["What was the student's original score?"])
        window.run_layer(text_input, "Prep Lab Calculator")
        if text_input.canceled:
            return

        old_score = float(text_input.get_text())

        text_input = ui.layers.TextInputLayer("zyBooks Completion")
        text_input.set_prompt(
            ["What is the student's current completion % in zyBooks"])
        text_input.set_text("100")
        window.run_layer(text_input, "Prep Lab Calculator")
        if text_input.canceled:
            return

        # Calculate the new score
        current_completion = float(text_input.get_text())
        new_score = old_score + ((current_completion - old_score) * 0.6)

        popup = ui.layers.Popup("New Score")
        popup.set_message([f"The student's new score is: {new_score}"])
        window.run_layer(popup, "Prep Lab Calculator")
    except ValueError:
        popup = ui.layers.Popup("Error")
        popup.set_message(["Invalid input"])
        window.run_layer(popup, "Prep Lab Calculator")


def view_students_fn(student):
    """Create a popup to show info for the selected student"""
    window = ui.get_window()

    msg = [
        f"Name: {student.full_name}",
        f"Email: {student.email}",
        f"Section: {student.section}",
        f"ID: {student.id}",
    ]

    popup = ui.layers.Popup("Student Info")
    popup.set_message(msg)
    window.run_layer(popup)


def view_students():
    """Create the view students filtered list"""
    window = ui.get_window()
    students = data.get_students()

    if not students:
        popup = ui.layers.Popup("No Students")
        popup.set_message(["There are no students in the class to show."])
        window.run_layer(popup)
        return

    popup = ui.layers.ListLayer("Students", popup=True)
    popup.set_exit_text("Close")
    popup.set_searchable("Student Name")
    for student in students:
        popup.add_row_text(str(student), view_students_fn, student)
    window.register_layer(popup, "View Students")


def fetch_zybooks_toc():
    window = ui.get_window()
    zy_api = Zybooks()

    popup = ui.layers.WaitPopup("Table of Contents",
                                ["Fetching TOC from zyBooks"])
    popup.set_wait_fn(zy_api.get_table_of_contents)
    window.run_layer(popup)

    return popup.get_result()
