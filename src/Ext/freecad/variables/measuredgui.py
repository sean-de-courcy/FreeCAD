# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/measured-variables-design.md in the ops repo)

"""The measured variable dialog: a task panel that takes picks in the 3D view.

The Variables panel's Add starts it for a measured kind (`start`); double-clicking a measured
variable in the panel reopens it on that measurement (`edit`). Each pick is resolved to the
feature that made the element (`measured.resolve_pick`), the value is measured live as the picks
change, and OK adds (or changes) the variable in one undo step.
"""

import FreeCAD as App
import FreeCADGui as Gui

from freecad.variables import measured

# The open dialog's panel, or None (tests and the panel read it).
current = None

KIND_TEXT = {"Distance": "Distance", "Length": "Length", "Diameter": "Diameter"}
DISTANCE_TEXT = {"Minimum": "Minimum", "Maximum": "Maximum"}
RECORD_TEXT = {"Distance": "Distance", "X": "X", "Y": "Y", "Z": "Z"}


def _tr(text):
    try:
        return App.Qt.translate("MeasuredVariable", text)
    except Exception:
        return text


def _length_text(value):
    try:
        return App.Units.Quantity(value, App.Units.Length).UserString
    except Exception:
        return "{:g} mm".format(value)


def active_studio(doc):
    """The part studio the user works in: the active tab's (an App::Part, or the document for the
    implicit studio), or None with the reason."""
    name = None
    try:
        name = Gui.DocumentTabs.activeTab(doc)
    except Exception:
        name = None
    if name in (None, ""):
        parts = [o for o in doc.Objects if o.TypeId == "App::Part"]
        if len(parts) == 1:
            return parts[0], ""
        return doc, ""
    if name == "*":
        return doc, ""
    tab = doc.getObject(name)
    if tab is not None and tab.isDerivedFrom("App::Part"):
        return tab, ""
    return None, _tr("Measured variables belong to a Part Studio: open one and add it there.")


def _same_studio(a, b):
    if isinstance(a, App.Document) or isinstance(b, App.Document):
        return a is b or (isinstance(a, App.Document) and isinstance(b, App.Document)
                          and a.Name == b.Name)
    return a is not None and b is not None and a.Name == b.Name


def _studio_label(studio):
    if isinstance(studio, App.Document):
        try:
            return App.DocumentTabs.label(studio, "*")
        except Exception:
            return studio.Label
    return studio.Label


class MeasuredPanel:
    """Task panel of one measured variable: a new one (`name`, `kind`) or an existing measurement
    (`measurement`)."""

    def __init__(self, doc, studio, name, kind="Length", description="", measurement=None):
        from PySide import QtWidgets

        self.doc = doc
        self.studio = studio
        self.name = name
        self.description = description
        self.measurement = measurement
        self.refs = []
        self.observing = False

        self.form = QtWidgets.QWidget()
        self.form.setObjectName("measuredVariablePanel")
        self.form.setWindowTitle(_tr("Measured variable"))
        layout = QtWidgets.QFormLayout(self.form)

        self.nameLabel = QtWidgets.QLabel("#" + name)
        self.nameLabel.setObjectName("variableName")
        layout.addRow(_tr("Variable:"), self.nameLabel)

        self.kindBox = QtWidgets.QComboBox()
        self.kindBox.setObjectName("kind")
        for k in measured.KINDS:
            self.kindBox.addItem(_tr(KIND_TEXT[k]), k)
        layout.addRow(_tr("Measure:"), self.kindBox)

        self.distanceBox = QtWidgets.QComboBox()
        self.distanceBox.setObjectName("distanceType")
        for d in measured.DISTANCE_TYPES:
            self.distanceBox.addItem(_tr(DISTANCE_TEXT[d]), d)
        self.distanceLabel = QtWidgets.QLabel(_tr("Distance:"))
        layout.addRow(self.distanceLabel, self.distanceBox)

        # Onshape's Use axis: shown with Minimum only (Maximum hides it, MV0)
        self.useAxisBox = QtWidgets.QCheckBox(_tr("Use axis"))
        self.useAxisBox.setObjectName("useAxis")
        self.useAxisBox.setToolTip(_tr("Measure circles, arcs and spheres from their centers, "
                                       "cylinders and cones from their axes"))
        layout.addRow("", self.useAxisBox)

        self.recordBox = QtWidgets.QComboBox()
        self.recordBox.setObjectName("valueToRecord")
        for r in measured.RECORDS:
            self.recordBox.addItem(_tr(RECORD_TEXT[r]), r)
        self.recordLabel = QtWidgets.QLabel(_tr("Value to record:"))
        layout.addRow(self.recordLabel, self.recordBox)

        # Onshape's Axis measurements: the distance and its components, read only
        self.axisLabel = QtWidgets.QLabel()
        self.axisLabel.setObjectName("axisMeasurements")
        self.axisLabel.setWordWrap(True)
        layout.addRow(self.axisLabel)

        self.radiusBox = QtWidgets.QCheckBox(_tr("Radius"))
        self.radiusBox.setObjectName("radius")
        layout.addRow("", self.radiusBox)

        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addRow(self.hint)

        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("references")
        self.list.setMaximumHeight(self.list.fontMetrics().lineSpacing() * 6)
        layout.addRow(_tr("References:"), self.list)

        self.removeButton = QtWidgets.QPushButton(_tr("Remove"))
        self.removeButton.setObjectName("removeReference")
        layout.addRow("", self.removeButton)

        self.valueLabel = QtWidgets.QLabel()
        self.valueLabel.setObjectName("value")
        layout.addRow(_tr("Value:"), self.valueLabel)

        self.errorLabel = QtWidgets.QLabel()
        self.errorLabel.setObjectName("error")
        self.errorLabel.setWordWrap(True)
        self.errorLabel.setStyleSheet("color: red;")
        layout.addRow(self.errorLabel)

        if measurement is not None:
            kind = measurement.Kind
            options = measured.options_of(measurement)
            self.distanceBox.setCurrentIndex(
                max(0, self.distanceBox.findData(options["distance_type"])))
            self.useAxisBox.setChecked(options["use_axis"])
            self.recordBox.setCurrentIndex(max(0, self.recordBox.findData(options["record"])))
            self.radiusBox.setChecked(options["radius"])
            try:
                self.refs = measured._references(measurement)
            except measured.MeasureError as e:
                # the lost ones are left out: pick their replacement
                self.refs = [(o, s) for o, s in self._links(measurement)
                             if o is not None and not measured._is_missing(s)]
                self.errorLabel.setText(str(e))
        self.kindBox.setCurrentIndex(max(0, self.kindBox.findData(kind)))

        self.kindBox.currentIndexChanged.connect(self.changed)
        self.distanceBox.currentIndexChanged.connect(self.changed)
        self.useAxisBox.toggled.connect(self.changed)
        self.recordBox.currentIndexChanged.connect(self.changed)
        self.radiusBox.toggled.connect(self.changed)
        self.removeButton.clicked.connect(self.removeSelected)

        if measurement is None:
            self.takeSelection()
        self.changed()
        self.observe(True)

    # --- state

    @staticmethod
    def _links(m):
        pairs = []
        for linked, subs in m.References:
            for sub in subs or ("",):
                pairs.append((linked, sub))
        return pairs

    def kind(self):
        return self.kindBox.currentData()

    def distanceType(self):
        return self.distanceBox.currentData()

    def options(self):
        """The options as `measured.measure` and `measured.add` take them."""
        return {"distance_type": self.distanceType(), "use_axis": self.useAxisBox.isChecked(),
                "record": self.recordBox.currentData(), "radius": self.radiusBox.isChecked()}

    def references(self):
        return list(self.refs)

    def changed(self, *_):
        """Refresh the list, the hint and the live value."""
        kind = self.kind()
        distance = kind == "Distance"
        for widget in (self.distanceBox, self.distanceLabel, self.recordBox, self.recordLabel,
                       self.axisLabel):
            widget.setVisible(distance)
        self.useAxisBox.setVisible(distance and self.distanceType() == "Minimum")
        self.radiusBox.setVisible(kind == "Diameter")
        self.axisLabel.setText("")
        self.hint.setText({
            "Distance": _tr("Pick two vertices, edges or faces in the 3D view."),
            "Length": _tr("Pick one or more edges in the 3D view, or a sketch in the tree; their "
                          "lengths are summed. A face is not measured."),
            "Diameter": _tr("Pick a circle or an arc, or a cylinder or a sphere face, in the 3D "
                            "view."),
        }[kind])
        self.list.clear()
        for obj, sub in self.refs:
            self.list.addItem(measured._show(obj, sub))
        self.value = None
        reason = measured.check_references(kind, self.refs)
        if reason:
            self.valueLabel.setText("")
            self.valueError = reason
            return
        try:
            options = self.options()
            self.value = measured.measure(kind, self.refs, **options)
            self.valueLabel.setText(_length_text(self.value))
            if distance:
                d, x, y, z = measured.distance_components(
                    self.refs, options["distance_type"], options["use_axis"])
                self.axisLabel.setText(_tr("Distance {}, along X {}, Y {}, Z {}").format(
                    *(_length_text(v) for v in (d, x, y, z))))
            self.valueError = ""
            if not self.errorLabel.text().startswith(_tr("Pick")):
                self.errorLabel.setText("")
        except Exception as e:  # MeasureError, or an OCC failure on an odd element: never OK
            self.value = None
            self.valueLabel.setText("")
            self.valueError = str(e) or type(e).__name__
            self.errorLabel.setText(self.valueError)

    def message(self, text):
        self.errorLabel.setText(text)

    # --- picks

    def addPick(self, root, subname):
        """Add the pick (root object, subname) as a reference; returns the reference, or None with
        the reason shown. A pick already listed is not added twice."""
        try:
            feature, element = measured.resolve_pick(root, subname,
                                                     wire_body=self.kind() == "Length")
        except measured.MeasureError as e:
            self.message(str(e))
            return None
        studio = measured.studio_of(feature)
        if not _same_studio(studio, self.studio):
            self.message(_tr("{} is not in {}: a measured variable reads its own Part Studio.")
                         .format(measured._show(feature, element), _studio_label(self.studio)))
            return None
        ref = (feature, element)
        if any(o.Name == feature.Name and s == element for o, s in self.refs):
            return ref
        holder = measured.holder_of(self.measurement) if self.measurement is not None else None
        if holder is not None and (feature is holder or holder in feature.OutListRecursive):
            self.message(_tr("{} uses #{}: measuring it would be a cycle.").format(
                feature.Label, self.name))
            return None
        kind = self.kind()
        low, high = measured._COUNTS[kind]
        if high is not None and len(self.refs) >= high:
            if high == 1:
                self.refs = []
            else:
                self.message(_tr("{} takes {} references: remove one first.").format(
                    _tr(KIND_TEXT[kind]), high))
                return None
        self.refs.append(ref)
        self.message("")
        self.changed()
        return ref

    def removePick(self, root, subname):
        try:
            feature, element = measured.resolve_pick(root, subname,
                                                     wire_body=self.kind() == "Length")
        except measured.MeasureError:
            return
        before = len(self.refs)
        self.refs = [(o, s) for o, s in self.refs if not (o.Name == feature.Name and s == element)]
        if len(self.refs) != before:
            self.changed()

    def removeSelected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()}, reverse=True)
        if not rows and self.refs:
            rows = [len(self.refs) - 1]
        for r in rows:
            del self.refs[r]
        self.changed()

    def takeSelection(self):
        """Pick-first: what is selected when the dialog opens becomes its references."""
        for sel in Gui.Selection.getSelectionEx(self.doc.Name, 0):
            for sub in sel.SubElementNames or ():
                self.addPick(sel.Object, sub)

    # selection observer (NoResolve: top-level object and full subname)
    def alive(self):
        """Whether the document is still open and the dialog's widgets still exist; a dead panel
        stops observing."""
        ok = False
        try:
            ok = App.getDocument(self.doc.Name) is self.doc and _valid(self.form)
        except Exception:
            ok = False
        if not ok:
            self.observe(False)
        return ok

    def addSelection(self, docName, objName, sub, pnt=None):
        try:
            if not self.alive() or docName != self.doc.Name or not sub:
                return
            root = self.doc.getObject(objName)
            if root is not None:
                self.addPick(root, sub)
        except Exception as e:  # never out of a selection callback
            _quietly(self.message, str(e))

    def removeSelection(self, docName, objName, sub):
        try:
            if not self.alive() or docName != self.doc.Name or not sub:
                return
            root = self.doc.getObject(objName)
            if root is not None:
                self.removePick(root, sub)
        except Exception as e:
            _quietly(self.message, str(e))

    def observe(self, on):
        if on and not self.observing:
            Gui.Selection.addObserver(self, 0)
            self.observing = True
        elif not on and self.observing:
            Gui.Selection.removeObserver(self)
            self.observing = False

    # --- task dialog

    def getStandardButtons(self):
        from PySide import QtWidgets

        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def apply(self):
        """Add or change the variable in one undo step; returns "" or why nothing was done."""
        kind = self.kind()
        reason = measured.check_references(kind, self.refs) or self.valueError
        if reason:
            return reason
        if self.measurement is None:
            reason = measured.check_name(self.studio, self.name)
            if reason:
                return reason
        doc = self.doc
        new = self.measurement is None
        title = ("Add measured variable " if new else "Edit measured variable ") + self.name
        doc.openTransaction(title)
        try:
            if new:
                options = self.options()
                _vs, self.measurement = measured.add(
                    self.studio, self.name, kind, self.refs, options["distance_type"],
                    self.description, options["use_axis"], options["record"], options["radius"])
            else:
                m = self.measurement
                m.Kind = kind
                measured.set_options(m, **self.options())
                measured.set_references(m, self.refs)
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            if new:
                self.measurement = None  # taken back with the transaction
            return str(e)
        doc.commitTransaction()
        return ""

    def accept(self):
        reason = self.apply()
        if reason:
            self.message(reason)
            return False
        self.close()
        return True

    def reject(self):
        self.close()
        return True

    def close(self):
        global current
        self.observe(False)
        if current is self:
            current = None
        try:
            Gui.Control.closeDialog()
        except Exception:
            pass


def _valid(widget):
    try:
        import shiboken6

        return shiboken6.isValid(widget)
    except ImportError:
        return True


def _quietly(call, *args):
    try:
        call(*args)
    except Exception:
        pass


def _still_open(panel):
    """Whether `panel`'s task dialog is still open in its own document (each document has its
    own task dialog)."""
    try:
        if App.getDocument(panel.doc.Name) is not panel.doc or not _valid(panel.form):
            return False
        return bool(Gui.Control.activeDialog(Gui.getDocument(panel.doc.Name)))
    except Exception:
        return False


def _drop_stale():
    """A panel whose task dialog was closed some other way (its document closed, another
    dialog's closeDialog) stops observing."""
    global current
    if current is not None and not _still_open(current):
        current.observe(False)
        current = None


def start(doc, name, kind, description=""):
    """From the Variables panel's Add: open the dialog for a new measured variable `name` of `kind`
    in the active part studio. Returns "" or why it can't open (the Add dialog shows it)."""
    _drop_stale()
    if isinstance(doc, str):
        doc = App.getDocument(doc)
    studio, reason = active_studio(doc)
    if studio is None:
        return reason
    reason = measured.check_name(studio, name)
    if reason:
        return reason
    if kind not in measured.KINDS:
        return "unknown kind {!r}".format(kind)
    if Gui.Control.activeDialog():
        return _tr("Close the open task dialog first.")
    panel = MeasuredPanel(doc, studio, name, kind, description)
    global current
    current = panel
    Gui.Control.showDialog(panel)
    return ""


def measurement_of(holder, name):
    """The measurement read by the variable `name` of `holder`, or None."""
    return measured.measurement_of(holder, name)


def edit(holder, name):
    """From the Variables panel (double-click on a measured variable): reopen the dialog on its
    measurement. Returns "" or why it can't open."""
    _drop_stale()
    if isinstance(holder, (list, tuple)):
        holder = App.getDocument(holder[0]).getObject(holder[1])
    m = measurement_of(holder, name)
    if m is None:
        return _tr("{} is not a measured variable.").format(name)
    if Gui.Control.activeDialog():
        return _tr("Close the open task dialog first.")
    studio = measured.studio_of(m) or m.Document
    panel = MeasuredPanel(m.Document, studio, name, measurement=m)
    global current
    current = panel
    Gui.Control.showDialog(panel)
    return ""
