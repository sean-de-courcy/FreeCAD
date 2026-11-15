# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 7).

"""A warning when FreeCAD's own folders lie inside the team folder (FreeCAD-CH, folder sync item 7).

notes/folder-sync.md 2.5 and section 3 item 7. The settings, data, cache and macro folders belong
to one computer; inside the team folder, Syncthing would copy them to the others. FreeCAD-CH warns
once at start, and when the team folder is set while it runs.

Each test runs a FreeCADCmd child whose FREECAD_USER_HOME is a new folder, inside or outside a
designed team folder made in a temporary folder."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import FreeCAD

WARNING = "is inside the team folder"

CHILD_SCRIPT = r"""
import os
import FreeCAD
team = os.environ.get("FCCH_SET_TEAM", "")
if team:
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document").SetString("TeamFolder", team)
    FreeCAD.saveParameter()
print("FCCH CHILD DONE", flush=True)
os._exit(0)
"""


def _freecadCmd():
    names = ("FreeCADCmd.exe", "FreeCADCmd") if sys.platform == "win32" else ("FreeCADCmd",)
    if os.path.basename(sys.executable).lower().startswith("freecadcmd"):
        return sys.executable
    for folder in ("bin", "MacOS", ""):
        for name in names:
            path = os.path.join(FreeCAD.getHomePath(), folder, name)
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("FreeCADCmd next to " + FreeCAD.getHomePath())


class TestSettingsInTeamFolder(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fcch-settings-")
        self.team = os.path.join(self.root, "Team")
        os.mkdir(self.team)
        self.script = os.path.join(self.root, "child.py")
        with open(self.script, "w", encoding="utf-8") as fh:
            fh.write(CHILD_SCRIPT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def runChild(self, home, setTeam=""):
        """The child's log. `setTeam` is a team folder the child sets (and saves) while it runs."""
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ)
        env["FREECAD_USER_HOME"] = home
        env["FCCH_SET_TEAM"] = setTeam
        result = subprocess.run(
            [_freecadCmd(), self.script],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.root,
            timeout=600,
        )
        text = result.stdout.decode("utf-8", errors="replace")
        self.assertIn("FCCH CHILD DONE", text, text[-3000:])
        return text

    def testSetWhileRunningThenAtStart(self):
        """Setting the team folder around the running FreeCAD's settings warns; the next start
        warns again, once per folder."""
        home = os.path.join(self.team, "home")
        first = self.runChild(home, setTeam=self.team)
        self.assertIn(WARNING, first, first[-3000:])
        self.assertIn("settings folder", first, first[-3000:])
        second = self.runChild(home)
        self.assertIn(WARNING, second, second[-3000:])
        lines = [line for line in second.splitlines() if WARNING in line and "settings folder" in line]
        self.assertEqual(len(lines), 1, second[-3000:])

    def testHomeOutsideTheTeamFolder(self):
        """A home beside the team folder: no warning, when set or at the next start."""
        home = os.path.join(self.root, "home")
        first = self.runChild(home, setTeam=self.team)
        self.assertNotIn(WARNING, first, first[-3000:])
        second = self.runChild(home)
        self.assertNotIn(WARNING, second, second[-3000:])

    def testNoTeamFolder(self):
        """No team folder set: no warning, even with the home in the folder that would be it."""
        text = self.runChild(os.path.join(self.team, "home"))
        self.assertNotIn(WARNING, text, text[-3000:])
