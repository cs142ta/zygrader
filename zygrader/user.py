"""User: User preference window management"""
import os

from zygrader import data, ui, zybooks
from zygrader.class_manager import download_roster
from zygrader.config import preferences
from zygrader.config.shared import SharedData
from zygrader.zybooks import Zybooks


def authenticate(window: ui.Window, zy_api: Zybooks, email="", password=""):
    """Authenticate to the zyBooks api with the email and password."""
    def wait_fn():
        success = zy_api.authenticate(email, password)
        if success:
            download_roster(silent=True)
        return success

    popup = ui.layers.WaitPopup("Signing in")
    popup.set_message([
        f"Signing into zyBooks as {email}..."
        if email else "Signing into zyBooks"
    ])
    popup.set_wait_fn(wait_fn)
    window.run_layer(popup)

    if popup.canceled:
        return False

    authenticated = popup.get_result()
    if not authenticated:
        popup = ui.layers.Popup("Error")
        popup.set_message(["Authentication Failure"])
        window.run_layer(popup)
    return authenticated


def get_password(window: ui.Window):
    """Prompt for the user's password"""

    text_input = ui.layers.TextInputLayer(
        "Enter Password", mask=ui.components.TextInput.TEXT_MASKED)
    text_input.set_prompt(["Enter your zyBooks password"])
    window.run_layer(text_input, "Sign In")

    if text_input.canceled:
        return False

    return text_input.get_text()


def login(window: ui.Window):
    """Authenticate to zybooks with the user's email and password"""
    zy_api = zybooks.Zybooks()

    while True:
        # Get user account information
        text_input = ui.layers.TextInputLayer("Enter Email")
        text_input.set_prompt(["Enter your zyBooks email"])
        window.run_layer(text_input, "Sign In")

        if text_input.canceled:
            return False

        email = text_input.get_text()
        password = get_password(window)
        if not password:
            return False

        if authenticate(window, zy_api, email, password):
            break

    return True


def logout():
    """Log a user out by erasing their token from config"""
    window = ui.get_window()

    # Clear account information
    preferences.set("refresh_token", "")

    msg = [
        "You have been logged out. Would you like to sign in with different credentials?",
        "",
        "Answering `No` will quit zygrader.",
    ]
    popup = ui.layers.BoolPopup("Sign in?")
    popup.set_message(msg)
    window.run_layer(popup)

    if popup.get_result():
        login(window)
    else:
        event_manager = ui.get_events()
        event_manager.push_zygrader_quit_event()


def update_course_data():
    SharedData.initialize_shared_data(SharedData.ZYGRADER_DATA_DIRECTORY)
    data.load_students()
    data.load_labs()
    data.load_class_sections()


def set_default_output_directory(row: ui.layers.Row):
    window = ui.get_window()
    directory = ui.layers.PathInputLayer("Default Output Directory",
                                         directory=True)
    directory.set_prompt(["Specify the default directory for output files."])
    directory.set_text(preferences.get("output_dir"))
    window.run_layer(directory)
    if directory.canceled:
        return

    # Use get_text() instead of get_path() here so we can store ~
    # in the preferences which is much shorter than the expanded version.
    path = directory.get_text()
    preferences.set("output_dir", path)
    row.set_row_text(f"Default Output Directory: {path}")

    # Set the working directory to the new path for output and input files
    # created by subprocesses (like student code)
    os.chdir(directory.get_path())


class PreferenceToggle(ui.layers.Toggle):
    def __init__(self, name, before_fn=None, after_fn=None):
        super().__init__()
        self.__name = name
        self.__before_fn = before_fn
        self.__after_fn = after_fn

    def toggle(self):
        toggled = preferences.get(self.__name)

        if self.__before_fn:
            self.__before_fn()

        preferences.set(self.__name, not toggled)

        if self.__after_fn:
            self.__after_fn()

    def is_toggled(self):
        return preferences.get(self.__name)


class StringRadioGroup(ui.layers.RadioGroup):
    def __init__(self, preference: str, after_fn=None):
        self.__preference = preference
        self.__after_fn = after_fn

    def toggle(self, _id: str):
        preferences.set(self.__preference, _id)
        if self.__after_fn:
            self.__after_fn()

    def is_toggled(self, _id: str):
        return preferences.get(self.__preference) == _id


def preferences_menu():
    """Create the preferences popup"""
    window = ui.get_window()
    popup = ui.layers.ListLayer("User Preferences", popup=True)
    popup.set_exit_text("Close")

    # Appearance sub-menu
    row = popup.add_row_parent("Appearance")
    row.add_row_toggle("Emojis", PreferenceToggle("unicode_mode"))

    # themes sub-sub-menu
    theme = row.add_row_parent("Themes")
    theme_radio = StringRadioGroup("theme")
    for theme_name in ui.themes.THEMES:
        theme.add_row_radio(theme_name, theme_radio, theme_name)

    # Navigation sub-meun
    row = popup.add_row_parent("Navigation")
    row.add_row_toggle("Vim Mode", PreferenceToggle("vim_mode"))
    row.add_row_toggle("Left/Right Arrow Navigation",
                       PreferenceToggle("left_right_arrow_nav"))
    row.add_row_toggle("Use Esc key to exit menus",
                       PreferenceToggle("use_esc_back"))

    # Editor selection submenu
    row = popup.add_row_parent("Text Editor")
    radio = StringRadioGroup("editor")
    for editor_name in preferences.EDITORS:
        row.add_row_radio(editor_name, radio, editor_name)

    row = popup.add_row_parent("Other")
    row.add_row_toggle("Auto Clear Search Text",
                       PreferenceToggle("clear_filter"))
    row.add_row_toggle("Open Diffs in Browser",
                       PreferenceToggle("browser_diff"))
    output_row = row.add_row_text(
        f"Default Output Directory: {preferences.get('output_dir')}")
    output_row.set_callback_fn(set_default_output_directory, output_row)

    # Class code selector
    row = popup.add_row_parent("Class Code")
    radio = StringRadioGroup("class_code", update_course_data)
    class_codes = SharedData.get_class_codes()
    class_codes.insert(0, "No Override")
    for code in class_codes:
        row.add_row_radio(code, radio, code)

    row = popup.add_row_parent("Account")
    row.add_row_text("Log Out", logout)

    window.register_layer(popup, "Preferences")
