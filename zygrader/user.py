"""User: User preference window management"""
from zygrader import zybooks

from zygrader.config import preferences
from zygrader.ui.window import Window, WinContext
from zygrader.ui.components import TextInput

def authenticate(window: Window, zy_api, email, password):
    """Authenticate to the zyBooks api with the email and password"""
    wait_popup = window.create_waiting_popup("Signing in", [f"Signing into zyBooks as {email}..."])
    success = zy_api.authenticate(email, password)
    wait_popup.close()

    if not success:
        window.create_popup("Error", ["Invalid Credentials"])
        return False
    return True

def get_email():
    """Get the user's email address from config"""
    config = preferences.get_config()
    if "email" in config:
        return config["email"]
    return ""

def get_password(window: Window):
    """Prompt for the user's password"""
    window.set_header("Sign In")

    password = window.create_text_input("Enter Password", "Enter your zyBooks password", mask=TextInput.TEXT_MASKED)
    if password == Window.CANCEL:
        password = ""

    return password

# Create a user account
def create_account(window: Window, zy_api):
    """Create zybooks user account info (email & password) in config"""
    window.set_header("Sign In")

    while True:
        # Get user account information
        email = window.create_text_input("Enter Email", "Enter your zyBooks email", mask=None)
        if email == Window.CANCEL:
            email = ""
        password = get_password(window)

        if authenticate(window, zy_api, email, password):
            break

    return email, password

def login(window: Window):
    """Authenticate to zybooks with the user's email and password
    or create an account if one does not exist"""
    zy_api = zybooks.Zybooks()
    config = preferences.get_config()

    # If user email and password exists, authenticate and return
    if "email" in config and "password" in config and config["password"]:
        password = preferences.decode_password(config)
        authenticate(window, zy_api, config["email"], password)
        window.set_email(config["email"])
        return config

    # User does not have account created
    if not config["email"]:
        email, password = create_account(window, zy_api)

        save_password = window.create_bool_popup("Save Password",
                                                 ["Would you like to save your password?"])

        config["email"] = email

        if save_password:
            config["save_password"] = ""
            preferences.encode_password(config, password)

        preferences.write_config(config)
        window.set_email(email)

    # User has not saved password, re-prompt
    elif "password" in config and not config["password"]:
        email = config["email"]

        while True:
            password = get_password(window)

            if authenticate(window, zy_api, email, password):
                if preferences.is_preference_set("save_password"):
                    preferences.encode_password(config, password)
                    preferences.write_config(config)
                break

def draw_text_editors():
    """Draw the list of text editors"""
    options = []
    current_editor = preferences.get_preference("editor")

    for name in preferences.EDITORS:
        if current_editor == name:
            options.append(f"[X] {name}")
        else:
            options.append(f"[ ] {name}")

    return options

def set_editor(editor_index, pref_name):
    """Set the user's default editor to the selected editor"""
    config_file = preferences.get_config()
    config_file[pref_name] = list(preferences.EDITORS.keys())[editor_index]

    preferences.write_config(config_file)

def set_editor_menu(name):
    """Open the set editor popup"""
    window = Window.get_window()
    edit_fn = lambda context: set_editor(context.data, name)
    window.create_list_popup("Set Editor", callback=edit_fn, list_fill=draw_text_editors)

def toggle_preference(pref):
    """Toggle a boolean preference"""
    config = preferences.get_config()

    if pref in config:
        del config[pref]
    else:
        config[pref] = ""

    preferences.write_config(config)

def password_toggle(name):
    """Toggle saving the user's password in their config file (encoded)"""
    toggle_preference(name)
    config = preferences.get_config()

    if name not in config:
        config["password"] = ""
        preferences.write_config(config)

    else:
        window = Window.get_window()
        window.create_popup("Remember Password",
                            ["Next time you start zygrader your password will be saved."])

class Preference:
    """Holds information for a user preference item"""
    def __init__(self, name, description, select_fn, toggle=True):
        self.name = name
        self.description = description
        self.select_fn = select_fn
        self.toggle = toggle

PREFERENCES = [Preference("left_right_arrow_nav", "Left/Right Arrow Navigation", toggle_preference),
               Preference("use_esc_back", "Use Esc key to exit menus", toggle_preference),
               Preference("clear_filter", "Auto Clear List Filters", toggle_preference),
               Preference("vim_mode", "Vim Mode", toggle_preference),
               Preference("dark_mode", "Dark Mode", toggle_preference),
               Preference("christmas_mode", "Christmas Theme", toggle_preference),
               Preference("browser_diff", "Open Diffs in Browser", toggle_preference),
               Preference("save_password", "Remember Password", password_toggle),
               Preference("editor", "Set Editor", set_editor_menu, False),
               ]

def draw_preferences():
    """Create the list of user preferences"""
    options = []
    for pref in PREFERENCES:
        if not pref.toggle:
            options.append(f"    {pref.description}")
        else:
            if preferences.is_preference_set(pref.name):
                options.append(f"[X] {pref.description}")
            else:
                options.append(f"[ ] {pref.description}")

    return options

def preferences_callback(context: WinContext):
    """Callback to run when a preference is selected"""
    selected_index = context.data
    pref = PREFERENCES[selected_index]
    pref.select_fn(pref.name)

    context.window.update_preferences()

def preferences_menu():
    """Create the preferences popup"""
    window = Window.get_window()
    window.set_header(f"Preferences")

    window.create_list_popup("User Preferences", callback=preferences_callback,
                             list_fill=draw_preferences)