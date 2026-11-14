# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's Create drawing (ops#640, rank 62).

"""Create drawing, as Onshape's: a page on a template, the ANSI A sheet by default (the pack's
units are millimetres, so Onshape's ANSI_A_MM: FreeCAD's ANSI A template, third angle through
its standard), with "No views" chosen first, or "Suggested views" of a part: Top, Front, Right
and an isometric, laid out third angle (Top above Front, Right beside it, the isometric upper
right), with no dimensions, centre marks or labels. The sheet's scale is the largest sensible
one at which the views fit the sheet, and the views follow it ("1:3 (Parent)").

createDrawing() is the App half (headless tests use it); the command TechDraw_CreateDrawing,
registered at the GUI's start so that other workbenches' menus can call it by name (the Parts
list's "Create drawing of ..." line), asks the two questions."""

import os

import FreeCAD as App

# The templates offered, by name: the file under the Templates folder
TEMPLATES = {
    "ANSI A (landscape)": os.path.join("ASME", "ANSIA_Landscape.svg"),
    "ANSI B (landscape)": os.path.join("ASME", "ANSIB_Landscape.svg"),
    "ISO A4 (landscape)": os.path.join("ISO", "A4_Landscape_ISO5457_minimal.svg"),
    "ISO A3 (landscape)": os.path.join("ISO", "A3_Landscape_ISO5457_minimal.svg"),
}
DEFAULT_TEMPLATE = "ANSI A (landscape)"

# Onshape's suggested views, by TechDraw's projection names
SUGGESTED_VIEWS = ("Front", "Top", "Right", "FrontTopRight")


def templatePath(name=DEFAULT_TEMPLATE):
    """The template file of a name in TEMPLATES, or a path given as is."""
    relative = TEMPLATES.get(name)
    if relative is None:
        return name
    return os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", relative)


def scaleText(scale):
    """A scale as a title block shows it: 1:3, 1:1, 2:1."""
    if scale < 1:
        return "1:%g" % round(1 / scale, 4)
    return "%g:1" % round(scale, 4)


def drawable(obj):
    """Whether a selected object is a part to draw: a body, or a feature with a solid."""
    if obj is None:
        return False
    if obj.isDerivedFrom("PartDesign::Body"):
        return True
    shape = getattr(obj, "Shape", None)
    return bool(shape is not None and not shape.isNull() and shape.Solids)


def createDrawing(doc, source=None, views=False, template=DEFAULT_TEMPLATE):
    """A new page on `template`; with `views` and a `source` part, its suggested views on it, the
    sheet's scale fitted to them. Returns the page."""
    import TechDraw  # noqa: F401  the drawing's types

    page = doc.addObject("TechDraw::DrawPage", "Drawing")
    svg = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    # the page's link first, then the file: the page takes the template's projection
    page.Template = svg
    svg.Template = templatePath(template)
    page.Label = (source.Label + " Drawing") if source is not None else "Drawing"
    if not (views and drawable(source)):
        doc.recompute()
        return page

    group = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
    page.addView(group)
    group.Source = [source]
    for name in SUGGESTED_VIEWS:
        group.addProjection(name)
    # the views spread over the sheet, its middle at the sheet's middle
    group.X = page.PageWidth / 2
    group.Y = page.PageHeight / 2
    # the scale that fits, found by the group, then the sheet's: the views follow it
    group.ScaleType = "Automatic"
    doc.recompute()
    doc.recompute()
    page.Scale = group.Scale
    group.ScaleType = "Page"
    if "scale" in svg.EditableTexts:
        texts = dict(svg.EditableTexts)
        texts["scale"] = scaleText(page.Scale)
        svg.EditableTexts = texts
    doc.recompute()
    return page


if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtWidgets
    from PySide.QtCore import QT_TRANSLATE_NOOP

    def translate(text):
        return App.Qt.translate("TechDraw_CreateDrawing", text)

    class CreateDrawingDialog(QtWidgets.QDialog):
        """Onshape's Create drawing dialog, its two questions: the template, and No views or
        Suggested views (No views first; Suggested views needs a part)."""

        def __init__(self, source, parent=None):
            super().__init__(parent)
            self.setWindowTitle(translate("Create drawing"))
            layout = QtWidgets.QVBoxLayout(self)
            self.template = QtWidgets.QComboBox(self)
            self.template.setObjectName("template")
            for name in TEMPLATES:
                self.template.addItem(translate(name), name)
            self.template.setCurrentIndex(list(TEMPLATES).index(DEFAULT_TEMPLATE))
            layout.addWidget(QtWidgets.QLabel(translate("Template"), self))
            layout.addWidget(self.template)
            self.noViews = QtWidgets.QRadioButton(translate("No views"), self)
            self.noViews.setObjectName("noViews")
            self.suggested = QtWidgets.QRadioButton(translate("Suggested views"), self)
            self.suggested.setObjectName("suggestedViews")
            self.noViews.setChecked(True)
            self.suggested.setEnabled(drawable(source))
            layout.addWidget(self.noViews)
            layout.addWidget(self.suggested)
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

    def selectedPart():
        """The part the command draws: the one selected object, or the active body."""
        selection = Gui.Selection.getSelection()
        if len(selection) == 1:
            return selection[0]
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        getter = getattr(view, "getActiveObject", None)
        return getter("pdbody") if getter else None

    class CommandCreateDrawing:
        """Create drawing: a page on a template, with no views or a part's suggested views."""

        def GetResources(self):
            return {
                "Pixmap": "actions/TechDraw_PageTemplate.svg",
                "MenuText": QT_TRANSLATE_NOOP("TechDraw_CreateDrawing", "Create Drawing..."),
                "ToolTip": QT_TRANSLATE_NOOP(
                    "TechDraw_CreateDrawing",
                    "Creates a drawing on a template, with no views or the selected part's "
                    "suggested views",
                ),
            }

        def IsActive(self):
            return App.ActiveDocument is not None

        def Activated(self):
            doc = App.ActiveDocument
            source = selectedPart()
            dialog = CreateDrawingDialog(source, Gui.getMainWindow())
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return
            views = dialog.suggested.isChecked() and drawable(source)
            doc.openTransaction(translate("Create drawing"))
            try:
                page = createDrawing(doc, source, views, dialog.template.currentData())
            finally:
                doc.commitTransaction()
            # the page's own window, as Onshape opens the drawing's tab
            if page.ViewObject:
                page.ViewObject.show()

    Gui.addCommand("TechDraw_CreateDrawing", CommandCreateDrawing())
