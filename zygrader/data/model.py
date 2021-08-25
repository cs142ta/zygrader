import curses
import datetime
import enum
import os
import signal
import subprocess
import time
from collections import Iterable

from zygrader import ui, utils
from zygrader.config import preferences
from zygrader.config.shared import SharedData
from zygrader.zybooks import Zybooks


class Lab:
    def __init__(self, name, parts, options):
        self.name = name
        self.parts = parts
        self.options = options

        # Convert due datetime strings to objects
        if "due" in self.options:
            self.options["due"] = datetime.datetime.strptime(
                self.options["due"], "%m.%d.%Y:%H.%M.%S").astimezone(tz=None)

    def __eq__(self, other):
        return self.name == other.name

    def __str__(self):
        return f"{self.name}"

    def get_unique_name(self):
        name = "".join(self.name.split())
        return f"{name}_{self.parts[0]['id']}"

    @classmethod
    def find(cls, line, text):
        assignment = line.data

        name = assignment.name.lower()
        text = text.lower()

        return name.find(text) != -1

    def to_json(self):
        lab = {
            "name": self.name,
            "parts": self.parts,
            "options": self.options.copy()
        }
        if "due" in lab["options"] and type(lab["options"]["due"]) is not str:
            lab["options"]["due"] = lab["options"]["due"].strftime(
                "%m.%d.%Y:%H.%M.%S")

        return lab


class Student:
    def __init__(self, first_name, last_name, email, section, id):
        self.first_name = first_name
        self.last_name = last_name
        self.full_name = f"{first_name} {last_name}"
        self.email = email
        self.section = section
        self.id = id

    def __eq__(self, other):
        return self.full_name == other.full_name and self.email == other.email and self.id == other.id

    def __str__(self):
        return f"{self.full_name} - {self.email} - Section {self.section}"

    def get_unique_name(self):
        name = "".join(self.full_name.split())
        return f"{name}_{self.id}"

    @classmethod
    def find(cls, line, text):
        student = line.data

        first_name = student.first_name.lower()
        last_name = student.last_name.lower()
        full_name = student.full_name.lower()
        email = student.email.lower()
        text = text.lower()

        return (first_name.find(text) != -1 or last_name.find(text) != -1
                or full_name.find(text) != -1 or email.find(text) != -1)


class ClassSection:
    DUE_TIME_STORAGE_FORMAT = "%H.%M.%S"
    DUE_TIME_DISPLAY_FORMAT = "%I:%M:%S%p"

    max_section_num = 0

    def __init__(self, section_number, default_due_time, section_group=None):
        self.section_number = section_number
        if section_number > ClassSection.max_section_num:
            ClassSection.max_section_num = section_number

        if isinstance(default_due_time, datetime.datetime):
            default_due_time = default_due_time.time()
        elif not isinstance(default_due_time, datetime.time):
            raise TypeError()
        self.default_due_time = default_due_time

        if section_group is None:
            section_group = "Default Section Group"
        self.section_group = section_group

    def copy(self, other):
        self.section_number = other.section_number
        self.default_due_time = other.default_due_time
        self.section_group = other.section_group

    def __str__(self):
        time_str = self.default_due_time.strftime(
            ClassSection.DUE_TIME_DISPLAY_FORMAT)
        section_padding = len(str(ClassSection.max_section_num))
        section_str = f"{self.section_number:>{section_padding}}"
        return (f"Section {section_str} - "
                f"Default Due Time: {time_str} - "
                f"Group: {self.section_group}")

    @classmethod
    def from_json(cls, section_json):
        section_number = section_json["section_number"]
        default_due_time_str = section_json["default_due_time"]
        default_due_time = (datetime.datetime.strptime(
            default_due_time_str,
            ClassSection.DUE_TIME_STORAGE_FORMAT).astimezone(tz=None).time())
        # Section Groups were added later, so do a safer get to avoid KeyError
        section_group = section_json.get("section_group")
        return ClassSection(section_number, default_due_time, section_group)

    def to_json(self):
        time_str = self.default_due_time.strftime(
            ClassSection.DUE_TIME_STORAGE_FORMAT)
        return {
            "section_number": self.section_number,
            "default_due_time": time_str,
            "section_group": self.section_group
        }


class TA:
    def __init__(self, netid, queue_name):
        self.netid = netid
        self.queue_name = queue_name

    def __repr__(self):
        return (f"TA(netid={self.netid}, queue_name={self.queue_name})")

    @classmethod
    def from_json(cls, ta_json):
        netid = ta_json["netid"]
        queue_name = ta_json["queue_name"]
        return TA(netid, queue_name)

    def to_json(self):
        return {"netid": self.netid, "queue_name": self.queue_name}


class SubmissionFlag(enum.Flag):
    NO_SUBMISSION = enum.auto()
    OK = enum.auto()
    BAD_ZIP_URL = enum.auto()
    DIFF_PARTS = enum.auto()


class Submission(Iterable):
    # Implement the iterator interface so the message can be updated
    # Throughout the grader popup's lifetime.
    def __iter__(self):
        self.current_line = 0
        return self

    def __next__(self):
        if self.current_line < len(self.msg):
            line = self.msg[self.current_line]
            self.current_line += 1
            return line
        else:
            raise StopIteration

    def __eq__(self, other):
        return self.student == other.student and self.lab == other.lab

    def get_part_identifier(self, part):
        """Some parts are not named, use ID in that case"""
        if part["name"]:
            return part["name"]
        return part["id"]

    def update_part(self, part, part_index):
        self.response["parts"][part_index] = part

        self.construct_submission()

    def construct_submission(self):
        # An assignment could have NO_SUBMISSION meaning it was late.
        # But students may have exceptions so this code is reached after picking
        # a submission after the due date. Remove the flag.
        self.flag &= ~SubmissionFlag.NO_SUBMISSION

        # Calculate score
        self.response["score"] = 0
        self.response["max_score"] = 0
        for part in self.response["parts"]:
            if part["code"] != Zybooks.NO_SUBMISSION:
                self.response["score"] += part["score"]
                self.response["max_score"] += part["max_score"]

        # Concatenate test results
        # There is a small chance that the test results may have changed
        # between student submissions, so it is best to recalculate every time.
        lines = []
        for part in self.response["parts"]:
            if part["code"] != Zybooks.NO_SUBMISSION:
                lines.append({
                    "name":
                    f"{self.get_part_identifier(part)} {part['score']}/{part['max_score']}",
                    "tests": part["tests"]
                })
            else:
                lines.append({
                    "name":
                    f"{self.get_part_identifier(part)} (No Submission)",
                    "tests": []
                })

        self.test_results = lines

        self.files_directory = self.read_files(self.response)

        self.create_submission_string(self.response)
        self.latest_submission = self.get_latest_submission(self.response)

        if "diff_parts" in self.lab.options:
            self.flag |= SubmissionFlag.DIFF_PARTS

    def __init__(self, student, lab, response):
        self.student = student
        self.lab = lab
        self.flag = SubmissionFlag.OK
        self.latest_submission = "No Submission"
        self.files_directory = ""

        # For storing compilation errors
        self.__stderr = ""

        # Save the response to be potentially updated later
        self.response = response

        # Only grade if student has submitted
        if self.response["code"] is Zybooks.NO_SUBMISSION:
            self.flag = SubmissionFlag.NO_SUBMISSION
            self.msg = [
                f"{self.student.full_name} - {self.lab.name}",
                "",
                "No submission before the due date.",
                "If the student has an exception, pick a submission to grade.",
            ]
            return

        # A list of test results for each part
        self.test_results = []

        self.construct_submission()

    def get_latest_submission(self, response) -> str:
        latest = None
        for part in response["parts"]:
            if part["code"] is Zybooks.NO_SUBMISSION:
                continue

            t = time.strptime(part["date"], "%I:%M %p - %m-%d-%Y")
            if not latest or time.mktime(latest) < time.mktime(t):
                latest = t

        if not latest:
            return ""
        return time.strftime("%I:%M %p - %m-%d-%Y", latest)

    def create_submission_string(self, response):
        msg = [f"{self.student.full_name} - {self.lab.name}", ""]

        longest_name = max(len(part["name"]) for part in response["parts"])

        for part in response["parts"]:
            if part["code"] == Zybooks.NO_SUBMISSION:
                msg.append(f"{part['name']:4} No Submission")
            else:
                score = f"{part['score']}/{part['max_score']}"

                if part["name"]:
                    msg.append(
                        f"{part['name']:{longest_name}}  {score:7}  {part['date']}"
                    )
                else:
                    msg.append(f"{score:8} {part['date']}")

                if part["code"] == Zybooks.COMPILE_ERROR:
                    msg[-1] += f" [Compile Error]"

        msg.append("")
        msg.append(f"Total Score: {response['score']}/{response['max_score']}")

        self.msg = msg

    def read_files(self, response):
        zy_api = Zybooks()
        tmp_dir = utils.create_tempdir()

        # Look through each part
        for part in response["parts"]:
            if part["code"] == Zybooks.NO_SUBMISSION:
                continue

            zip_file = zy_api.get_submission_zip(part["zip_url"])

            # Sometimes the zip file URL reported by zyBooks is invalid. Not sure if this
            # is an error with Amazon (the host) or zyBooks but in this rare case, just skip
            # the file. Also flag this Submission as having missing file(s).
            if zip_file == Zybooks.ERROR:
                self.flag |= SubmissionFlag.BAD_ZIP_URL
                continue

            # TODO: Can the name be removed from the file itself?
            files = utils.extract_zip(zip_file)

            # Write file to subdirectory in temporary directory
            part_directory = os.path.join(tmp_dir,
                                          self.get_part_identifier(part))
            os.makedirs(part_directory)
            for file_name in files.keys():
                with open(os.path.join(part_directory, file_name),
                          "w") as source_file:
                    source_file.write(files[file_name])

        return tmp_dir

    @utils.suspend_curses
    def show_files(self):
        if self.flag & SubmissionFlag.NO_SUBMISSION:
            # Can't show popup here because curses is disabled...
            return
        user_editor = preferences.get("editor")
        editor_path = preferences.EDITORS[user_editor]

        files = utils.get_source_file_paths(self.files_directory)

        # Terminal-based editors
        if user_editor in {"Vim", "Emacs", "Nano", "Less"}:
            files.sort()

            if user_editor == "Vim":
                # Use "-p" to open in tabs
                cmds = [
                    "--cmd",
                    "set tabpagemax=100",
                    "--cmd",
                    "set laststatus=2",
                    "--cmd",
                    "set number",
                ]
                subprocess.run([editor_path, "-p"] + files + cmds,
                               stderr=subprocess.DEVNULL)
            elif user_editor == "Emacs":
                # Force terminal with "-nw"
                subprocess.run([editor_path, "-nw"] + files,
                               stderr=subprocess.DEVNULL)
            else:
                subprocess.run([editor_path] + files, stderr=subprocess.DEVNULL)

        # Graphical editors
        else:
            subprocess.run([editor_path] + files,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)

    def do_resume_code(self, process):
        if process:
            curses.endwin()
            SharedData.RUNNING_CODE = True
            process.send_signal(signal.SIGCONT)
            print("Resumed student code")
            print(
                "#############################################################")
            return True
        return False

    def compile_and_run_code(self, use_gdb):
        events = ui.get_events()

        if self.do_resume_code(SharedData.running_process):
            stopped = self.wait_on_child(SharedData.running_process)
        else:
            # Get path to executable
            executable = self.compile_code()
            if not executable:
                return False  # Could not compile code

            SharedData.RUNNING_CODE = True
            stopped = self.run_code(executable, use_gdb)

        if not stopped:
            SharedData.running_process = None

            SharedData.RUNNING_CODE = False
            print(
                "\n#############################################################"
            )
            print("Press ENTER to continue")
            input()

        else:
            print(
                "\n#############################################################"
            )
            print("Paused student code\n")

        curses.initscr()
        curses.flushinp()
        events.clear_event_queue()
        curses.doupdate()
        return True

    def pick_part(self, title="Choose a part", pick_all=False):
        window = ui.get_window()
        part_names = [self.get_part_identifier(x) for x in self.lab.parts]

        popup = ui.layers.ListLayer(title, popup=True)
        if pick_all:
            popup.add_row_text("Pick all latest")
        for part in part_names:
            popup.add_row_text(part)
        window.run_layer(popup)
        if popup.canceled:
            return None

        if pick_all:
            return popup.selected_index() - 1
        return popup.selected_index()

    def save_stderr(self, stderr):
        self.__stderr = stderr

    def view_stderr(self):
        utils.view_string(self.__stderr, "compile-error")

    def compile_code(self):
        # Use a separate tmp dir to avoid opening the binary in a text editor
        tmp_dir = utils.create_tempdir()
        executable_name = os.path.join(tmp_dir, "run")

        root_dir = self.files_directory
        if len(self.lab.parts) > 1:
            part = self.pick_part()
            if part == ui.GO_BACK:
                return False

            root_dir = os.path.join(
                self.files_directory,
                self.get_part_identifier(self.lab.parts[part]))

        files = utils.get_source_file_paths(root_dir)

        source_files = [f for f in files if f.endswith(".cpp")]
        compile_command = ["g++", "-g", "-o", executable_name, f"-I{root_dir}"
                           ] + source_files

        compile_exit = subprocess.run(compile_command,
                                      encoding="utf-8",
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE)
        if compile_exit.returncode != 0:
            self.save_stderr(compile_exit.stderr)
            return False

        # Compiled successfully, run code
        return os.path.abspath(executable_name)

    def wait_on_child(self, child):
        while child.poll() is None:
            time.sleep(0.1)
            if not SharedData.RUNNING_CODE:
                break

        # If the running process still exists
        if SharedData.running_process and SharedData.running_process.poll(
        ) is None:
            return True

        return False

    def run_code(self, executable, use_gdb):
        events = ui.get_events()
        events.clear_event_queue()
        curses.endwin()

        print(chr(27) + "[2J", end="")  # Clear the terminal
        print("#############################################################")
        print(f"Running {self.student.full_name}'s code")
        print("CTRL+C to terminate")
        print("CTRL+Z to stop (pause)")
        # if not use_gdb:
        # print("ALT+ENTER when running code to use gdb")
        print("#############################################################\n")

        if use_gdb:
            process = subprocess.Popen(["gdb", executable],
                                       stderr=subprocess.DEVNULL)
        else:
            process = subprocess.Popen([executable], stderr=subprocess.DEVNULL)
        SharedData.running_process = process

        # Return indicator if child terminated or stopped
        return self.wait_on_child(process)

    def diff_parts(self):
        use_browser = preferences.get("browser_diff")

        if len(self.lab.parts) < 2:
            return "Not enough parts to diff"
        elif len(self.lab.parts) > 2:
            index = self.pick_part("Pick the first part")
            if index is ui.GO_BACK:
                return
            part_a = self.lab.parts[index]

            index = self.pick_part("Pick the second part")
            if index is ui.GO_BACK:
                return
            part_b = self.lab.parts[index]
        else:
            # Assume for 2 part labs to diff those two parts
            part_a = self.lab.parts[0]
            part_b = self.lab.parts[1]

        path_a = os.path.join(self.files_directory,
                              self.get_part_identifier(part_a))
        path_b = os.path.join(self.files_directory,
                              self.get_part_identifier(part_b))

        # Only diff if both have submissions
        if not (os.path.exists(path_a) and os.path.exists(path_b)):
            return "No submission for at least one part"

        part_a_paths = [os.path.join(path_a, f) for f in os.listdir(path_a)]
        part_b_paths = [os.path.join(path_b, f) for f in os.listdir(path_b)]

        diff = utils.make_diff_string(part_a_paths, part_b_paths, path_a,
                                      path_b, use_browser)
        utils.view_string(diff, "parts.diff", use_browser)
