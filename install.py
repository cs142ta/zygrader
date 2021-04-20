"""Install.py

A module for installing the latest tagged release from GitHub.

Master is not always stable, so download and run this script instead
to download the latest stable release for a first-time install.
"""

import requests
import subprocess
import sys

REPO_NAME = "cs142ta/zygrader"
API_URL = f"https://api.github.com/repos/{REPO_NAME}/tags"


def get_tags_list() -> dict:
    """Get list of tags for zygrader from GitHub"""
    r = requests.get(API_URL)
    if not r.ok:
        return {}
    return r.json()


def install_from_url(url: str):
    """Install zygrader from the GitHub tarball url"""
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--user", "--no-cache-dir",
            url
        ])
    except subprocess.CalledProcessError:
        print("Failed to install zygrader. Exiting")


def install_zygrader():
    """ Install the most recent tagged release. """
    tags = get_tags_list()
    url = tags[0]["tarball_url"]
    install_from_url(url)


if __name__ == "__main__":
    install_zygrader()
