# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""VTK's messages reach FreeCAD's console (FreeCAD-CH, ops#382).

VTK's default output window on Windows (vtkWin32OutputWindow) opened a window on the desktop for
every VTK warning or error, e.g. vtkSmoothPolyDataFilter's "No data to smooth!" from FEM's
post-processing filters on empty data. Loading FEM now installs an output window that forwards
VTK's text to Base::Console.

The messages are caught on the console's stderr observer (fd 2), once with its error output on
and once off: with it off nothing may arrive, so text written to stderr by VTK itself (VTK's
default window elsewhere) doesn't count.
"""

import os
import tempfile
import unittest

import FreeCAD

SMOOTH_ERROR = b"No data to smooth!"


def _vtk():
    """vtkmodules' classes used here, or None without VTK's Python bindings."""
    if "BUILD_FEM_VTK_PYTHON" not in FreeCAD.__cmake__:
        return None
    try:
        from vtkmodules.vtkCommonCore import vtkOutputWindow
        from vtkmodules.vtkCommonDataModel import vtkPolyData
        from vtkmodules.vtkFiltersCore import vtkSmoothPolyDataFilter
    except ImportError:
        return None
    return vtkOutputWindow, vtkPolyData, vtkSmoothPolyDataFilter


def _caughtOnStderr(action, errors):
    """What the console's std observer writes to fd 2 during action(), with its error output
    on or off."""
    if "Console" not in FreeCAD.Console.GetObservers():
        raise unittest.SkipTest("no console observer to catch the message")
    status = FreeCAD.Console.GetStatus("Console", "Err")
    FreeCAD.Console.SetStatus("Console", "Err", errors)
    saved = os.dup(2)
    with tempfile.TemporaryFile() as caught:
        os.dup2(caught.fileno(), 2)
        try:
            action()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            FreeCAD.Console.SetStatus("Console", "Err", bool(status))
        caught.seek(0)
        return caught.read()


class TestVtkOutputWindow(unittest.TestCase):
    def setUp(self):
        if "BUILD_FEM_VTK" not in FreeCAD.__cmake__:
            self.skipTest("FEM without VTK")
        import Fem  # noqa: F401  (installs the output window)

        self.vtk = _vtk()
        if self.vtk is None:
            self.skipTest("no VTK Python bindings")
        vtkOutputWindow = self.vtk[0]
        window = vtkOutputWindow.GetInstance()
        if window.GetClassName() == "vtkWin32OutputWindow":
            # The window this test checks against: never open it on the desktop
            window.ShowWindowOff()

    def smoothNothing(self):
        _, vtkPolyData, vtkSmoothPolyDataFilter = self.vtk
        smooth = vtkSmoothPolyDataFilter()
        smooth.SetInputData(vtkPolyData())
        smooth.Update()

    def testInstalledWithFem(self):
        vtkOutputWindow = self.vtk[0]
        self.assertEqual(vtkOutputWindow.GetInstance().GetClassName(), "FemVtkOutputWindow")

    def testErrorReachesTheConsole(self):
        on = _caughtOnStderr(self.smoothNothing, True)
        self.assertIn(SMOOTH_ERROR, on, "a VTK error is printed as a console error")
        off = _caughtOnStderr(self.smoothNothing, False)
        self.assertNotIn(SMOOTH_ERROR, off, "it goes through the console, not straight to stderr")
