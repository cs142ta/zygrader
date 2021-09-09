"""Zygrader: Main menu for zygrader"""
import argparse
import os
import signal
import sys
import time

from zygrader import (admin, config, data, email_manager, grader, logger, ui,
                      updater, user, utils, zybooks)
from zygrader.config import preferences, versioning
from zygrader.config.shared import SharedData


def lock_cleanup():
    # If terminating before shared directories are initialized, the folders would be
    # created in the current directory when removing locks. See #72 for more details.
    if SharedData.is_initialized():
        data.lock.unlock_all_labs_by_grader(utils.get_username())


def sighup_handler(signum, frame):
    lock_cleanup()
    # This ensures that terminating an SSH connection will indeed exit zygrader
    sys.exit(1)


def sigint_handler(signum, frame):
    if SharedData.RUNNING_CODE:
        # If child process is running
        if SharedData.running_process.poll() is None:
            SharedData.RUNNING_CODE = False
            SharedData.running_process.send_signal(signal.SIGINT)
            SharedData.running_process = None
    else:
        # Terminating the program
        lock_cleanup()
        sys.exit(0)


def sigtstp_handler(signum, frame):
    if SharedData.RUNNING_CODE:
        # If child process is running
        if SharedData.running_process.poll() is None:
            SharedData.RUNNING_CODE = False
            SharedData.running_process.send_signal(signal.SIGTSTP)


def parse_args():
    """Parse CMD args"""
    parser = argparse.ArgumentParser(
        description="download and inspect zyBooks data for grading")
    parser.add_argument("-s",
                        "--set-data-dir",
                        help="Data path for shared zygrader files")
    parser.add_argument("--init-data-dir",
                        help="Create the folder for shared zygrader files")
    parser.add_argument("-a",
                        "--admin",
                        action="store_true",
                        help="Enable admin features")
    parser.add_argument("-d",
                        "--debug",
                        action="store_true",
                        help="Show the debug console")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-n",
                       "--no-update",
                       action="store_true",
                       help="Do not check for updates")
    group.add_argument("-i",
                       "--install-version",
                       help="Specify version to install")

    return parser.parse_args()


def handle_args(args):
    if args.set_data_dir:
        if preferences.set_data_directory(args.set_data_dir):
            print(
                f"Successfully set the shared data dir to {args.set_data_dir}")
            time.sleep(1)
        else:
            print(f'Error: The path "{args.set_data_dir}" does not exist.')
            sys.exit()

    if args.init_data_dir:
        if not os.path.exists(args.init_data_dir):
            print(f"Error: the path {args.init_data_dir} does not exist.")
            sys.exit()

        shared_data_dir = os.path.join(args.init_data_dir, "zygrader_data")

        print(f"Warning: You are about to create the following directory:")
        print(f"{shared_data_dir}")
        print(f"Any existing data will be overwritten.")
        print(f"Type 'Y' to confirm, anything else to cancel: ", end="")

        confirm = input()
        if confirm not in {"Y", "y", "yes", "Yes"}:
            print("Canceled")
            sys.exit()

        SharedData.create_shared_data_directory(shared_data_dir)
        preferences.set_data_directory(shared_data_dir)

        print(f"Successfully created the shared data dir at {shared_data_dir}")
        print()
        print(f"Instruct users to run zygrader with the following flag:")
        print(f"zygrader --set-data-dir {shared_data_dir}")
        sys.exit()


def view_changelog():
    window = ui.get_window()
    lines = config.versioning.load_changelog()

    popup = ui.layers.ListLayer("Changelog", popup=True)
    popup.set_exit_text("Press enter to close")
    popup.set_paged()
    for line in lines:
        popup.add_row_text(line)
    window.run_layer(popup, "Changelog")


def mainloop(args):
    """Create the main menu that runs until zygrader is exited"""
    window = ui.get_window()

    # Create the main menu
    menu = ui.layers.ListLayer()
    menu.set_exit_text("Quit")
    menu.add_row_text("Grade", grader.grade)
    menu.add_row_text("Emails", email_manager.email_menu)
    menu.add_row_text("Prep Lab Score Calculator", utils.prep_lab_score_calc)
    menu.add_row_text("Run For Fun", lambda: grader.grade(use_locks=False))
    menu.add_row_text("View Students", utils.view_students)
    menu.add_row_text("Preferences", user.preferences_menu)
    menu.add_row_text("Changelog", view_changelog)
    if args.admin:
        menu.add_row_text("Admin", admin.admin_menu)
    window.register_layer(menu, "Main Menu")

    # Begin the event loop
    window.loop()


def preference_update_fn():
    """Callback that is run when preferences are updated"""
    window = ui.get_window()
    window.update_preferences()

    events = ui.get_events()
    events.update_preferences()


def main(window: ui.Window, args):
    """Curses has been initialized, now setup various modules before showing the menu"""
    # Register preference update callback
    preferences.add_observer(preference_update_fn)
    preferences.update_observers()

    # Notify the user of changes
    versioning.show_versioning_message(window)

    # Start file watch thread
    data.fs_watch.start_fs_watch()

    # Authenticate the user
    zybooks_api = zybooks.Zybooks()
    if not preferences.get("refresh_token") or not user.authenticate(
            window, zybooks_api):
        user.login(window)

    logger.log("zygrader started")

    mainloop(args)


def start():
    """Setup before initializing curses"""

    # Handle Signals
    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTSTP, sigtstp_handler)
    signal.signal(signal.SIGHUP, sighup_handler)

    # Set a short ESC key delay (curses environment variable)
    os.environ.setdefault("ESCDELAY", "25")

    args = parse_args()

    # Check for updates
    if not args.no_update and not args.install_version:
        latest_version = updater.get_latest_version()
        if latest_version != SharedData.VERSION:
            updater.update_zygrader(latest_version)
            sys.exit()

    if args.install_version:
        updater.install_version(args.install_version)
        sys.exit()

    # Setup user configuration
    preferences.initialize()

    versioning.versioning_update_preferences()

    # Handle configuration based args after config has been initialized
    handle_args(args)

    # Check for shared data dir
    data_dir = preferences.get("data_dir")
    if not data_dir:
        print("You have not set the shared data directory")
        print("Please run with the flag --set-data-dir [path]")
        sys.exit()

    # Start application and setup data folders
    if not SharedData.initialize_shared_data(data_dir):
        sys.exit()

    # Load data for the current class
    data.get_students()
    data.get_labs()

    # Change directory to the default output dir
    os.chdir(os.path.expanduser(preferences.get("output_dir")))

    name = data.netid_to_name(utils.get_username())

    # Create a zygrader window, callback to main function
    ui.Window(main, f"zygrader {SharedData.VERSION}", name, args)

    logger.log("zygrader exited normally")


if __name__ == "__main__":
    start()
