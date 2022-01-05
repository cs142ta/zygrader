"""Lock files are created to prevent multiple people from grading an assignment simultaneously."""

import collections
import csv
import os
import time
from datetime import datetime, timedelta
from typing import Union

from zygrader import logger, utils
from zygrader.config.shared import SharedData

from .model import Lab, Student


def get_lock_files():
    """Return a list of all lock files"""
    return [
        l for l in os.listdir(SharedData.get_locks_directory())
        if l.endswith(".lock")
    ]


def get_lock_log_path():
    """Return path to lock log file"""
    return os.path.join(SharedData.get_logs_directory(), "locks_log.csv")


def log(name, lab, event_type, lock="LOCK"):
    """Logging utility for lock files

    This logs when each lab is locked and unlocked,
    along with when and by whom.
    This also logs to the shared log file
    """

    lock_log = get_lock_log_path()
    # Get timestamp
    timestamp = datetime.now().isoformat()

    with open(lock_log, "a", newline='') as _log:
        # Use csv to properly write names with commas in them
        csv.writer(_log).writerow(
            [timestamp, event_type, name, lab,
             utils.get_username(), lock])

    logger.log(f"{name},{lab},{lock},{event_type}")


def was_recently_locked(student: Student,
                        lab: Union[Lab, None],
                        netid: str,
                        range: int = 10) -> tuple:
    """
    Check the lock log for a previous lock for the given name
    and lab. The range is in minutes. If the lock was made by the same ta as
    the current grader, then ignore the lock.
    If lab is None, then Email locks are checked
    """
    lock_log = get_lock_log_path()

    oldest_allowed = datetime.now() - timedelta(minutes=range)
    Row = collections.namedtuple("Row", ["time", "student", "lab", "ta"])

    # Collect all rows within the time range
    rows = []
    if not os.path.isfile(lock_log):
        return False, None, None

    with open(lock_log, "r") as log:
        for line in csv.reader(log):
            row = Row(datetime.fromisoformat(line[0]), line[2], line[3],
                      line[4])

            if row.time > oldest_allowed:
                rows.append(row)

    # No one was graded in the time range
    if not rows:
        return False, None, None

    # Check if the student and lab are in the time range
    student_name = student.get_unique_name()
    lab_name = lab.get_unique_name() if lab else None
    for row in reversed(rows):
        # ignore labs if only checking emails
        if row.student == student_name and (not lab or row.lab == lab_name):

            # this was locked by the same TA who recently locked it,
            # so ignore the lock.
            if row.ta == netid:
                continue

            ts = datetime.strftime(row.time, "%I:%M %p - %m-%d-%Y")
            return True, ts, row.ta

    return False, None, None


def get_lock_file_path(student: Student, lab: Lab = None):
    """Return path for lock file"""
    username = utils.get_username()

    # We can safely store both lab+student and lab locks in the
    # Same directory
    if lab:
        lab_name = lab.get_unique_name()
        student_name = student.get_unique_name()
        lock_path = f"{username}.{lab_name}.{student_name}.lock"
    else:
        student_name = student.get_unique_name()
        lock_path = f"{username}.{student_name}.lock"

    return os.path.join(SharedData.get_locks_directory(), lock_path)


def is_locked(student: Student, lab: Lab = None):
    """Check if a submission is locked for a given student and lab"""
    # Try to match this against all the lock files in the directory
    lock_path = os.path.basename(get_lock_file_path(student, lab))
    lock_path_end = ".".join(lock_path.split(".")[1:])

    for lock in get_lock_files():
        # Strip off username
        lock = ".".join(lock.split(".")[1:])

        if lock == lock_path_end:
            return True

    return False


def get_locked_netid(student: Student, lab: Lab = None):
    """Return netid of locked submission"""
    # Try to match this against all the lock files in the directory
    lock_path = os.path.basename(get_lock_file_path(student, lab))
    lock_path_end = ".".join(lock_path.split(".")[1:])

    for lock in get_lock_files():
        if lock.endswith(lock_path_end):
            return lock.split(".")[0]

    return ""


def lock(student: Student, lab: Lab = None):
    """Lock the submission for the given student (and lab if given)

    Locking is done by creating a file with of the following format:
        username.lab.student.lock
    Where username is the grader's username.
    These files are used to determine if a submission is being graded.
    """
    lock = get_lock_file_path(student, lab)

    open(lock, "w").close()

    if lab:
        log(student.get_unique_name(), lab.get_unique_name(), "LAB")
    else:
        log(student.get_unique_name(), "N/A", "EMAIL")


def unlock(student: Student, lab: Lab = None):
    """Unlock the submission for the given student and lab"""
    lock = get_lock_file_path(student, lab)

    # Only remove the lock if it exists
    if os.path.exists(lock):
        os.remove(lock)
    if lab:
        log(student.get_unique_name(), lab.get_unique_name(), "LAB", "UNLOCK")
    else:
        log(student.get_unique_name(), "N/A", "EMAIL", "UNLOCK")


def unlock_all_labs_by_grader(username: str):
    """Remove all lock files for a given grader"""
    # Look at all lock files
    for lock in get_lock_files():
        lock_parts = lock.split(".")

        # Only look at the lock files graded by the current grader
        if lock_parts[0] == username:
            os.remove(os.path.join(SharedData.get_locks_directory(), lock))

    logger.log("All locks under the current grader were removed",
               logger.WARNING)


def unlock_all_labs():
    """Remove all locks"""
    for lock in get_lock_files():
        os.remove(os.path.join(SharedData.get_locks_directory(), lock))


def remove_lock_file(_file):
    """Remove a specific lock file (not logged to locks_log.csv)"""
    locks_directory = SharedData.get_locks_directory()

    os.remove(os.path.join(locks_directory, _file))

    logger.log("lock file was removed manually", _file, logger.WARNING)
