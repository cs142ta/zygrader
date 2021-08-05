# zygrader
_Zygrader is a Python 3 ncurses tool to facilitate grading student submissions on the zyBooks online programming textbook system. It has been tested on Linux._

Zygrader is a tool developed for the BYU CS142 Introduction to Computer Programming teaching assistants by [Nathan Craddock](https://github.com/natecraddock),
and others have since contributed to the project. Rather than navigating the slow zyBooks website to review student code,
zygrader assists the grader in downloading, running, reviewing, and comparing student code.

Contents:
- [Installation](#installation)
- [User Manual](#user-manual)
- [Development](#development)
- [Style Guide](#style-guide)
- [Code Notes](#code-notes)

# Installation

Zygrader is installed through `pip` for each user who each have their own local configuration stored at `~/.config/zygrader/config.json`. Each user
accesses a shared folder that can be stored at any location.

To install zygrader run the following:

```
python3 -m pip install https://github.com/cs142ta/zygrader/archive/master.zip
```

Zygrader is installed to `~/.local/bin/zygrader`. If you do not already have
`~/.local/bin` on your PATH then run the following:

```
echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.bashrc
```

The following may also be run if you would like to use zygrader over ssh.

```
echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.bash_profile
```

To start zygrader run the following in a terminal

```
zygrader
```

If you would rather not modify your PATH you can run zygrader through python

```
python3 -m zygrader
```

To uninstall zygrader run the following:

```
python3 -m pip uninstall zygrader
```

## Setup

Zygrader will not run without setting the data directory.
Each user will need to point zygrader to the shared folder by running

```
zygrader --set-data-dir [path]
```

Once it is set, it is stored in your user configuration.

To create the shared data folder (always named `zygrader_data`), run zygrader with:

```
zygrader --init-data-dir [path]
```

For example

```
zygrader --init-data-dir /home/shared/programming/
```

will create the directory `/home/shared/programming/zygrader_data/`.

# User Manual
As zygrader is a terminal application, all controls are entered with the keyboard.

The arrow keys can be used to navigate through lists of options, with enter to select.
Some parts of the interface also accept text input.

There is a vim mode which maps the `hjkl` keys to the arrow keys, with `i` and `ESC` to toggle between insert and normal mode.

# Development

Because zygrader is installed with `pip`, running `import zygrader` will first check for the system-wide install. This causes problems
for developing zygrader. To solve these issues, virtual environments are used.

Install virtualenv
```
python3 -m pip install --user virtualenv
```

Create the virtual environment
```
python3 -m venv ~/.virtualenvs/zygrader
```

Enter the virtual environment
```
source ~/.virtualenvs/zygrader/bin/activate
```

You must first install zygrader in _develop mode_ before running from source. Run the following from the zygrader repository (installing needed deps).
```
pip3 install requests yapf
pip3 install -e .
```

zygrader can be run directly from the main file, or as a module during development (supports alias)
```
python3 zygrader/main.py
python3 -m zygrader
```

To exit the virtual environment
```
deactivate
```

Each time you want to test the develop version you must be in the virtual environment. This prevents conflicts between the local and installed versions of zygrader.

Changes can be pushed to the git repository to share between developers. Zygrader checks GitHub for new tags when
it starts. If a commit has been tagged with a higher version number than the current version it will be downloaded and installed.

## Pushing Updates
When enough features are ready, a major release can be sent to users. A major release includes:
* updating the changelog `zygrader/config/changelog.txt`
* adding any needed versioning code in `zygrader/config/versioning.py`
* showing the changelog message in the versioning code (see previous versions)
* and update the version number in `zygrader/config/shared.py`.

If a critical bugfix release needs to be released (of the form `X.X.1`, `X.X.2`, ...), then the only needed change
is to update the version number in `zygrader/config/shared.py`.

#### Tagging
After making necessary code changes, run `push_update.sh` with the new version number as the argument to tag and push the tag to the repository. After this runs successfully, any user who starts zygrader
will see it automatically download and update to the latest version. The argument to `push_update.sh` should match the
VERSION variable in `shared.py` exactly.

**Example:** _pushing a major version 3.6.0_
```
./push_update.sh 3.6.0
```

**Example:** _pushing a buxfix update to version 3.5.0_
```
./push_update.sh 3.5.1
```

## Environment (VSCode)
We strongly suggest using Visual Studio Code as a development enviromnent. The minimum recommended settings are:
* Extensions
  * Python (Microsoft) - _Python language support_
  * Pylance (Microsoft) - _Improved Python language server_
* Configuration (workspace)
  * editor.formatOnSave: true
  * python.formatting.provider: "yapf"

We use `yapf` for auto code formatting. The above settings will enable auto code formatting
on save to keep everyone's edits consistent. If you want to run formatting on all
files, run `find . -name "*.py" -exec python3 -m yapf -i {} \;`.


After creating a virtual environment, you must select that as the python interpreter in VSCode for development. Enter the
command `Python: Select Interpreter` and choose the virtual environment. It searches the project folder and `~/.virtualenvs` for python environments so the venv may be created where desired.

### Debugging
VSCode can debug zygrader by including something similar to the following in `launch.json`

```
    "configurations": [
        {
            "name": "zygrader",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/zygrader/main.py",
            "console": "integratedTerminal"
        }
    ]
```

## Style Guide
We use yapf for indentation and spacing, but we have a few other conventions
that can't be enforced by yapf.

### Naming
* Variables and functions are in `snake_case`
* Classes are in `UpperCamelCase`

### Typing
Python is a dynamically-typed language, but it supports type hints. These are only used by text editors and IDEs
to make code easier to read and improve autocomplete. Hints should be used where reasonable.
* Function definitions are the most important place for type hints because they define the interface to that unit of code.
* Members of classes can be given type hints.
* Variables are rarely (never?) given type hints. It is usually inferred from the first use.
* Function return values should be given type hints when reasonable. Use the typing module to union types where needed.

For example
```python
class A:
  pass

class Test:
  # Function parameters should be typed
  def __init__(self, name: str, ob: A):

    # Types are inferred from parameters here
    self.name = name
    self.ob = ob

    # The type is inferred here
    self.id = 5

    # This type is explicit because we assign the window later
    self.window: Window = None

    # Use the typing module to specify more advanced types
    self.args: typing.List[Argument] = []

  def set_window(self, window: Window):
    self.window = window
```

The code is not fully hinted, but most new code is. New code is highly encouraged to be hinted where reasonable.
Cleanup commits that add hints are also welcome.

### Docstrings
* Each file should have a dostring on the first line.
* We try to use docstrings on general utility functions and methods. Functions used in one place for the purpose of simplifying logic do
not need docstrings as usually the name and parameters are enough explanation.

# Code Notes

## zyBooks API - `zybooks.py`
The zyBooks API is a small wrapper around some zyBooks webpage-building requests. The [zyBooks website](https://learn.zybooks.com/) is created with the Ember.js framework, which builds the page locally with JSON responses. If anything breaks in zygrader in the future, it will be the wrapper around their API (which isn't publicly documented).

To find the API urls, open zyBooks in a browser with the network traffic inspector open. An example will be given to locate the URL for downloading a student's submissions. Find the *Lab Statistics and submissions* box on the page and pick a student from the list. At the time of writing, two identical requests are sent to `https://zyserver.zybooks.com/v1/zybook/[BOOK CODE]/programming_submission/[SECTION CODE]/user/[USER ID]?auth_token=XXXX`. The `BOOK CODE` is the name of the book, for example BYUCS142Spring2020. The `SECTION CODE` is a number unique to the page (section) in zyBooks. Finally, the `USER ID` is the user's id. (The function `zybooks.py get_roster()` downloads the JSON for all of the students in a book).

If anything in zyBooks breaks regarding the zyBooks integration (downloading submissions, logging in), the first thing I would do is check if their API urls have changed.

ZyBooks submission responses contain links to zip files stored on Amazon's AWS.
