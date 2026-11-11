# SPDX-License-Identifier: LGPL-2.1-or-later
"""DXF in and out of sketches and faces (FreeCAD-CH).

- `insert(sketch, path, units=None, fit=True, tolerance=0.01, corner=30, hold="block")`: a DXF
  into a sketch (`importer.py`), long chains of short segments fitted to lines, arcs and splines
  (`fitting.py`).
- `export_face(face, path)`, `export_sketch(sketch, path)`, `export_selection(obj, sub, path)`:
  an R12 DXF in millimetres of true lines, arcs and circles (`exporter.py`).
The commands are in `SketcherDxfGui.py`.
"""

from .reader import DxfError, read  # noqa: F401
from .importer import DxfUnitsMissing, Report, insert, DEFAULT_TOLERANCE, DEFAULT_CORNER  # noqa: F401
from .exporter import ExportError, ExportReport, export_face, export_sketch, export_selection  # noqa: F401
