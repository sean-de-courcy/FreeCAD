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

"""File > Import and File > Open for "Onshape variables (*.json)" (FreeCAD-CH, ops#317 PR G1).

With the GUI, the import dialog opens with the file (freecad.variables.importgui); without it,
the file is imported with no choices, and anything that stands in the way raises
copies.ImportBlocked.
"""

import os

import FreeCAD as App

from freecad.variables import copies


def insert(filename, docname):
    doc = App.getDocument(docname)
    if App.GuiUp:
        from freecad.variables import importgui

        importgui.run(doc, [filename])
    else:
        copies.import_studios(doc, [filename])


def open(filename):  # noqa: A001 (the name FreeCAD's File > Open calls)
    doc = App.newDocument(os.path.splitext(os.path.basename(filename))[0])
    insert(filename, doc.Name)
