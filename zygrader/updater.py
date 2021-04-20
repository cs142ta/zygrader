"""Updater: To auto-update zygrader during runtime"""
import subprocess
import sys
from distutils.version import LooseVersion

import requests

from zygrader.config.shared import SharedData

REPO_NAME = "cs142ta/zygrader"
API_URL = f"https://api.github.com/repos/{REPO_NAME}/tags"


def get_tags_list() -> dict:
    """Get list of tags for zygrader from GitHub"""
    r = requests.get(API_URL)
    if not r.ok:
        return {}
    return r.json()


def install_from_url(url: str):
    """Install the new version of zygrader from the GitHub tarball url"""
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--user", "--upgrade",
            "--no-cache-dir", url
        ])
    except subprocess.CalledProcessError:
        print("Failed to update zygrader. Exiting")
        print()
        sys.exit()


def uninstall_zygrader():
    """Uninstall zygrader before downgrading"""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "uninstall", "-y", "zygrader"])
    except subprocess.CalledProcessError:
        print("Failed to uninstall zygrader. Exiting")
        print()
        sys.exit()


def get_latest_version():
    """Check the zygrader git repo tags for a new version"""
    tags = get_tags_list()
    if not tags:
        return SharedData.VERSION

    latest = LooseVersion(tags[0]["name"])
    if latest > SharedData.VERSION:
        return latest

    return SharedData.VERSION


def update_zygrader(latest_version):
    """Download zygrader from the git repository and update it"""
    print()
    print(f"Updating zygrader [{SharedData.VERSION} -> {latest_version}]")
    print()

    # Get tarball URL from github
    tags = get_tags_list()
    if not tags:
        print("Failed to download latest version.")
        sys.exit()

    tag = tags[0]
    install_from_url(tag["tarball_url"])

    print("zygrader successfully updated. Please run zygrader again.")
    print()


def install_version(version: str):
    """Specify a version to install from pip"""
    tags = get_tags_list()
    if not tags:
        print(f"Failed to download version {version}.")
        sys.exit()

    for tag in tags:
        if tag["name"] == version:
            uninstall_zygrader()
            install_from_url(tag["tarball_url"])

            print(
                f"zygrader {version} successfully installed. Please run zygrader again."
            )
            print()
            sys.exit()

    print(f"zygrader {version} does not exist. Exiting.")
