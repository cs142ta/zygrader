"""Admin: Functions for more "administrator" users of zygrader to manage
the class, scan through student submissions, and access to other menus"""
from collections import defaultdict
from zygrader.ui.templates import ZybookSectionSelector, filename_input
from zygrader.ui.displaystring import DisplayStr
from zygrader.config import preferences

import csv
import datetime
import itertools
import operator
import os
import requests
import re
import time

from zygrader import bobs_shake, class_manager, data, grade_puller, ui, utils
from zygrader.zybooks import Zybooks
from zygrader.config.shared import SharedData


def check_student_submissions(zy_api, student_id, lab, search_pattern):
    """Search for a substring in all of a student's submissions for a given lab.
    Supports regular expressions.
    """
    response = {"code": Zybooks.NO_SUBMISSION}

    all_submissions = zy_api.get_all_submissions(lab["id"], student_id)
    if not all_submissions:
        return response

    for submission in all_submissions:
        # Get file from zip url
        try:
            zip_file = zy_api.get_submission_zip(submission["zip_location"])
        except requests.exceptions.ConnectionError:
            # Bad connection, wait a few seconds and try again
            return {"code": Zybooks.DOWNLOAD_TIMEOUT}

        # If there was an error
        if zip_file == Zybooks.ERROR:
            response["error"] = (f"Error fetching submission"
                                 f" {zy_api.get_time_string(submission)}")
            continue

        extracted_zip_files = utils.extract_zip(zip_file)

        # Check each file for the matched string
        for source_file in extracted_zip_files.keys():
            if search_pattern.search(extracted_zip_files[source_file]):

                # Get the date and time of the submission and return it
                response["time"] = zy_api.get_time_string(submission)
                response["code"] = Zybooks.NO_ERROR

                return response

    return response


def submission_search_fn(logger, lab, search_string, output_path, use_regex):
    students = data.get_students()
    zy_api = Zybooks()

    regex_str = search_string if use_regex else re.escape(search_string)
    search_pattern = re.compile(regex_str)

    with open(output_path, "w", newline="") as log_file:
        csv_log = csv.DictWriter(log_file,
                                 fieldnames=[
                                     "Name", "Submission",
                                     (f"(Searching for {search_string})"
                                      f"{' as a regex' if use_regex else ''}")
                                 ])
        csv_log.writeheader()
        student_num = 1

        for student in students:
            while True:
                counter = f"[{student_num}/{len(students)}]"
                logger.log(f"{counter:12} Checking {student.full_name}")

                match_result = check_student_submissions(
                    zy_api, str(student.id), lab, search_pattern)

                if match_result["code"] == Zybooks.DOWNLOAD_TIMEOUT:
                    logger.log(
                        "Download timed out... trying again after a few seconds"
                    )
                    time.sleep(5)
                else:
                    break

            if match_result["code"] == Zybooks.NO_ERROR:
                csv_log.writerow({
                    "Name": student.full_name,
                    "Submission": match_result['time']
                })

                logger.append(f" found {search_string}")

            # Check for and log errors
            if "error" in match_result:
                csv_log.writerow({
                    "Name": student.full_name,
                    "Submission": f"ERROR: {match_result['error']}"
                })

            student_num += 1


def submission_search_init():
    """Get lab part and string from the user for searching"""
    window = ui.get_window()
    labs = data.get_labs()

    menu = ui.layers.ListLayer()
    menu.set_searchable("Assignment")
    for lab in labs:
        menu.add_row_text(str(lab))
    window.run_layer(menu, "Submissions Search")
    if menu.canceled:
        return

    assignment = labs[menu.selected_index()]

    # Select the lab part if needed
    if len(assignment.parts) > 1:
        popup = ui.layers.ListLayer("Select Part", popup=True)
        for part in assignment.parts:
            popup.add_row_text(part["name"])
        window.run_layer(popup, "Submissions Search")
        if popup.canceled:
            return

        part = assignment.parts[popup.selected_index()]
    else:
        part = assignment.parts[0]

    regex_input = ui.layers.BoolPopup("Use Regex")
    regex_input.set_message(["Would you like to use regex?"])
    window.run_layer(regex_input)
    if regex_input.canceled:
        return
    use_regex = regex_input.get_result()

    text_input = ui.layers.TextInputLayer("Search String")
    text_input.set_prompt(["Enter a search string"])
    window.run_layer(text_input, "Submissions Search")
    if text_input.canceled:
        return

    search_string = text_input.get_text()

    # Get a valid output path
    filename_input = ui.layers.PathInputLayer("Output File")
    filename_input.set_prompt(["Enter the filename to save the search results"])
    filename_input.set_text(preferences.get("output_dir"))
    window.run_layer(filename_input, "Submissions Search")
    if filename_input.canceled:
        return

    logger = ui.layers.LoggerLayer()
    logger.set_log_fn(lambda: submission_search_fn(
        logger, part, search_string, filename_input.get_path(), use_regex))
    window.run_layer(logger, "Submission Search")


class LockToggle(ui.layers.Toggle):
    def __init__(self, name, list):
        super().__init__()
        self.__name = name
        self.__list = list
        self.get()

    def toggle(self):
        self.__list[self.__name] = not self.__list[self.__name]
        self.get()

    def get(self):
        self._toggled = self.__list[self.__name]


def remove_locks():
    window = ui.get_window()
    all_locks = {lock: False for lock in data.lock.get_lock_files()}

    popup = ui.layers.ListLayer("Select Locks to Remove", popup=True)
    popup.set_exit_text("Confirm")
    for lock in all_locks:
        popup.add_row_toggle(lock, LockToggle(lock, all_locks))
    window.run_layer(popup)

    selected_locks = [lock for lock in all_locks if all_locks[lock]]
    if not selected_locks:
        return

    # Confirm
    popup = ui.layers.BoolPopup("Confirm Removal")
    popup.set_message(
        [f"Are you sure you want to remove {len(selected_locks)} lock(s)?"])
    window.run_layer(popup)
    if not popup.get_result() or popup.canceled:
        return

    # Remove selected locked content
    for lock in selected_locks:
        if lock:
            data.lock.remove_lock_file(lock)


def _confirm_gradebook_ready():
    window = ui.get_window()

    confirmation = ui.layers.BoolPopup("Using canvas_master", [
        "This operation requires an up-to date canvas_master.",
        ("Please confirm that you have downloaded the gradebook"
         " and put it in the right place."), "Have you done so?"
    ])
    window.run_layer(confirmation)
    return (not confirmation.canceled) and confirmation.get_result()


def report_gaps():
    """Report any cells in the gradebook that do not have a score"""
    window = ui.get_window()

    if not _confirm_gradebook_ready():
        return

    # Use the Canvas parsing from the gradepuller to get the gradebook in
    puller = grade_puller.GradePuller()
    try:
        puller.read_canvas_csv()
    except grade_puller.GradePuller.StoppingException:
        return

    real_assignment_pattern = re.compile(r".*\([0-9]+\)")

    # Create mapping from assignment names to lists of students
    # with no grade for that assignment
    all_gaps = dict()
    for assignment in puller.canvas_header:
        if real_assignment_pattern.match(assignment):
            gaps = []
            for student in puller.canvas_students.values():
                if not student[assignment]:
                    gaps.append(student['Student'])
            if gaps:
                all_gaps[assignment] = gaps

    # Abort if no gaps present
    if not all_gaps:
        popup = ui.layers.Popup("Full Gradebook",
                                ["There are no gaps in the gradebook"])
        window.run_layer(popup)
        return

    # Transpose the data for easier reading
    rows = [list(all_gaps.keys())]
    added = True
    while added:
        added = False
        new_row = []
        for assignment in rows[0]:
            if all_gaps[assignment]:
                new_row.append(all_gaps[assignment].pop(0))
                added = True
            else:
                new_row.append("")
        rows.append(new_row)

    # select the output file and write to it
    out_path = filename_input(purpose="the gap report",
                              text=os.path.join(preferences.get("output_dir"),
                                                "gradebook_gaps.csv"))
    if out_path is None:
        return
    with open(out_path, "w", newline="") as out_file:
        writer = csv.writer(out_file)
        writer.writerows(rows)


def _get_exam_assignments(window: ui.Window, puller: grade_puller.GradePuller):
    instructions_popup = ui.layers.Popup("Instructions")
    instructions_popup.set_message([
        "Select assignments related to Exams."
        " After each assignment, you will select which exam it is a part of."
    ])
    window.run_layer(instructions_popup)
    if instructions_popup.canceled:
        return None

    # Pre-build layers that are used repeatedly in the loop
    which_exam_entry = ui.layers.TextInputLayer("Which Exam?")
    which_exam_entry.set_prompt([
        "Enter the id of the exam this assignment is part of.",
        "You can choose any id system, just be consistent"
        " (the ids are only used to associate assignments within this tool).",
        DisplayStr(
            "I recommend using [u:1] for MT1, [u:2] for MT2, and [u:0] for Final."
        )
    ])

    ask_if_more_entry = ui.layers.BoolPopup("Instructions")
    ask_if_more_base_prompt = ["Do you have more assignments to add?"]
    ask_if_more_entry.set_message(ask_if_more_base_prompt)

    exam_assignments = defaultdict(lambda: list())

    assignments_msg = ["", DisplayStr("[u:Current assignments selected]")]
    try:
        more_assignments = True
        while more_assignments:
            assignment = puller.select_canvas_assignment()

            window.run_layer(which_exam_entry)
            if which_exam_entry.canceled:
                return
            exam = which_exam_entry.get_text()

            exam_assignments[exam].append(assignment)
            assignments_msg.append(f"Exam: {exam} | {assignment}")

            ask_if_more_entry.set_message(ask_if_more_base_prompt +
                                          assignments_msg)
            window.run_layer(ask_if_more_entry)
            if ask_if_more_entry.canceled:
                return
            more_assignments = ask_if_more_entry.get_result()

    except grade_puller.GradePuller.StoppingException:
        return None

    final_exam_entry = ui.layers.ListLayer("Select which is the Final Exam",
                                           popup=True)
    assignment_list = list(exam_assignments)
    for exam in assignment_list:
        final_exam_entry.add_row_text(exam)
    window.run_layer(final_exam_entry)
    if final_exam_entry.canceled:
        return
    final_exam_assignment = assignment_list[final_exam_entry.selected_index()]

    confirmation_explanation = ui.layers.Popup("Pre-Confirmation")
    msg = [
        "Next you will confirm that you have made the correct selections.",
        "A list of the midterms you selected, with sublists containing the"
        " assignments for each midterm, will be presented.",
        DisplayStr(
            "You can then say [u:Yes], this looks good, or [u:No], I need to fix it."
        )
    ]
    confirmation_explanation.set_message(msg)
    window.run_layer(confirmation_explanation)

    confirmation_dialog = ui.layers.BoolPopup("Confirmation")
    msg = []
    for exam, assignments in exam_assignments.items():
        msg.append(
            f"Exam ID: {exam}{' (Final Exam)' if exam == final_exam_assignment else ''}"
        )
        for assignment in assignments:
            msg.append('   ' + assignment)
    msg.append("")
    msg.append("Does everything look correct?")
    confirmation_dialog.set_message(msg)
    window.run_layer(confirmation_dialog)
    if confirmation_dialog.canceled or not confirmation_dialog.get_result():
        return None

    return sorted(exam_assignments.items(),
                  key=lambda kv: kv[0] == final_exam_assignment)


def _sum_scores(mapping, assignment_names):
    return sum(
        float(mapping[assignment]) if mapping[assignment] else 0.0
        for assignment in assignment_names)


def _combined_score(assignment_names, student, points_out_of):
    points_earned = _sum_scores(student, assignment_names)
    points_total = _sum_scores(points_out_of, assignment_names)
    return points_earned / points_total


def _give_score_to_assignments(assignment_names, student, score, points_out_of):
    point_distro = sorted((float(points_out_of[assignment]), assignment)
                          for assignment in assignment_names)
    points_total = sum(v[0] for v in point_distro)
    points_left_to_distribute = score * points_total

    for point_max, assignment in point_distro:
        points_to_give = min(point_max, points_left_to_distribute)
        student[assignment] = points_to_give
        points_left_to_distribute -= points_to_give
        if points_left_to_distribute <= 0:
            break
    if points_left_to_distribute > 0:
        student[point_distro[-1][1]] += points_left_to_distribute


def _apply_midterm_mercy(midterm_assignments, final_assignments,
                         puller: grade_puller.GradePuller):
    # Do the replacement for each student
    for student in puller.canvas_students.values():
        midterm_scores = [
            _combined_score(assignments, student, puller.canvas_points_out_of)
            for assignments in midterm_assignments
        ]
        final_score = _combined_score(final_assignments, student,
                                      puller.canvas_points_out_of)

        lowest_mt_idx, lowest_mt_score = min(enumerate(midterm_scores),
                                             key=operator.itemgetter(1))

        if lowest_mt_score < final_score:
            _give_score_to_assignments(midterm_assignments[lowest_mt_idx],
                                       student, final_score,
                                       puller.canvas_points_out_of)


def midterm_mercy():
    """Replace the lower of the two midterm scores with the final exam score"""
    window = ui.get_window()

    if not _confirm_gradebook_ready():
        return

    puller = grade_puller.GradePuller()
    puller.read_canvas_csv()

    exam_assignments = _get_exam_assignments(window, puller)
    if not exam_assignments:
        return

    midterm_assignments = [
        assignments for _, assignments in exam_assignments[:-1]
    ]
    final_assignments = exam_assignments[-1][1]

    _apply_midterm_mercy(midterm_assignments, final_assignments, puller)

    out_path = filename_input(purpose="the updated midterm scores",
                              text=os.path.join(preferences.get("output_dir"),
                                                "midterm_mercy.csv"))
    if out_path is None:
        return

    # We need to programmatically set the selected assignments in the puller
    puller.selected_assignments = list(
        itertools.chain.from_iterable(midterm_assignments))

    puller.write_upload_file(out_path)

    reminder = ui.layers.Popup("Reminder")
    reminder.set_message([
        "Don't forget to manually correct as necessary"
        " (for any students who should not have a score replaced)."
    ])
    window.run_layer(reminder)


def attendance_score():
    """Calculate the participation score from the attendance score columns"""
    window = ui.get_window()

    if not _confirm_gradebook_ready():
        return

    # Make use of many functions from gradepuller to avoid code duplication
    puller = grade_puller.GradePuller()
    try:
        puller.read_canvas_csv()

        popup = ui.layers.Popup("Selection")
        popup.set_message(["First Select the Participation Score Assignment"])
        window.run_layer(popup)
        participation_score_assignment = puller.select_canvas_assignment()

        popup.set_message(["Next Select the first Classes Missed Assignment"])
        window.run_layer(popup)
        start_classes_missed_assignment = puller.select_canvas_assignment()

        popup.set_message(["Next Select the last Classes Missed Assignment"])
        window.run_layer(popup)
        end_classes_missed_assignment = puller.select_canvas_assignment()

        class_sections = puller.select_class_sections()

    except grade_puller.GradePuller.StoppingException:
        return

    # Get all of the assignments between the start and end
    start_index = puller.canvas_header.index(start_classes_missed_assignment)
    end_index = puller.canvas_header.index(end_classes_missed_assignment)
    all_classes_missed_assignments = puller.canvas_header[
        start_index:end_index + 1]

    # Figure out the grading scheme - the mapping from classes missed to grade
    builtin_schemes = [
        ("TR", [100, 100, 98, 95, 91, 86, 80, 73, 65, 57, 49, 46]),
        ("MWF", [100, 100, 99, 97, 94, 90, 85, 80, 75, 70, 65, 60, 55, 53]),
    ]
    scheme_selector = ui.layers.ListLayer("Scheme Selector", popup=True)
    for name, scheme in builtin_schemes:
        scheme_selector.add_row_text(f"{name}: {','.join(map(str,scheme))},...")
    scheme_selector.add_row_text("Create New Scheme")

    window.run_layer(scheme_selector)
    if scheme_selector.canceled:
        return

    selected = scheme_selector.selected_index()
    if selected < len(builtin_schemes):
        points_by_classes_missed = builtin_schemes[selected][1]
    else:
        # Get the custom scheme
        scheme_inputter = ui.layers.TextInputLayer("New Scheme")
        scheme_inputter.set_prompt([
            "Enter a new scheme as a comma-separated list",
            "e.g. '100,100,95,90,85,80,78'",
            "",
            "The difference between the last two values will be repeated"
            " until a score of 0 is reached",
        ])
        window.run_layer(scheme_inputter)
        if scheme_inputter.canceled:
            return
        scheme_text = scheme_inputter.get_text()
        points_by_classes_missed = list(map(int, scheme_text.split(',')))

    # Extend the scheme until 0 is reached
    delta = points_by_classes_missed[-2] - points_by_classes_missed[-1]
    while points_by_classes_missed[-1] >= 0:
        points_by_classes_missed.append(points_by_classes_missed[-1] - delta)
    # Get rid of the negative element
    del points_by_classes_missed[-1]

    # Calculate and assign the grade for each student
    for student in puller.canvas_students.values():
        if student["section_number"] in class_sections:
            total_classes_missed = 0
            for assignment in all_classes_missed_assignments:
                score_str = student[assignment]
                try:
                    # the gradebook might have decimals (e.g. 0.00),
                    # but we need an int for total_classes_missed to be
                    # used as a key. hence parsing the string as a float,
                    # then immediately casting to int (python raises
                    # ValueError for casting decimal strings to ints)
                    total_classes_missed += int(float(score_str))
                except ValueError:
                    if score_str == "N/A":
                        # count N/A as zero (for ease of grading online section)
                        pass
                    else:
                        total_classes_missed = (
                            total_classes_missed +
                            int(float(puller.canvas_points_out_of[assignment])))

            try:
                grade = points_by_classes_missed[total_classes_missed]
            except IndexError:
                grade = 0
            student[participation_score_assignment] = grade

    out_path = filename_input(purpose="the partipation score",
                              text=os.path.join(preferences.get("output_dir"),
                                                "participation.csv"))
    if out_path is None:
        return

    # Again use the gradepuller functionality
    # We just need to programmatically set the selected assignments
    puller.selected_assignments = [participation_score_assignment]
    # And the involved class sections
    puller.involved_class_sections = set(class_sections)
    puller.write_upload_file(out_path, restrict_sections=True)


def report_high_scoring_students():
    """Generate a list of students who met specified thresholds"""
    window = ui.get_window()

    # Selecting Assignments to Consider
    selector = ZybookSectionSelector()
    zybook_assignments = selector.select_zybook_sections(
        title_extra="Assignments to Consider")
    if not zybook_assignments:
        return

    # Selecting Minimum Score
    min_score_input_prompt = [
        "Enter the minimum score needed on each assignment to be considered (0-100):",
        "(the default text is a suggested minimum)"
    ]
    schema_input = ui.layers.TextInputLayer("Minimum Score")
    schema_input.set_prompt(min_score_input_prompt)
    schema_input.set_text("85")
    valid_input = False
    minimum_score = 0
    while not valid_input:
        window.run_layer(schema_input)
        if schema_input.canceled:
            return
        try:
            minimum_score = int(schema_input.get_text())
            valid_input = True
        except ValueError:
            window.run_layer(
                ui.layers.Popup("Error", ["You must provide integer values"]))

    # Select the output file location
    out_path = filename_input(purpose="the high scorer's report",
                              text=os.path.join(preferences.get("output_dir"),
                                                "high_scorers.csv"))
    if out_path is None:
        return

    # The rest of the function is data crunching,
    # and it takes a while, so wrap it in a WaitPopup
    wait_popup = ui.layers.WaitPopup("Filtering")

    def data_cruncher():
        # Fetch Completion Report
        wait_popup.set_message([f"Fetching completion report."])
        now = datetime.datetime.now()
        puller = grade_puller.GradePuller()
        report, header = puller.fetch_completion_report(now, zybook_assignments)

        # Set up for filtering
        considerables = set(report.keys())

        score_column_pat = re.compile(r".*\([1-9][0-9]*\)")
        total_column_pat = re.compile(r".*total.*", re.IGNORECASE)

        # Filter students
        wait_popup.set_message(["Filtering students based on scores."])
        for assignment_name in header:
            if ((not score_column_pat.match(assignment_name))
                    or total_column_pat.match(assignment_name)):
                continue
            for stud in report.keys():
                score_str = report[stud][assignment_name]
                score = float(score_str) if score_str else 0
                if score < minimum_score:
                    considerables.discard(stud)

        # Write the report
        wait_popup.set_message(["Writing the report"])
        # Use the same headers as the report, up to and including the email column
        email_column_pat = re.compile(r".*email.*", re.IGNORECASE)
        output_headers = []
        for column in header:
            output_headers.append(column)
            if email_column_pat.match(column):
                break
        with open(out_path, "w", newline="") as out_file:
            writer = csv.DictWriter(out_file,
                                    fieldnames=output_headers,
                                    extrasaction='ignore')
            writer.writeheader()
            writer.writerows(row for stud, row in report.items()
                             if stud in considerables)

    # Run the wait popup we made earlier, with the data crunching inside it
    wait_popup.set_wait_fn(data_cruncher)
    window.run_layer(wait_popup)


def end_of_semester_tools():
    """Create the menu for end of semester tools"""
    window = ui.get_window()

    menu = ui.layers.ListLayer()
    menu.add_row_text("Report Gaps", report_gaps)
    menu.add_row_text("Midterm Mercy", midterm_mercy)
    menu.add_row_text("Attendance Score", attendance_score)

    window.register_layer(menu)


HM_RANGE_FORMAT_STR = "%H hours, %M minutes"


def set_recently_locked_range(row: ui.layers.Row, name: str):
    window = ui.get_window()
    duration_selector = ui.layers.DatetimeSpinner(
        f"Set {name} recently locked range")

    original = SharedData.RECENT_LOCK_GRADES if name == "grades" else SharedData.RECENT_LOCK_EMAILS
    duration_selector.set_initial_time(
        datetime.time(hour=original // 60, minute=original % 60))
    duration_selector.set_format_str(HM_RANGE_FORMAT_STR)

    window.run_layer(duration_selector)

    new_range_time = duration_selector.get_time()
    new_range = new_range_time.hour * 60 + new_range_time.minute
    SharedData.set_recently_locked(name, new_range)
    row.set_row_text(f"{'Grader:' if name == 'grades' else 'Email: '}"
                     f" {new_range_time.strftime(HM_RANGE_FORMAT_STR)}")
    SharedData.initialize_recently_locked()


class ClassCodeRadioGroup(ui.layers.RadioGroup):
    def __init__(self, config: str, fn=None):
        self._config = config
        self._fn = fn

    def toggle(self, _id: str):
        SharedData.set_current_class_code(_id)

    def is_toggled(self, _id: str):
        return SharedData.CLASS_CODE == _id


def admin_config():
    """A menu of admin configurations similar to the user preferences"""
    window = ui.get_window()
    popup = ui.layers.ListLayer("Admin Config", popup=True)
    popup.set_exit_text("Close")

    # Recently locked time ranges
    row = popup.add_row_parent("Recently Locked Ranges")
    grade_range = datetime.time(hour=SharedData.RECENT_LOCK_GRADES // 60,
                                minute=SharedData.RECENT_LOCK_GRADES % 60)
    sub = row.add_row_text(
        f"Grader: {grade_range.strftime(HM_RANGE_FORMAT_STR)}")
    sub.set_callback_fn(set_recently_locked_range, sub, "grades")
    email_range = datetime.time(hour=SharedData.RECENT_LOCK_EMAILS // 60,
                                minute=SharedData.RECENT_LOCK_EMAILS % 60)
    sub = row.add_row_text(
        f"Email:  {email_range.strftime(HM_RANGE_FORMAT_STR)}")
    sub.set_callback_fn(set_recently_locked_range, sub, "emails")

    # Shared Class Code
    row = popup.add_row_parent("Class Code")
    radio = ClassCodeRadioGroup("class_code")
    class_codes = SharedData.get_class_codes()
    for code in class_codes:
        row.add_row_radio(code, radio, code)

    window.register_layer(popup, "Admin Config")


def admin_menu():
    """Create the admin menu"""
    window = ui.get_window()

    menu = ui.layers.ListLayer()
    menu.add_row_text("Submissions Search", submission_search_init)
    menu.add_row_text("Grade Puller", grade_puller.GradePuller().pull)
    menu.add_row_text("Find Unmatched Students",
                      grade_puller.GradePuller().find_unmatched_students)
    menu.add_row_text("Remove Locks", remove_locks)
    menu.add_row_text("Class Management", class_manager.start)
    menu.add_row_text("Bob's Shake", bobs_shake.shake)
    menu.add_row_text("End Of Semester Tools", end_of_semester_tools)
    menu.add_row_text("Report High-Scoring Students",
                      report_high_scoring_students)
    menu.add_row_text("Config", admin_config)

    window.register_layer(menu, "Admin")
