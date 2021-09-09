"""Grader: Menus and popups for grading and pair programming"""
import curses

from zygrader import data, ui, utils
from zygrader.config import preferences
from zygrader.config.shared import SharedData
from zygrader.data import model
from zygrader.zybooks import Zybooks
from zygrader.ui import colors


def get_student_row_color_sort_index(lab, student):
    """Color the student names in the grader based on locked, flagged, or normal status"""
    if data.lock.is_locked(student, lab) and not isinstance(student, str):
        return curses.color_pair(colors.COLOR_PAIR_LOCKED), 0
    if data.flags.is_submission_flagged(student,
                                        lab) and not isinstance(student, str):
        return curses.color_pair(colors.COLOR_PAIR_FLAGGED), 1
    return curses.color_pair(colors.COLOR_PAIR_DEFAULT), 2


def fill_student_list(student_list: ui.layers.ListLayer,
                      students,
                      lab,
                      use_locks,
                      callback_fn=None):
    student_list.clear_rows()

    for student in students:
        row = student_list.add_row_text(str(student), callback_fn, student, lab,
                                        use_locks)
        color, sort_index = get_student_row_color_sort_index(lab, student)
        row.set_row_color(color)
        row.set_row_sort_index(sort_index)
    student_list.rebuild = True


def set_submission_message(popup: ui.layers.OptionsPopup,
                           submission: data.model.Submission):
    popup.set_message(list(submission))


def get_submission(lab, student, use_locks=True):
    """Get a submission from zyBooks given the lab and student"""
    window = ui.get_window()
    zy_api = Zybooks()

    # Lock student
    if use_locks:
        data.lock.lock(student, lab)

    submission_response = zy_api.download_assignment(student, lab)
    submission = data.model.Submission(student, lab, submission_response)

    # Report missing files
    if submission.flag & data.model.SubmissionFlag.BAD_ZIP_URL:
        msg = [
            f"One or more URLs for {student.full_name}'s code submission are bad.",
            "Some files could not be downloaded. Please",
            "View the most recent submission on zyBooks.",
        ]
        popup = ui.layers("Warning", msg)
        window.run_layer(popup)

    # A student may have submissions beyond the due date, and an exception
    # In case that happens, always allow a normal grade, but show a message
    if submission.flag == data.model.SubmissionFlag.NO_SUBMISSION:
        pass

    return submission


def pick_submission(submission_popup: ui.layers.OptionsPopup,
                    lab: data.model.Lab, student: data.model.Student,
                    submission: data.model.Submission):
    """Allow the user to pick a submission to view"""
    window = ui.get_window()
    zy_api = Zybooks()

    # If the lab has multiple parts, prompt to pick a part
    part_index = 0
    if len(lab.parts) > 1:
        part_index = submission.pick_part(pick_all=True)
        if part_index is None:
            return
        if part_index == -1:

            def wait_fn():
                for i, part in enumerate(lab.parts):
                    part_submissions = zy_api.get_submissions_list(
                        part["id"], student.id)
                    if len(part_submissions) > 0:
                        part_response = zy_api.download_assignment_part(
                            lab, student.id, part,
                            len(part_submissions) - 1)
                        submission.update_part(part_response,
                                               lab.parts.index(part))
                set_submission_message(submission_popup, submission)

            popup = ui.layers.WaitPopup("Downloading")
            popup.set_message([f"Downloading latest submissions..."])
            popup.set_wait_fn(wait_fn)
            window.run_layer(popup)
            return

    # Get list of all submissions for that part
    part = lab.parts[part_index]
    all_submissions = zy_api.get_submissions_list(part["id"], student.id)
    if not all_submissions:
        popup = ui.layers.Popup("No Submissions",
                                ["The student did not submit this part"])
        window.run_layer(popup)
        return

    # Reverse to display most recent submission first
    all_submissions.reverse()

    popup = ui.layers.ListLayer("Select Submission", popup=True)
    popup.set_exit_text("Cancel")
    for sub in all_submissions:
        popup.add_row_text(sub)
    window.run_layer(popup)
    if popup.canceled:
        return

    submission_index = popup.selected_index()

    # Modify submission index to un-reverse the index
    submission_index = abs(submission_index - (len(all_submissions) - 1))

    # Fetch that submission
    part_response = zy_api.download_assignment_part(lab, student.id, part,
                                                    submission_index)
    submission.update_part(part_response, lab.parts.index(part))
    set_submission_message(submission_popup, submission)


def view_test_io(test: dict):
    # create a tempfile name for this test case
    test_io_name = f"{test['label']}".replace(" ", "-").lower()

    # format the test case input and output into a nice string
    io = [
        f"{test['name']}\n",
        "Input:",
        f"{test['input']}\n",
        "Output:",
        f"{test['output']}\n",
        "Expected:",
        f"{test['expected']}",
    ]

    utils.view_string("\n".join(io), test_io_name)


def view_test_results(submission: model.Submission):
    """View the test results for all parts"""
    window = ui.get_window()

    # Ensure the student has submitted
    if submission.flag & model.SubmissionFlag.NO_SUBMISSION:
        popup = ui.layers.Popup("No Submission", [
            "Cannot vew test cases because the student did not submit",
        ])
        window.run_layer(popup)
        return

    popup = ui.layers.ListLayer("Test Results", popup=True)
    popup.set_exit_text("Close")

    for part in submission.test_results:
        row = popup.add_row_parent(part["name"])
        for test in part["tests"]:
            subrow = row.add_row_text(test["name"], view_test_io, test)
            if test["type"] == "unit_test":
                subrow.set_disabled()

    window.run_layer(popup)


def view_diff(first: model.Submission, second: model.Submission):
    """View a diff of the two submissions"""
    if (first.flag & model.SubmissionFlag.NO_SUBMISSION
            or second.flag & model.SubmissionFlag.NO_SUBMISSION):
        window = ui.get_window()
        popup = ui.layers.Popup("No Submissions", [
            "Cannot diff submissions because at least one student has not submitted."
        ])
        window.run_layer(popup)
        return

    use_browser = preferences.get("browser_diff")

    paths_a = utils.get_source_file_paths(first.files_directory)
    paths_b = utils.get_source_file_paths(second.files_directory)

    paths_a.sort()
    paths_b.sort()

    diff = utils.make_diff_string(paths_a, paths_b, first.student.full_name,
                                  second.student.full_name, use_browser)
    utils.view_string(diff, "submissions.diff", use_browser)


def run_code_fn(window, submission):
    """Callback to compile and run a submission's code"""
    use_gdb = False

    if not submission.compile_and_run_code(use_gdb):
        popup = ui.layers.OptionsPopup("Error", ["Could not compile code"])
        popup.add_option("View Log", submission.view_stderr)
        window.run_layer(popup)


def pair_programming_submission_callback(lab, submission):
    """Show both pair programming students for viewing a diff"""
    window = ui.get_window()

    popup = ui.layers.OptionsPopup("Pair Programming Submission")
    popup.set_message(submission)
    popup.add_option(
        "Pick Submission",
        lambda: pick_submission(popup, lab, submission.student, submission))
    popup.add_option("Run", lambda: run_code_fn(window, submission))
    popup.add_option("View", lambda: submission.show_files())
    window.run_layer(popup)

    SharedData.running_process = None


def flag_submission(lab, student, flag_text="", flagtag=""):
    """Flag a submission with a note"""
    window = ui.get_window()

    if not flagtag:
        flagtags = ["Needs Head TA", "Student Action Required", "Other"]
        tag_input = ui.layers.ListLayer("Flag Tag", popup=True)
        for tag in flagtags:
            tag_input.add_row_text(tag)
        window.run_layer(tag_input)
        if tag_input.canceled:
            return
        flagtag = flagtags[tag_input.selected_index()]

    text_input = ui.layers.TextInputLayer("Flag Note")
    text_input.set_prompt(["Enter a flag note"])
    text_input.set_text(flag_text)
    window.run_layer(text_input)
    if text_input.canceled:
        return
    flag_note = text_input.get_text()

    full_message = f"{flagtag}: {flag_note}"
    data.flags.flag_submission(student, lab, full_message)


def edit_flag(flag_string: str, student: model.Student, lab: model.Lab):
    """Edit the text in a flagged submission"""

    # The note might contain `:` characters, so we handle that case
    parts = flag_string.split(":")
    tag_type = parts[0].strip()
    tag_text = ":".join(parts[1:]).strip()

    flag_submission(lab, student, tag_text, tag_type)


def show_currently_grading_popup(window, student, lab):
    netid = data.lock.get_locked_netid(student, lab)

    # If being graded by the user who locked it, allow grading
    if netid != utils.get_username():
        name = data.netid_to_name(netid)
        msg = [f"This student is already being graded by {name}"]
        popup = ui.layers.Popup("Student Locked", msg)
        window.run_layer(popup)
        return False
    return True


def is_lab_available(use_locks, student, lab):
    """
    Check if the student's lab is available for grading
    * always available if locks are disabled
    * unavailable if a student's lab is currently locked or
      if it was locked within the last 10 minutes.
    """
    if not use_locks:
        return True

    window = ui.get_window()

    if data.flags.is_submission_flagged(student, lab):
        flag_message = data.flags.get_flag_message(student, lab)
        msg = [
            "This submission has been flagged",
            "",
            flag_message,
        ]
        popup = ui.layers.OptionsPopup("Submission Flagged", msg)
        popup.add_option("Edit")
        popup.add_option("Unflag")
        popup.add_option("View")
        window.run_layer(popup)

        choice = popup.get_selected()
        if choice == "Edit":
            edit_flag(flag_message, student, lab)
            return False
        elif choice == "Unflag":
            data.flags.unflag_submission(student, lab)
        elif choice == "View":
            # Make sure that "View" is an option, but still do the recent check locks
            pass
        else:
            return False

    # Check if this submission is currently graded by another TA
    if data.lock.is_locked(student, lab) and not show_currently_grading_popup(
            window, student, lab):
        return False

    # The submission was graded within the last 10 minutes, prompt
    # the TA to confirm that they haven't been graded already.
    current_netid = utils.get_username()
    recently_locked, ts, netid = data.lock.was_recently_locked(
        student, lab, current_netid)
    if recently_locked:
        name = data.netid_to_name(netid)
        msg = [
            f"This submission may have been recently graded by {name} at {ts}.",
            "Please check to make sure it hasn't already been graded"
        ]
        popup = ui.layers.OptionsPopup("Recently Graded", msg)
        popup.add_option("Proceed to Grade")
        window.run_layer(popup)
        if popup.get_selected() == "Close":
            return False

    # There is a very small chance that two TAs are looking through the previous
    # popups at the same time. If that is the case, we want to ensure the check
    # for locks occurs last, otherwise the small window of time when both are
    # looking at the popups gives a chance to bypass the locks.
    if data.lock.is_locked(student, lab):
        return show_currently_grading_popup(window, student, lab)

    return True


def pair_programming_message(first, second) -> list:
    """To support dynamic updates on the pair programming popup"""
    return [
        f"{first.student.full_name} {first.latest_submission}",
        f"{second.student.full_name} {second.latest_submission}",
        "",
        "Pick a student's submission to view or view the diff",
    ]


def grade_pair_programming(first_submission, use_locks):
    """Pick a second student to grade pair programming with"""
    # Get second student
    window = ui.get_window()
    students = data.get_students()

    lab = first_submission.lab

    student_list = ui.layers.ListLayer()
    student_list.set_searchable("Student")
    student_list.set_sortable()
    fill_student_list(student_list, students, lab, use_locks)
    window.run_layer(student_list)

    if student_list.canceled:
        return

    # Get student
    student_index = student_list.selected_index()
    student = students[student_index]

    if not is_lab_available(use_locks, student, lab):
        return

    try:
        second_submission = get_submission(lab, student, use_locks)

        if second_submission is None:
            return

        if second_submission == first_submission:
            popup = ui.layers.Popup(
                "Invalid Student",
                ["The first and second students are the same"])
            window.run_layer(popup)
            return

        first_submission_fn = lambda: pair_programming_submission_callback(
            lab, first_submission)
        second_submission_fn = lambda: pair_programming_submission_callback(
            lab, second_submission)

        msg = lambda: pair_programming_message(first_submission,
                                               second_submission)
        popup = ui.layers.OptionsPopup("Pair Programming")
        popup.set_message(msg)
        popup.add_option(first_submission.student.full_name,
                         first_submission_fn)
        popup.add_option(second_submission.student.full_name,
                         second_submission_fn)
        popup.add_option("View Diff",
                         lambda: view_diff(first_submission, second_submission))
        window.run_layer(popup)

    finally:
        if use_locks:
            data.lock.unlock(student, lab)


def diff_parts_fn(window, submission):
    """Callback for text diffing parts of a submission"""
    error = submission.diff_parts()
    if error:
        popup = ui.layer.Popup("Error", [error])
        window.run_layer(popup)


def student_select_fn(student, lab, use_locks):
    """Show the submission for the selected lab and student"""
    window = ui.get_window()

    # Wait for student's assignment to be available
    if not is_lab_available(use_locks, student, lab):
        return

    try:
        # Get the student's submission
        submission = get_submission(lab, student, use_locks)

        # Exit if student has not submitted
        if submission is None:
            return

        def flag_submission_fn():
            flag_submission(lab, student)
            # Return to the list of students
            events = ui.get_events()
            events.push_layer_close_event()

        popup = ui.layers.OptionsPopup("Submission")
        set_submission_message(popup, submission)
        popup.add_option("Flag", flag_submission_fn)
        popup.add_option(
            "Pick Submission",
            lambda: pick_submission(popup, lab, student, submission))
        popup.add_option("Test Results", lambda: view_test_results(submission))
        popup.add_option("Pair Programming",
                         lambda: grade_pair_programming(submission, use_locks))
        if submission.flag & data.model.SubmissionFlag.DIFF_PARTS:
            popup.add_option("Diff Parts",
                             lambda: diff_parts_fn(window, submission))
        popup.add_option("Run", lambda: run_code_fn(window, submission))
        popup.add_option("View", lambda: submission.show_files())
        window.run_layer(popup)

        SharedData.running_process = None

    finally:
        # Always unlock the lab when no longer grading
        if use_locks:
            data.lock.unlock(student, lab)


def watch_students(student_list, students, lab, use_locks):
    """Register paths when the filtered list is created"""
    paths = [SharedData.get_locks_directory(), SharedData.get_flags_directory()]
    data.fs_watch.fs_watch_register(paths, "student_list_watch",
                                    fill_student_list, student_list, students,
                                    lab, use_locks, student_select_fn)


def lab_select_fn(selected_index, use_locks, student: model.Student = None):
    """Callback function that executes after selecting a lab"""
    lab = data.get_labs()[selected_index]

    # Skip selecting a student and go immediately to the grader
    if student:
        student_select_fn(student, lab, use_locks)
        return

    window = ui.get_window()
    students = data.get_students()

    student_list = ui.layers.ListLayer()
    student_list.set_searchable("Student")
    student_list.set_sortable()
    fill_student_list(student_list, students, lab, use_locks, student_select_fn)

    # Register a watch function to watch the students
    watch_students(student_list, students, lab, use_locks)

    # # Remove the file watch handler when done choosing students
    student_list.set_destroy_fn(
        lambda: data.fs_watch.fs_watch_unregister("student_list_watch"))
    window.register_layer(student_list, lab.name)


def grade(use_locks=True, student: model.Student = None):
    """Create the list of labs to pick one to grade"""
    window = ui.get_window()
    labs = data.get_labs()

    if not labs:
        popup = ui.layers.Popup("Error")
        popup.set_message(["No labs have been created yet"])
        window.run_layer(popup)
        return

    title = "Grader"
    if not use_locks:
        title = "Run for Fun"

    lab_list = ui.layers.ListLayer()
    lab_list.set_searchable("Lab")
    for index, lab in enumerate(labs):
        lab_list.add_row_text(str(lab), lab_select_fn, index, use_locks,
                              student)
    window.register_layer(lab_list, title)
