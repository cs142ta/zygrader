"""Class Manager: Functions to manage zybooks classes"""
import json

from zygrader import data, ui
from zygrader.config.shared import SharedData
from zygrader.ui.templates import ZybookSectionSelector
from zygrader.zybooks import Zybooks


def save_roster(roster):
    """Save the roster of students to a json file"""
    roster = roster["roster"]  # It is stored under "roster" in the json

    # Download students (and others)
    students = []
    for role in roster:
        for person in roster[role]:
            student = {}
            student["first_name"] = person["first_name"]
            student["last_name"] = person["last_name"]
            student["email"] = person["primary_email"]
            student["id"] = person["user_id"]

            if "class_section" in person:
                student["section"] = person["class_section"]["value"]
            else:
                student["section"] = -1

            students.append(student)

    out_path = SharedData.get_student_data()
    with open(out_path, "w") as _file:
        json.dump(students, _file, indent=2)


def setup_new_class():
    """Setup a new class based on a zyBooks class code"""
    window = ui.get_window()
    zy_api = Zybooks()

    text_input = ui.layers.TextInputLayer("Class Code")
    text_input.set_prompt(["Enter class code"])
    window.run_layer(text_input)
    if text_input.canceled:
        return

    # Check if class code is valid
    code = text_input.get_text()
    valid = zy_api.check_valid_class(code)
    if valid:
        popup = ui.layers.Popup("Valid", [f"{code} is valid"])
        window.run_layer(popup)
    else:
        popup = ui.layers.Popup("Invalid", [f"{code} is invalid"])
        window.run_layer(popup)
        return

    # If code is valid, add it to the shared configuration
    SharedData.add_class(code)

    # Download the list of students
    roster = zy_api.get_roster()

    save_roster(roster)
    popup = ui.layers.Popup("Finished",
                            ["Successfully downloaded student roster"])
    window.run_layer(popup)
    class_section_manager()


def add_lab():
    """Add a lab to the current class"""
    window = ui.get_window()
    zy_api = Zybooks()

    text_input = ui.layers.TextInputLayer("Lab Name")
    text_input.set_prompt(["Enter the Lab Name"])
    window.run_layer(text_input)
    if text_input.canceled:
        return

    lab_name = text_input.get_text()

    # Get lab part(s)
    parts = []

    section_selector = ZybookSectionSelector(allow_optional_and_hidden=True)
    section_numbers = section_selector.select_zybook_sections(
        return_just_numbers=True)

    for chapter, section in section_numbers:
        part = {}
        response = zy_api.get_zybook_section(chapter, section)
        if not response.success:
            popup = ui.layers.Popup("Error", ["Invalid URL"])
            window.run_layer(popup)
        part["name"] = response.name
        part["id"] = response.id
        parts.append(part)

    new_lab = data.model.Lab(lab_name, parts, {})

    edit_lab_options(new_lab)

    all_labs = data.get_labs()
    all_labs.append(new_lab)

    data.write_labs(all_labs)


def fill_lab_list(lab_list: ui.layers.ListLayer, labs: data.model.Lab):
    lab_list.clear_rows()
    for lab in labs:
        lab_list.add_row_text(str(lab), edit_labs_fn, lab, lab_list)
    lab_list.rebuild = True


def set_date_text(lab, row: ui.layers.Row):
    # Update the row text
    if "due" in lab.options:
        date = lab.options["due"].strftime("%m.%d.%Y:%H.%M.%S")
        row.set_row_text(f"Due Date: {date}")
    else:
        row.set_row_text("Due Date: None")


def set_due_date(lab, row: ui.layers.Row):
    """Set a cutoff date for a lab

    When grading the submission before the cutoff date will be shown, but the
    in-grader submission picker allows to pick submissions after the cutoff date
    if needed
    """
    window = ui.get_window()

    labs = data.get_labs()

    old_date = lab.options.get("due", None)
    date_spinner = ui.layers.DatetimeSpinner("Due Date")
    date_spinner.set_optional(True)
    if old_date:
        date_spinner.set_initial_time(old_date)
    window.run_layer(date_spinner)
    if date_spinner.canceled:
        return

    due_date = date_spinner.get_time()

    # Clearing the due date
    if due_date == ui.components.DatetimeSpinner.NO_DATE:
        if "due" in lab.options:
            del lab.options["due"]
    else:
        # Remove time zone information
        lab.options["due"] = due_date.astimezone(tz=None)

    data.write_labs(labs)
    set_date_text(lab, row)


def rename_lab(lab_list: ui.layers.ListLayer, lab):
    """Rename a lab"""
    window = ui.get_window()
    labs = data.get_labs()

    text_input = ui.layers.TextInputLayer("Rename Lab")
    text_input.set_prompt(["Enter Lab's new name"])
    text_input.set_text(lab.name)
    window.run_layer(text_input)
    if not text_input.canceled:
        lab.name = text_input.get_text()
        data.write_labs(labs)
        fill_lab_list(lab_list, labs)


def toggle_lab_option(lab, option):
    """Toggle a boolean lab option (T/F value)"""
    if option in lab.options:
        del lab.options[option]
    else:
        lab.options[option] = ""

    labs = data.get_labs()
    data.write_labs(labs)


class LabOptionToggle(ui.layers.Toggle):
    def __init__(self, lab, option):
        super().__init__()
        self.__lab = lab
        self.__option = option
        self.get()

    def toggle(self):
        toggle_lab_option(self.__lab, self.__option)
        self.get()

    def get(self):
        self._toggled = self.__option in self.__lab.options


def edit_lab_options(lab):
    window = ui.get_window()

    popup = ui.layers.ListLayer("Edit Lab Options", popup=True)
    popup.add_row_toggle("Grade Highest Scoring Submission",
                         LabOptionToggle(lab, "highest_score"))
    popup.add_row_toggle("Diff Submission Parts",
                         LabOptionToggle(lab, "diff_parts"))
    row = popup.add_row_text("Due Date")
    row.set_callback_fn(set_due_date, lab, row)
    set_date_text(lab, row)
    window.register_layer(popup)


def move_lab(lab_list: ui.layers.ListLayer, lab, step):
    """Move a lab up or down the list of labs"""
    labs = data.get_labs()
    index = labs.index(lab)

    # Prevent moving out of bounds
    if index + step > len(labs) - 1 or index + step < 0:
        return

    labs[index] = labs[index + step]
    labs[index + step] = lab

    data.write_labs(labs)
    lab_list.component._selected_index += step
    fill_lab_list(lab_list, labs)


def remove_fn(lab_list, window, lab) -> bool:
    """Remove a lab from the list"""
    msg = [f"Are you sure you want to remove {lab.name}?"]
    popup = ui.layers.BoolPopup("Confirm", msg)
    window.run_layer(popup)
    remove = popup.get_result()

    if remove:
        labs = data.get_labs()
        labs.remove(lab)
        data.write_labs(labs)

    labs = data.get_labs()
    fill_lab_list(lab_list, labs)
    events = ui.get_events()
    events.push_layer_close_event()
    return remove


def edit_labs_fn(lab, lab_list: ui.layers.ListLayer):
    """Create a popup for basic lab editing options"""
    window = ui.get_window()

    msg = [f"Editing {lab.name}", "", "Select an option"]
    popup = ui.layers.OptionsPopup("Edit Lab", msg)
    popup.add_option("Remove", lambda: remove_fn(lab_list, window, lab))
    popup.add_option("Rename", lambda: rename_lab(lab_list, lab))
    popup.add_option("Move Up", lambda: move_lab(lab_list, lab, -1))
    popup.add_option("Move Down", lambda: move_lab(lab_list, lab, 1))
    popup.add_option("Edit Options", lambda: edit_lab_options(lab))
    window.register_layer(popup)


def edit_labs():
    """Creates a list of labs to edit"""
    window = ui.get_window()
    labs = data.get_labs()

    lab_list = ui.layers.ListLayer()
    fill_lab_list(lab_list, labs)
    window.register_layer(lab_list)


def get_class_section(old_section: data.model.ClassSection = None):
    window = ui.get_window()

    text_input = ui.layers.TextInputLayer("Section Number")
    text_input.set_prompt(["Enter the new section number for this section"])
    if old_section:
        text_input.set_text(str(old_section.section_number))
    window.run_layer(text_input)
    if text_input.canceled:
        return None

    # FIXME: This assumes the int parses correctly
    section_num = int(text_input.get_text())

    date_spinner = ui.layers.DatetimeSpinner("Section Default Due Time")
    date_spinner.set_quickpicks([(50, 0), (59, 59), (0, 0)])
    date_spinner.set_include_date(False)
    if old_section:
        date_spinner.set_initial_time(old_section.default_due_time)
    window.run_layer(date_spinner)

    default_due_time = date_spinner.get_time()
    if default_due_time == ui.GO_BACK:
        return None

    text_input = ui.layers.TextInputLayer("Section Group")
    text_input.set_prompt(
        ["Enter the name of the new section group for this section"])
    if old_section:
        text_input.set_text(old_section.section_group)
    window.run_layer(text_input)
    if text_input.canceled:
        return None

    section_group = text_input.get_text()

    return data.model.ClassSection(section_num, default_due_time, section_group)


def add_class_section():
    """Add a class section to the current class"""
    new_class_section = get_class_section()
    if not new_class_section:
        return

    class_sections = data.get_class_sections()
    class_sections.append(new_class_section)

    data.write_class_sections(class_sections)


def remove_class_section():
    window = ui.get_window()
    class_sections = data.get_class_sections()

    popup = ui.layers.ListLayer("Pick Section", popup=True)
    for section in class_sections:
        popup.add_row_text(str(section))
    window.run_layer(popup)
    if popup.canceled:
        return

    selected_section = popup.selected_index()

    popup = ui.layers.BoolPopup("Confirm")
    popup.set_message([
        f"Are you sure you want to delete {class_sections[selected_section]}?"
    ])
    window.run_layer(popup)

    if not popup.get_result():
        return

    del class_sections[selected_section]
    data.write_class_sections(class_sections)


def fill_class_section_list(section_list: ui.layers.ListLayer):
    section_list.clear_rows()
    class_sections = data.get_class_sections()
    for section in class_sections:
        section_list.add_row_text(str(section), edit_class_sections_fn,
                                  section_list, section)
    section_list.rebuild = True


def edit_class_sections_fn(section_list: ui.layers.ListLayer, class_section):
    new_section = get_class_section(old_section=class_section)
    if not new_section:
        return

    class_section.copy(new_section)

    data.write_class_sections(data.get_class_sections())
    fill_class_section_list(section_list)


def edit_class_sections():
    """Create list of class sections to edit"""
    window = ui.get_window()

    section_list = ui.layers.ListLayer()
    fill_class_section_list(section_list)
    window.register_layer(section_list)


def sort_class_sections():
    class_sections = data.get_class_sections()
    class_sections = sorted(class_sections, key=lambda sec: sec.section_number)
    data.write_class_sections(class_sections)

    window = ui.get_window()
    popup = ui.layers.Popup(
        "Finished", ["The Class Sections are now sorted by section number"])
    window.run_layer(popup)


def download_roster(silent=False):
    """Download the roster of students from zybooks and save to disk"""
    window = ui.get_window()
    zy_api = Zybooks()

    roster = zy_api.get_roster()

    if not silent and not roster:
        popup = ui.layers.Popup("Failed", ["Failed to download student roster"])
        window.run_layer(popup)
        return
    if roster:
        save_roster(roster)
    if not silent:
        popup = ui.layers.Popup("Finished",
                                ["Successfully downloaded student roster"])
        window.run_layer(popup)


def lab_manager():
    window = ui.get_window()

    menu = ui.layers.ListLayer()
    menu.add_row_text("Add Lab", add_lab)
    menu.add_row_text("Edit Current Labs", edit_labs)
    window.register_layer(menu, "Lab Manager")


def class_section_manager():
    window = ui.get_window()

    menu = ui.layers.ListLayer()
    menu.add_row_text("Add Section", add_class_section)
    menu.add_row_text("Remove Section", remove_class_section)
    menu.add_row_text("Edit Current Sections", edit_class_sections)
    menu.add_row_text("Sort Current Sections", sort_class_sections)
    window.register_layer(menu, "Class Section Manager")


def start():
    """Create the main class manager menu"""
    window = ui.get_window()

    menu = ui.layers.ListLayer()
    menu.add_row_text("Setup New Class", setup_new_class)
    menu.add_row_text("Lab Manager", lab_manager)
    menu.add_row_text("Class Section Manager", class_section_manager)
    menu.add_row_text("Download Student Roster", download_roster)
    window.register_layer(menu, "Class Manager")
