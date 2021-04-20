"""Shared Data: Data shared between all users of zygrader"""
import json
import os
from distutils.version import LooseVersion

from . import preferences


class SharedData:
    # Zygrader version
    VERSION = LooseVersion("5.9.3")

    # Current class code (shared)
    # Can be overridden on a user level
    CLASS_CODE = ""

    # The zygrader data exists in a hidden folder created by the --init-data-dir flag
    # This folder contains the shared configuration and the folders for each
    # semester/class that zygrader has been setup for.
    ZYGRADER_DATA_DIRECTORY = ""
    CLASS_DIRECTORY = ""
    LOGS_DIRECTORY = "logs"
    DATA_DIRECTORY = ".data"
    CACHE_DIRECTORY = ".cache"
    LOCKS_DIRECTORY = ".locks"
    FLAGS_DIRECTORY = ".flags"

    # Set to true once the data paths have been initialized
    DIRECTORIES_INITIALIZED = False

    STUDENTS_FILE = "students.json"
    LABS_FILE = "labs.json"
    CANVAS_MASTER_FILE = "canvas_master.csv"
    CLASS_SECTIONS_FILE = "class_sections.json"
    TAS_FILE = "tas.json"

    # This is a global to represent if student code is being executed
    RUNNING_CODE = False
    running_process = None

    SHARED_CONFIG_PATH = ""

    # Global arrays
    STUDENTS = []
    LABS = []
    CLASS_SECTIONS = []
    TAS = []

    @classmethod
    def initialize_shared_data(cls, shared_data_path):
        if not os.path.exists(shared_data_path):
            print("The shared data folder does not exist")
            return False

        cls.ZYGRADER_DATA_DIRECTORY = shared_data_path
        cls.SHARED_CONFIG_PATH = os.path.join(shared_data_path, "config")

        shared_config = cls.get_shared_config()
        if not shared_config:
            print("No shared configuration exists")
            return False

        # Initialize current class
        current_class_code = cls.get_current_class_code()

        if current_class_code:
            cls.initialize_class_data(current_class_code)

        cls.DIRECTORIES_INITIALIZED = True

        return True

    @classmethod
    def initialize_class_data(cls, class_code):
        cls.CLASS_CODE = class_code
        cls.CLASS_DIRECTORY = os.path.join(cls.ZYGRADER_DATA_DIRECTORY,
                                           class_code)

    @classmethod
    def get_shared_config(cls):
        if not os.path.exists(cls.SHARED_CONFIG_PATH):
            return False

        config = {}
        with open(cls.SHARED_CONFIG_PATH, "r") as _file:
            config = json.load(_file)

        return config

    @classmethod
    def write_shared_config(cls, config):
        with open(cls.SHARED_CONFIG_PATH, "w") as _file:
            json.dump(config, _file)

    @classmethod
    def get_config_directory(cls, config_type):
        """Return path of config directory. Create directory if it does not exist"""
        _path = os.path.join(cls.CLASS_DIRECTORY, config_type)
        if not os.path.exists(_path):
            os.makedirs(_path)
        return _path

    @classmethod
    def get_logs_directory(cls):
        return cls.get_config_directory(cls.LOGS_DIRECTORY)

    @classmethod
    def get_data_directory(cls):
        return cls.get_config_directory(cls.DATA_DIRECTORY)

    @classmethod
    def get_cache_directory(cls):
        return cls.get_config_directory(cls.CACHE_DIRECTORY)

    @classmethod
    def get_locks_directory(cls):
        return cls.get_config_directory(cls.LOCKS_DIRECTORY)

    @classmethod
    def get_flags_directory(cls):
        return cls.get_config_directory(cls.FLAGS_DIRECTORY)

    @classmethod
    def is_initialized(cls):
        return cls.DIRECTORIES_INITIALIZED

    @classmethod
    def get_student_data(cls):
        return os.path.join(cls.get_data_directory(), cls.STUDENTS_FILE)

    @classmethod
    def get_labs_data(cls):
        return os.path.join(cls.get_data_directory(), cls.LABS_FILE)

    @classmethod
    def get_canvas_master(cls):
        return os.path.join(cls.get_data_directory(), cls.CANVAS_MASTER_FILE)

    @classmethod
    def get_class_sections_data(cls):
        return os.path.join(cls.get_data_directory(), cls.CLASS_SECTIONS_FILE)

    @classmethod
    def get_ta_data(cls):
        return os.path.join(cls.get_data_directory(), cls.TAS_FILE)

    @classmethod
    def create_shared_data_directory(cls, data_path):
        """If no data directory exists, create it"""
        if not os.path.exists(data_path):
            os.makedirs(data_path)

        # Ensure the config file exists in the directory
        cls.SHARED_CONFIG_PATH = os.path.join(data_path, "config")
        if not os.path.exists(cls.SHARED_CONFIG_PATH):
            shared_config = {"class_code": "", "class_codes": []}
            cls.write_shared_config(shared_config)

    @classmethod
    def ensure_data_directory(cls, path):
        """Validate the given path to check if it is structured as a proper shared data directory."""

        # Check the path itself
        if not os.path.exists(path):
            return False

        cfg = cls.get_shared_config()
        if not cfg:
            return False

        return True

    @classmethod
    def get_class_codes(cls) -> list:
        config = cls.get_shared_config()
        return config["class_codes"]

    @classmethod
    def set_class_codes(cls, codes):
        config = cls.get_shared_config()
        config["class_codes"] = codes

        cls.write_shared_config(config)

    @classmethod
    def get_current_class_code(cls):
        override = preferences.get("class_code")
        if override and override != "No Override":
            return override
        config = cls.get_shared_config()
        return config["class_code"]

    @classmethod
    def setup_class_directory(cls, code):
        cls.initialize_class_data(code)

        if not os.path.exists(cls.CLASS_DIRECTORY):
            os.makedirs(cls.CLASS_DIRECTORY)

    @classmethod
    def set_current_class_code(cls, code):
        config = cls.get_shared_config()
        config["class_code"] = code

        # If the code is not in the list, add it
        if code not in config["class_codes"]:
            config["class_codes"].append(code)

        cls.setup_class_directory(code)
        cls.write_shared_config(config)

    @classmethod
    def add_class(cls, code):
        config = cls.get_shared_config()

        # Don't allow duplicates
        if code in config["class_codes"]:
            return

        cls.set_current_class_code(code)
