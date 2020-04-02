import curses
import difflib
import getpass
import io
import os
import subprocess
from subprocess import PIPE
import tempfile

from . import config
from . import data
from . import logger

from .ui import components, UI_GO_BACK
from .ui.window import Window
from .zybooks import Zybooks

def get_submission(lab, student, use_locks=True):
    window = Window.get_window()
    zy_api = Zybooks()

    # Lock student
    if use_locks:
        data.lock.lock_lab(student, lab)

    submission_response = zy_api.download_assignment(student, lab)
    submission = data.model.Submission(student, lab, submission_response)

    # Report missing files
    if submission.flag & data.model.SubmissionFlag.BAD_ZIP_URL:
        msg = [f"One or more URLs for {student.full_name}'s code submission are bad.",
               "Some files could not be downloaded. Please",
               "View the most recent submission on zyBooks."]
        window.create_popup("Warning", msg)

    return submission

def diff_submissions(first, second, use_html=False):
    """Generate an file of the two students submissions in HTML or text

    HTML is used for a side-by-side graphical presentation in a web browser
    text is the output from the unix `diff` commeand
    """
    diffs = {}

    name_a = first.student.full_name
    name_b = second.student.full_name

    # Read lines into two dictionaries
    for file_name in os.listdir(first.files_directory):
        path_a = os.path.join(first.files_directory, file_name)
        path_b = os.path.join(second.files_directory, file_name)

        diff = ""
        if use_html:
            with open(path_a, 'r') as file_a:
                with open(path_b, 'r') as file_b:
                        html = difflib.HtmlDiff(4, 80)
                        diff = html.make_file(file_a.readlines(), file_b.readlines(), name_a, name_b, context=True)
        else:
            p = subprocess.Popen(f"diff -w -u --color=always {path_a} {path_b}", shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE, universal_newlines=True)
            diff = str(p.communicate()[0])

        diffs[file_name] = diff

    return diffs

def view_diff(first, second):
    """View a diff of the two submissions"""
    use_browser = config.user.is_preference_set("browser_diff")

    diffs = diff_submissions(first, second, use_html=use_browser)

    # Write diffs to a merged file
    tmp_dir = tempfile.mkdtemp()
    with open(f"{os.path.join(tmp_dir, 'submissions.html')}", 'w') as diff_file:
        for diff in diffs:
            if use_browser:
                diff_file.write(f"<h1>{diff}</h1>")
            else:
                diff_file.write(f"\n\nFILE: {diff}\n")
            diff_file.write(diffs[diff])

    if use_browser:
        # Open diffs in the grader's default browser
        subprocess.Popen(f"xdg-open {os.path.join(tmp_dir, 'submissions.html')}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        curses.endwin()
        subprocess.run(["less", "-r", f"{os.path.join(tmp_dir, 'submissions.html')}"])
        curses.initscr()

def pair_programming_submission_callback(submission):
    window = Window.get_window()

    options = ["Open Folder", "Run", "View", "Done"]
    while True:
        option = window.create_options_popup("Downloaded", submission.msg, options, components.Popup.ALIGN_LEFT)

        if option == "View":
            submission.show_files()
        elif option == "Open Folder":
            submission.open_folder()
        elif option == "Run":
            if not submission.compile_and_run_code():
                window.create_popup("Error", ["Could not compile and run code"])
        else:
            break

    config.g_data.running_process = None

def grade_pair_programming(first_submission):
    # Get second student
    window = Window.get_window()
    students = data.get_students()

    lab = first_submission.lab

    # Get student
    line_lock = lambda student : data.lock.is_lab_locked(student, lab) if type(student) is not str else False
    student_index = window.create_filtered_list(students, "Student", filter_function=data.Student.find, draw_function=line_lock)
    if student_index is UI_GO_BACK:
        return

    student = students[student_index]

    if data.lock.is_lab_locked(student, lab):
        netid = data.lock.get_locked_netid(student, lab)

        msg = [f"This student is already being graded by {netid}"]
        window.create_popup("Student Locked", msg)
        return

    try:
        second_submission = get_submission(lab, student)

        if second_submission.flag == data.model.SubmissionFlag.NO_SUBMISSION:
            msg = [f"{student.full_name} has not submitted"]
            window.create_popup("No Submissions", msg)

            data.lock.unlock_lab(student, lab)
            return

        options = [first_submission.student.full_name, second_submission.student.full_name, "View Diff", "Done"]

        msg = [f"{first_submission.student.full_name} {first_submission.latest_submission}",
               f"{second_submission.student.full_name} {second_submission.latest_submission}",
               "", "Pick a student's submission to view or view the diff"]

        while True:
            option = window.create_options_popup("Pair Programming", msg, options)

            if option == first_submission.student.full_name:
                pair_programming_submission_callback(first_submission)
            elif option == second_submission.student.full_name:
                pair_programming_submission_callback(second_submission)
            elif option == "View Diff":
                view_diff(first_submission, second_submission)
            else:
                break

        data.lock.unlock_lab(student, lab)
    except KeyboardInterrupt:
        data.lock.unlock_lab(student, lab)
    except curses.error:
        data.lock.unlock_lab(student, lab)
    except Exception:
        data.lock.unlock_lab(student, lab)

def student_callback(lab, student_index, use_locks=True):
    window = Window.get_window()

    student = data.get_students()[student_index]

    # Wait for student's assignment to be available
    if use_locks and data.lock.is_lab_locked(student, lab):
        netid = data.lock.get_locked_netid(student, lab)

        # If being graded by the user who locked it, allow grading
        if netid != getpass.getuser():
            msg = [f"This student is already being graded by {netid}"]
            window.create_popup("Student Locked", msg)
            return

    try:
        # Get the student's submission
        submission = get_submission(lab, student, use_locks)

        # Unlock if student has not submitted
        if submission.flag == data.model.SubmissionFlag.NO_SUBMISSION:
            msg = [f"{student.full_name} has not submitted"]
            window.create_popup("No Submissions", msg)

            if use_locks:
                data.lock.unlock_lab(student, lab)
            return
        options = ["Open Folder", "Run", "View", "Done"]
        if use_locks:
            options.insert(1, "Pair Programming")

        # Add option to diff parts if this lab requires it
        if submission.flag & data.model.SubmissionFlag.DIFF_PARTS:
            options.insert(1, "Diff Parts")

        while True:
            option = window.create_options_popup("Downloaded", submission.msg, options, components.Popup.ALIGN_LEFT)

            if option == "Pair Programming":
                grade_pair_programming(submission)
            elif option == "Run":
                if not submission.compile_and_run_code():
                    window.create_popup("Error", ["Could not compile and run code"])
            elif option == "View":
                submission.show_files()
            elif option == "Open Folder":
                submission.open_folder()
            elif option == "Diff Parts":
                submission.diff_parts()
            else:
                break

        config.g_data.running_process = None

        # After popup, unlock student
        if use_locks:
            data.lock.unlock_lab(student, lab)
    except (KeyboardInterrupt, curses.error):
        if use_locks:
            data.lock.unlock_lab(student, lab)


def lab_callback(lab_index, use_locks=True):
    window = Window.get_window()

    lab = data.get_labs()[lab_index]

    students = data.get_students()

    # Get student
    line_lock = lambda student : data.lock.is_lab_locked(student, lab) if type(student) is not str else False
    window.create_filtered_list(students, "Student", \
        lambda student_index : student_callback(lab, student_index, use_locks), data.Student.find, draw_function=line_lock)

def grade(use_locks=True):
    window = Window.get_window()
    labs = data.get_labs()

    if not labs:
        window.create_popup("Error", ["No labs have been created yet"])
        return

    # Pick a lab
    window.create_filtered_list(labs, "Assignment", lambda lab_index : lab_callback(lab_index, use_locks), data.Lab.find)
