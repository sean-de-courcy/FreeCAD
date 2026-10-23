# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Runs `make_generation.main()` inside FreeCADCmd for regen_gen0.sh (FreeCAD-CH ops#418).

make_generation.py does nothing when FreeCADCmd runs it as a file (its main() sits under
`if __name__ == "__main__"`), so regen_gen0.sh runs this wrapper instead. Environment:

    FREECAD_COMPAT_OUT      the generation's folder (gen<k>), as make_generation.py reads it
    FREECAD_COMPAT_MODELS   optional, the models to build (space separated); empty: all of them
    FREECAD_COMPAT_RESULT   a file this writes: "OK" or the traceback

It refuses to run unless FREECAD_USER_HOME is an absolute path of an existing folder that
FreeCAD really uses (a missing or relative one makes FreeCAD fall back to the user's real settings,
and it rewrites them on exit). It ends with os._exit, as the old hand step did: no settings are
written and no shutdown hang.
"""

import os
import sys
import traceback


def _fail(message):
    sys.stderr.write(f"regen_gen0_drive: {message}\n")
    sys.stderr.flush()
    os._exit(2)


def _under(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _checkUserHome():
    home = os.environ.get("FREECAD_USER_HOME", "")
    drive = os.path.splitdrive(home)[0]
    if not home or not os.path.isabs(home) or (sys.platform == "win32" and not drive):
        _fail(f"FREECAD_USER_HOME='{home}' is not an absolute path (with its drive)")
    if not os.path.isdir(home):
        _fail(f"FREECAD_USER_HOME='{home}' does not exist")
    import FreeCAD

    used = FreeCAD.getUserConfigDir()
    if not _under(used, home):
        _fail(f"FreeCAD runs on {used}, not on FREECAD_USER_HOME='{home}'")


def _run():
    result = os.environ.get("FREECAD_COMPAT_RESULT")
    if not result:
        _fail("set FREECAD_COMPAT_RESULT")
    _checkUserHome()
    try:
        from PartDesignTests.Compat import make_generation, models

        unknown = [n for n in os.environ.get("FREECAD_COMPAT_MODELS", "").split() if n not in models.MODELS]
        if unknown:
            raise RuntimeError(
                f"this build has no model {unknown}: the build is older than the checkout's "
                f"gen0, or the name is misspelt"
            )
        make_generation.main()
        text = "OK\n"
    except BaseException:
        text = traceback.format_exc()
    with open(result, "w", encoding="utf-8") as fh:
        fh.write(text)
    sys.stdout.flush()
    os._exit(0)


_run()
