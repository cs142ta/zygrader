"""Logging utility functions for zygrader

These allow basic logging of data to a log.txt file in the logs directory
"""
import datetime
import os

from zygrader.config.shared import SharedData
from zygrader import utils

# Log types
INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"


def get_global_lock_path():
    return os.path.join(SharedData.get_logs_directory(), "log.txt")


def log(*args, type=INFO):
    """Log all arguments in a comma separated list with a type, username, and timestamp"""

    with open(get_global_lock_path(), "a") as _log:
        _log.write(
            f"{type},{utils.get_username()},{datetime.datetime.now().isoformat()},"
        )
        for item in args:
            _log.write(f"{item},")
        _log.write("\n")
