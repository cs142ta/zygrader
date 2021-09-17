"""Email: Manage locking of student emails from zygrader to prevent double-answering."""

import curses
from zygrader.config.shared import SharedData

from zygrader import data, grader, ui, utils
from zygrader.ui import colors


def view_email_submissions(student: data.Student):
    """View submissions from the locked student"""
    grader.grade(use_locks=False, student=student)


def show_currently_locked_popup(window, student):
    netid = data.lock.get_locked_netid(student)

    # Locked by a different user
    if netid != utils.get_username():
        name = data.netid_to_name(netid)
        msg = [f"{name} is replying to {student.first_name}'s email"]
        popup = ui.layers.Popup("Student Locked", msg)
        window.run_layer(popup)
        return False
    # Locked by current user
    return True


def lock_student_callback(student: data.Student):
    window = ui.get_window()

    if data.lock.is_locked(student) and not show_currently_locked_popup(
            window, student):
        return

    netid = utils.get_username()
    recently_locked, ts, netid = data.lock.was_recently_locked(
        student, None, netid, range=SharedData.RECENT_LOCK_EMAILS)

    if recently_locked:
        name = data.netid_to_name(netid)
        msg = [
            f"This email may have been replied to already by {name} at {ts}.",
            "Please check to make sure no one has yet replied.",
            "(Or the student has sent a new email within the last 10 minutes making this a false alarm)",
        ]
        popup = ui.layers.OptionsPopup("Recently Emailed", msg)
        popup.add_option("Proceed to Lock")
        window.run_layer(popup)
        if popup.get_selected() == "Close":
            return

    # Just like in grader.py, there is a small chance that two TAs are
    # looking at the "recently locked" popup, and we need to check here
    # in case one has locked the email while the other was still in the
    # popup.
    if data.lock.is_locked(student) and not show_currently_locked_popup(
            window, student):
        return

    try:
        data.lock.lock(student)
        msg = [f"You have locked {student.full_name} for emailing."]
        popup = ui.layers.OptionsPopup("Student Locked", msg)
        popup.add_option("View Submitted Code",
                         lambda: view_email_submissions(student))
        popup.add_option("Prep Lab Calc", utils.prep_lab_score_calc)
        window.run_layer(popup)
    finally:
        data.lock.unlock(student)


def watch_students(student_list, students):
    """Register paths when the filtered list is created"""
    paths = [data.SharedData.get_locks_directory()]
    data.fs_watch.fs_watch_register(paths, "student_email_list_watch",
                                    fill_student_list, student_list, students)


def get_student_row_color_sort_index(student):
    if data.lock.is_locked(student):
        return curses.color_pair(colors.COLOR_PAIR_LOCKED), 0
    return curses.color_pair(colors.COLOR_PAIR_DEFAULT), 1


def fill_student_list(student_list: ui.layers.ListLayer, students):
    student_list.clear_rows()
    for student in students:
        row = student_list.add_row_text(str(student), lock_student_callback,
                                        student)
        color, sort_index = get_student_row_color_sort_index(student)
        row.set_row_color(color)
        row.set_row_sort_index(sort_index)
    student_list.rebuild = True


def email_menu():
    """Show the list of students with auto-update and locking."""
    window = ui.get_window()
    students = data.get_students()

    student_list = ui.layers.ListLayer()
    student_list.set_searchable("Student")
    student_list.set_sortable()
    fill_student_list(student_list, students)
    watch_students(student_list, students)
    student_list.set_destroy_fn(
        lambda: data.fs_watch.fs_watch_unregister("student_email_list_watch"))
    window.register_layer(student_list, "Email Manager")
