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

The messages are caught on the console's stderr observer (fd 2), once with its error (or log)
output on and once off: with it off nothing may arrive, so text written to stderr by VTK itself
(VTK's default window elsewhere) doesn't count.

Round 1 of the fix: plain and debug text reach the console's log with their text (they printed
only "VTK"), and a contour filter whose output is empty (a pipeline without data, a constant
field) no longer has its smoother report "No data to smooth!" as an error on every recompute.
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


def _caughtOnStderr(action, on, level="Err"):
    """What the console's std observer writes to fd 2 during action(), with its output of
    `level` ("Err" or "Log") on or off."""
    if "Console" not in FreeCAD.Console.GetObservers():
        raise unittest.SkipTest("no console observer to catch the message")
    status = FreeCAD.Console.GetStatus("Console", level)
    FreeCAD.Console.SetStatus("Console", level, on)
    saved = os.dup(2)
    with tempfile.TemporaryFile() as caught:
        os.dup2(caught.fileno(), 2)
        try:
            action()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            FreeCAD.Console.SetStatus("Console", level, bool(status))
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

    def testTextReachesTheConsoleLog(self):
        window = self.vtk[0].GetInstance()

        def display():
            window.DisplayText("ops382-plain-text\n")
            window.DisplayDebugText("ops382-debug-text\n")

        on = _caughtOnStderr(display, True, "Log")
        self.assertIn(b"ops382-plain-text", on, "VTK's plain text is printed as a console log line")
        self.assertIn(b"ops382-debug-text", on, "VTK's debug text is printed as a console log line")
        off = _caughtOnStderr(display, False, "Log")
        self.assertNotIn(b"ops382-plain-text", off, "it goes through the console")
        self.assertNotIn(b"ops382-debug-text", off, "it goes through the console")


# A unit cube, one hexahedron, with the point field T given per corner (legacy VTK format)
CORNERS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]


def _writeCube(path, field):
    lines = ["# vtk DataFile Version 3.0", "unit cube", "ASCII", "DATASET UNSTRUCTURED_GRID"]
    lines.append("POINTS 8 double")
    lines += ["%g %g %g" % c for c in CORNERS]
    lines += ["CELLS 1 9", "8 0 1 2 3 4 5 6 7", "CELL_TYPES 1", "12"]
    lines += ["POINT_DATA 8", "SCALARS T double 1", "LOOKUP_TABLE default"]
    lines.append(" ".join("%g" % field(c) for c in CORNERS))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


class TestContoursFilterEmptyOutput(unittest.TestCase):
    """A contour filter with nothing to contour has an empty output and prints no VTK error;
    a contour filter with something to contour gives the contours it gave before."""

    def setUp(self):
        if "BUILD_FEM_VTK" not in FreeCAD.__cmake__:
            self.skipTest("FEM without VTK")
        import ObjectsFem

        self.ObjectsFem = ObjectsFem
        self.doc = FreeCAD.newDocument("TestContoursFilterEmptyOutput")
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    def pipelineOnCube(self, field):
        path = os.path.join(self.folder, "cube.vtk")
        _writeCube(path, field)
        pipeline = self.doc.addObject("Fem::FemPostPipeline", "Pipeline")
        pipeline.read(path)
        return pipeline

    def contoursOfT(self, pipeline, smoothing=False):
        contours = self.ObjectsFem.makePostVtkFilterContours(self.doc, pipeline)
        contours.EnableSmoothing = smoothing
        self.doc.recompute()
        contours.Field = "T"
        contours.NumberOfContours = 1  # one visible contour: the values min, middle and max
        self.doc.recompute()
        return contours

    def assertNoVtkError(self, action):
        caught = _caughtOnStderr(action, True)
        self.assertNotIn(SMOOTH_ERROR, caught, "an empty contour output is no error")
        self.assertNotIn(b"VTK", caught, "no VTK message at all")

    def outputPoints(self, contours):
        """The output's points, or None without VTK's Python bindings."""
        if _vtk() is None:
            return None
        data = contours.getDataSet()
        if data is None:
            return []
        return [data.GetPoint(i) for i in range(data.GetNumberOfPoints())]

    def recompute(self, obj):
        obj.touch()
        self.doc.recompute()

    def testPipelineWithoutData(self):
        pipeline = self.doc.addObject("Fem::FemPostPipeline", "Pipeline")
        contours = self.ObjectsFem.makePostVtkFilterContours(self.doc, pipeline)
        self.assertNoVtkError(lambda: self.recompute(contours))
        self.assertNotIn("Invalid", contours.State)
        self.assertIn(self.outputPoints(contours), (None, []))

    def testConstantField(self):
        # Every contour value equals the field's only value: nothing to contour
        pipeline = self.pipelineOnCube(lambda c: 0.0)
        made = []
        self.assertNoVtkError(lambda: made.append(self.contoursOfT(pipeline)))
        contours = made[0]
        self.assertEqual(contours.Field, "T")
        self.assertNoVtkError(lambda: self.recompute(contours))
        self.assertNotIn("Invalid", contours.State)
        self.assertIn(self.outputPoints(contours), (None, []))

    def checkLinearField(self, smoothing):
        # T = x: the contour of the middle value is the square x = 0.5; every other contour
        # point lies on a face x = 0 or x = 1. Smoothing keeps the points in their planes.
        pipeline = self.pipelineOnCube(lambda c: c[0])
        contours = self.contoursOfT(pipeline, smoothing)
        self.assertNotIn("Invalid", contours.State)
        points = self.outputPoints(contours)
        if points is None:
            self.skipTest("no VTK Python bindings")
        self.assertTrue(points, "the contours of T = x are not empty")
        tol = 1e-9
        for p in points:
            self.assertTrue(
                any(abs(p[0] - x) < tol for x in (0.0, 0.5, 1.0)), "point %s off the planes" % (p,)
            )
        middle = sorted((round(p[1], 9), round(p[2], 9)) for p in points if abs(p[0] - 0.5) < tol)
        if smoothing:
            self.assertEqual(len(middle), 4)
        else:
            self.assertEqual(middle, [(0, 0), (0, 1), (1, 0), (1, 1)])

    def testLinearField(self):
        self.checkLinearField(False)

    def testLinearFieldSmoothed(self):
        self.checkLinearField(True)
