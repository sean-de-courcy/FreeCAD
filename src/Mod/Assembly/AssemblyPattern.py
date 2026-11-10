# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (asm-patterns): assembly instance patterns, as Onshape's assembly Linear and Circular
# pattern. Design note: notes/assembly-patterns-design.md in the ops repo.
#
# A pattern is an object of the assembly's joint group. For each seed (an instance of the
# assembly) and each i in 1..Count-1 it owns one copy: an App::Link in the assembly's Group, so the
# instance list and the BOM count it as Onshape does. Copy i of a seed is placed at
#   Linear:   Translate(i * Distance * d) * seed
#   Circular: Rotate(axis, i * step) * seed
# with d and the axis read in the assembly's frame from the Direction reference. The solver
# (AssemblyObject.cpp) gives a seed and its copies one solver body, and calls placeInstances()
# before and after each solve, so the copies follow their seed and mates to copies hold.

import math
import re

import FreeCAD as App
import Part

from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets

translate = App.Qt.translate

__title__ = "Assembly instance patterns"

PATTERN_TYPES = ["Linear", "Circular"]
# Placements closer than this are the same (mm, and radians for the rotation)
TOLERANCE = 1e-7
# The pattern panel that is open (as JointObject.activeTask)
activePanel = None


def reachOf(seed):
    """How far the seed's shape reaches from its placement's origin (mm; 100 when it has none)"""
    try:
        box = seed.Shape.BoundBox
    except Exception:
        return 100.0
    if not box.isValid():
        return 100.0
    origin = seed.Placement.Base
    corners = [App.Vector(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    return max((c - origin).Length for c in corners)


def hasExpression(obj, name):
    """Whether an expression drives obj's property name"""
    return any(path == name for path, _ in obj.ExpressionEngine)


def isPattern(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == InstancePattern.Type


def assemblyOf(fp):
    """The assembly whose joint group holds fp"""
    for parent in fp.InList:
        if parent.isDerivedFrom("Assembly::AssemblyObject"):
            return parent
        if parent.TypeId == "Assembly::JointGroup":
            for grand in parent.InList:
                if grand.isDerivedFrom("Assembly::AssemblyObject"):
                    return grand
    return None


def sourceOf(seed):
    """What a copy of seed links to: the seed's linked object, or the seed itself"""
    if seed.isDerivedFrom("App::Link") or seed.isDerivedFrom("Assembly::AssemblyLink"):
        linked = seed.LinkedObject
        if linked is not None:
            return linked
    return seed


def instanceLabel(assembly, source):
    """Onshape's instance name, "<source> <N>", N the lowest number free (as Insert names them,
    CommandInsertLink.instanceLabel)"""
    base = source.Label
    taken = set()
    pattern = re.compile(re.escape(base) + r" <(\d+)>$")
    for obj in assembly.Group:
        match = pattern.match(obj.Label)
        if match:
            taken.add(int(match.group(1)))
    duplicates = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetBool(
        "DuplicateLabels", False
    )
    doc = assembly.Document
    n = 1
    while n in taken or (not duplicates and doc.getObjectsByLabel(f"{base} <{n}>")):
        n += 1
    return f"{base} <{n}>"


def patternLabel(assembly, kind):
    """"Linear pattern 1", "Circular pattern 2"... (Onshape's feature names)"""
    base = f"{kind} pattern"
    taken = {o.Label for o in assembly.Document.Objects}
    n = 1
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def referenceAxis(fp):
    """(point, unit direction) of the pattern's Direction reference in the assembly's frame.
    Raises RuntimeError with the reason when the reference is missing or its element is gone."""
    ref = fp.Direction
    what = "axis" if fp.PatternType == "Circular" else "direction"
    if not ref or ref[0] is None:
        raise RuntimeError(translate("Assembly", "{0}: pick a {1}").format(fp.Label, what))
    obj, subs = ref[0], ref[1]
    sub = subs[0] if subs else ""
    name = f"{obj.Label}.{sub}" if sub else obj.Label
    try:
        shape = Part.getShape(obj, sub, needSubElement=True, transform=True)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        raise RuntimeError(
            translate("Assembly", "{0}: the {1} reference {2} is gone").format(fp.Label, what, name)
        )
    axis = axisOfShape(shape)
    if axis is None:
        raise RuntimeError(
            translate("Assembly", "{0}: {1} gives no {2} (pick a straight or circular edge, a plane or a cylinder)").format(
                fp.Label, name, what
            )
        )
    return axis


def axisOfShape(shape):
    """(point, unit direction) of a straight or circular edge, a plane (its normal) or a cylinder
    or cone (its axis); None for anything else"""
    if shape.ShapeType == "Edge":
        curve = shape.Curve
        kind = type(curve).__name__
        if kind in ("Line", "LineSegment"):
            points = [v.Point for v in shape.Vertexes]
            if len(points) >= 2 and (points[-1] - points[0]).Length > TOLERANCE:
                return points[0], (points[-1] - points[0]).normalize()
            return App.Vector(curve.Location), App.Vector(curve.Direction).normalize()
        if hasattr(curve, "Axis") and hasattr(curve, "Center"):
            # The axis the edge turns about (right hand), whichever way its curve is parametrized
            axis = App.Vector(curve.Axis).normalize()
            return App.Vector(curve.Center), -axis if shape.Orientation == "Reversed" else axis
        return None
    if shape.ShapeType == "Face":
        surface = shape.Surface
        kind = type(surface).__name__
        if kind == "Plane":
            u0, u1, v0, v1 = shape.ParameterRange
            u, v = (u0 + u1) / 2, (v0 + v1) / 2
            return shape.valueAt(u, v), App.Vector(shape.normalAt(u, v)).normalize()
        if kind in ("Cylinder", "Cone") and hasattr(surface, "Axis"):
            # The axis that turning about (right hand) with the outward normal goes the face's way
            # round: a Part cylinder's side face is reversed on a -Z surface axis, and gives +Z
            center = surface.Center if hasattr(surface, "Center") else surface.Apex
            axis = App.Vector(surface.Axis).normalize()
            return App.Vector(center), -axis if shape.Orientation == "Reversed" else axis
        return None
    if shape.ShapeType in ("Wire", "Compound") and len(shape.Edges) == 1:
        return axisOfShape(shape.Edges[0])
    return None


class InstancePattern:
    """The proxy of an assembly pattern (App::FeaturePython in the joint group)"""

    Type = "Assembly::InstancePattern"

    def __init__(self, fp, kind="Linear"):
        fp.Proxy = self
        self.setProperties(fp)
        fp.PatternType = kind

    def setProperties(self, fp):
        def add(kind, name, doc):
            if not hasattr(fp, name):
                fp.addProperty(kind, name, "Pattern", doc)

        add("App::PropertyEnumeration", "PatternType", QT_TRANSLATE_NOOP("App::Property", "Linear or Circular"))
        fp.PatternType = PATTERN_TYPES
        add("App::PropertyLinkList", "Seeds", QT_TRANSLATE_NOOP("App::Property", "The instances to pattern"))
        add(
            "App::PropertyXLinkSub",
            "Direction",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The direction (Linear) or the axis (Circular): a straight or circular edge, a plane, a cylinder",
            ),
        )
        add("App::PropertyLength", "Distance", QT_TRANSLATE_NOOP("App::Property", "The distance between neighbouring instances (Linear)"))
        add("App::PropertyAngle", "Angle", QT_TRANSLATE_NOOP("App::Property", "The angle between neighbouring instances, or the whole spread with Equal spacing (Circular)"))
        add("App::PropertyBool", "EqualSpacing", QT_TRANSLATE_NOOP("App::Property", "Spread the instances evenly over the angle (Circular)"))
        add("App::PropertyIntegerConstraint", "Count", QT_TRANSLATE_NOOP("App::Property", "The number of instances, the seed included"))
        add("App::PropertyBool", "Reversed", QT_TRANSLATE_NOOP("App::Property", "Pattern the other way"))
        add("App::PropertyBool", "Suppressed", QT_TRANSLATE_NOOP("App::Property", "A suppressed pattern has no copies"))
        add("App::PropertyLinkListHidden", "Instances", QT_TRANSLATE_NOOP("App::Property", "The copies the pattern made"))
        fp.setPropertyStatus("Instances", ["ReadOnly", "Hidden"])
        fp.Count = (max(int(fp.Count), 2) if fp.Count else 2, 1, 100000, 1)
        if fp.Distance.Value == 0:
            fp.Distance = 25.0
        if fp.Angle.Value == 0:
            fp.Angle = 360.0
            fp.EqualSpacing = True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    # --- what the pattern makes -------------------------------------------------------------------

    def transforms(self, fp):
        """The placements that take a seed to copies 1..Count-1"""
        count = int(fp.Count)
        if count < 2:
            return []
        point, direction = referenceAxis(fp)
        sign = -1.0 if fp.Reversed else 1.0
        result = []
        if fp.PatternType == "Circular":
            angle = fp.Angle.Value
            if fp.EqualSpacing:
                full = abs(abs(angle) - 360.0) < 1e-9
                step = angle / count if full else angle / (count - 1)
            else:
                step = angle
            for i in range(1, count):
                rotation = App.Rotation(direction, sign * step * i)
                result.append(App.Placement(App.Vector(), rotation, point))
        else:
            spacing = direction * (sign * fp.Distance.Value)
            for i in range(1, count):
                result.append(App.Placement(spacing * i, App.Rotation()))
        return result

    def seeds(self, fp):
        assembly = assemblyOf(fp)
        members = set(assembly.Group) if assembly else set()
        return [s for s in fp.Seeds if s is not None and s in members and not isPatternCopy(s)]

    def copySeeds(self, fp):
        """The seeds that are another pattern's copies (not patterned: said, not dropped)"""
        return [s for s in fp.Seeds if s is not None and isPatternCopy(s) and s.PatternOwner != fp]

    def copiesBySeed(self, fp):
        """{seed name: {index: copy}} of the copies the pattern holds that its count wants"""
        result = {}
        count = int(fp.Count)
        for copy in fp.Instances:
            if copy is None or not hasattr(copy, "PatternIndex") or not 0 < copy.PatternIndex < count:
                continue
            seed = copy.PatternSeed
            result.setdefault(seed.Name if seed else "", {}).setdefault(copy.PatternIndex, copy)
        return result

    def clusters(self, fp):
        """Each seed followed by its copies (the solver gives them one body)"""
        if fp.Suppressed:
            return []
        held = self.copiesBySeed(fp)
        clusters = []
        for seed in self.seeds(fp):
            copies = held.get(seed.Name, {})
            if copies:
                clusters.append([seed] + [copies[i] for i in sorted(copies)])
        return clusters

    def placeInstances(self, fp):
        """Places the copies at the pattern's placements; how far the copy that moved most went (mm,
        the farthest point of its shape). Raises when the direction is lost (the solver reports
        it; the copies stay where they are)."""
        if fp.Suppressed:
            return 0.0
        transforms = self.transforms(fp)
        held = self.copiesBySeed(fp)
        moved = 0.0
        for seed in self.seeds(fp):
            copies = held.get(seed.Name, {})
            reach = reachOf(seed)
            for i, transform in enumerate(transforms, start=1):
                copy = copies.get(i)
                if copy is None:
                    continue
                target = transform.multiply(seed.Placement)
                if not copy.Placement.isSame(target, TOLERANCE):
                    step = copy.Placement.inverse().multiply(target)
                    # The farthest point of the copy moves at most this far
                    moved = max(moved, step.Base.Length + abs(step.Rotation.Angle) * reach)
                    copy.Placement = target
                    copy.purgeTouched()
        return moved

    def makeCopy(self, fp, assembly, seed, index):
        source = sourceOf(seed)
        kind = "Assembly::AssemblyLink" if seed.isDerivedFrom("Assembly::AssemblyLink") else "App::Link"
        copy = assembly.newObject(kind, source.Name)
        self.matchSeed(copy, seed)
        copy.Label = instanceLabel(assembly, source)
        copy.addProperty("App::PropertyLinkHidden", "PatternSeed", "Pattern", "The seed this copy repeats")
        copy.addProperty("App::PropertyInteger", "PatternIndex", "Pattern", "The copy's number in its pattern")
        copy.addProperty("App::PropertyLinkHidden", "PatternOwner", "Pattern", "The pattern that made this copy")
        copy.PatternSeed = seed
        copy.PatternIndex = index
        copy.PatternOwner = fp
        for name in ("PatternSeed", "PatternIndex", "PatternOwner"):
            copy.setPropertyStatus(name, ["ReadOnly"])
        copy.Placement = seed.Placement
        return copy

    def matchSeed(self, copy, seed):
        """The copy links to what its seed links to, scaled and rigid as the seed"""
        source = sourceOf(seed)
        if copy.LinkedObject != source:
            copy.LinkedObject = source
        for name in ("Rigid", "ScaleVector"):
            if hasattr(copy, name) and hasattr(seed, name) and getattr(copy, name) != getattr(seed, name):
                setattr(copy, name, getattr(seed, name))

    def reconcile(self, fp):
        """Makes the copies the properties ask for and removes the others"""
        assembly = assemblyOf(fp)
        if assembly is None:
            raise RuntimeError(translate("Assembly", "{0} is in no assembly").format(fp.Label))
        doc = fp.Document
        count = 0 if fp.Suppressed else int(fp.Count)
        seeds = self.seeds(fp)
        wanted = {(s.Name, i) for s in seeds for i in range(1, count)}
        # The copies are the ones listed and any other link of the assembly that names this pattern
        # its owner: an undo outside the recompute's transaction can bring one back unlisted
        listed = [c for c in fp.Instances if c is not None and hasattr(c, "PatternIndex")]
        unlisted = [
            o for o in assembly.Group if getattr(o, "PatternOwner", None) == fp and o not in listed
        ]
        keep = {}
        extra = []
        for copy in listed + unlisted:
            key = (copy.PatternSeed.Name if copy.PatternSeed else "", copy.PatternIndex)
            if key in wanted and key not in keep:
                keep[key] = copy
            elif copy in unlisted and key in keep:
                # A duplicate of a copy (pasted, or copied with its properties): a plain instance of
                # its own, not the pattern's
                for name in ("PatternOwner", "PatternSeed", "PatternIndex"):
                    copy.removeProperty(name)
            else:
                extra.append(copy)
        # A copy a mate uses isn't removed: the pattern says so and changes nothing (a mate would
        # otherwise lose its part without an error)
        direction = fp.Direction[0] if fp.Direction else None
        for copy in extra:
            users = usersOf(assembly, copy, fp)
            if copy == direction:
                users.append(fp)
            if users:
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is used by {2}; delete or change that first").format(
                        fp.Label, copy.Label, ", ".join(u.Label for u in users)
                    )
                )
        for copy in extra:
            doc.removeObject(copy.Name)
        ordered = []
        for seed in seeds:
            for i in range(1, count):
                copy = keep.get((seed.Name, i))
                if copy is None:
                    copy = self.makeCopy(fp, assembly, seed, i)
                else:
                    self.matchSeed(copy, seed)
                ordered.append(copy)
        if list(fp.Instances) != ordered:
            fp.setPropertyStatus("Instances", "-ReadOnly")
            fp.Instances = ordered
            fp.setPropertyStatus("Instances", "ReadOnly")

    def execute(self, fp):
        copySeeds = self.copySeeds(fp)
        if copySeeds:
            raise RuntimeError(
                translate("Assembly", "{0}: {1} is a copy of {2}; pattern its seed instead").format(
                    fp.Label, copySeeds[0].Label, copySeeds[0].PatternOwner.Label
                )
            )
        if not fp.Suppressed:
            if not self.seeds(fp):
                self.reconcile(fp)  # the copies of a deleted seed go
                raise RuntimeError(translate("Assembly", "{0}: pick the instances to pattern").format(fp.Label))
            # Raises when the direction is lost, before anything changes: the copies stay
            self.transforms(fp)
        self.reconcile(fp)
        # A fixed copy would be moved by its pattern: said instead
        import UtilsAssembly

        for other in UtilsAssembly.getJointGroup(assemblyOf(fp)).Group:
            ground = getattr(other, "ObjectToGround", None)
            if ground is not None and ground in fp.Instances:
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is fixed; a patterned instance follows its seed: unfix it").format(
                        fp.Label, ground.Label
                    )
                )
            # A rigid group with a copy in it would stop holding its other members to the copy when the
            # pattern moves the copy: said instead
            grouped = [c for c in (getattr(other, "ObjectsToRigidGroup", None) or []) if c in fp.Instances]
            if grouped and not getattr(other, "Suppressed", False):
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is in {2}; a patterned instance can't be in a rigid group").format(
                        fp.Label, grouped[0].Label, other.Label
                    )
                )
        self.placeInstances(fp)
        for copy in fp.Instances:
            if copy is not None:
                copy.purgeTouched()

    def unsetupObject(self, fp):
        """Deleting the pattern deletes its copies (not called on undo; not when the whole assembly
        or its joint group goes, which removes the copies itself)"""
        doc = fp.Document
        if any(getattr(parent, "Removing", False) for parent in fp.InList):
            return
        assembly = assemblyOf(fp)
        if assembly is not None and assembly.Removing:
            return
        for copy in list(fp.Instances):
            if copy is None or copy.Removing or doc.getObject(copy.Name) is None:
                continue
            if assembly is not None and usersOf(assembly, copy, fp):
                # A copy a mate uses stays, as a plain instance where it is: its mates keep their part
                for name in ("PatternOwner", "PatternSeed", "PatternIndex"):
                    copy.removeProperty(name)
                continue
            doc.removeObject(copy.Name)


def usersOf(assembly, obj, pattern=None):
    """The joints, groundings, rigid groups and other patterns of the assembly that use obj"""
    import UtilsAssembly

    users = []
    for other in UtilsAssembly.getJointGroup(assembly).Group:
        if other == pattern:
            continue
        refs = [getattr(other, name, None) for name in ("Reference1", "Reference2", "Direction")]
        if (
            any(ref and ref[0] == obj for ref in refs)
            or getattr(other, "ObjectToGround", None) == obj
            or obj in (getattr(other, "ObjectsToRigidGroup", None) or [])
            or obj in (getattr(other, "Seeds", None) or [])
        ):
            users.append(other)
    return users


def isPatternCopy(obj):
    return obj is not None and hasattr(obj, "PatternOwner") and obj.PatternOwner is not None


def makePattern(assembly, kind="Linear", seeds=(), direction=None):
    """Makes a pattern in the assembly's joint group (without recomputing)"""
    import UtilsAssembly

    joints = UtilsAssembly.getJointGroup(assembly)
    fp = joints.newObject("App::FeaturePython", f"{kind}Pattern")
    InstancePattern(fp, kind)
    fp.Label = patternLabel(assembly, kind)
    fp.Seeds = list(seeds)
    if direction is not None:
        fp.Direction = direction
    if App.GuiUp:
        ViewProviderInstancePattern(fp.ViewObject)
    return fp


# --- GUI ------------------------------------------------------------------------------------------


class ViewProviderInstancePattern:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        kind = getattr(getattr(self, "Object", None), "PatternType", "Linear")
        return f":/icons/Assembly_CreatePattern{kind}.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction(translate("Assembly", "Edit Pattern"))
        action.triggered.connect(lambda: self.edit(vobj))
        return False

    def doubleClicked(self, vobj):
        return self.edit(vobj)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        return self.edit(vobj)

    def unsetEdit(self, vobj, mode=0):
        return False

    def edit(self, vobj):
        if Gui.Control.activeDialog():
            return False
        showPanel(TaskInstancePattern(vobj.Object))
        return True


def showPanel(panel):
    """Shows the pattern panel; it closes (Cancel) when its transaction or its document goes"""
    dialog = Gui.Control.showDialog(panel)
    if dialog is not None:
        dialog.setAutoCloseOnTransactionChange(True)
        dialog.setAutoCloseOnDeletedDocument(True)
        dialog.setDocumentName(panel.doc.Name)
    return dialog


class TaskInstancePattern(QtCore.QObject if App.GuiUp else object):
    """Onshape's pattern dialog: the instances, the direction or axis, the distance or angle, the count.
    Picks go to the field that is checked (Instances or Direction); the copies update as you type."""

    def __init__(self, pattern, created=False):
        super().__init__()
        global activePanel
        activePanel = self
        self.pattern = pattern
        self.created = created
        self.doc = pattern.Document
        self.assembly = assemblyOf(pattern)
        if not created:
            self.doc.openTransaction(translate("Assembly", "Edit {0}").format(pattern.Label))
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(pattern.Label)
        layout = QtWidgets.QFormLayout(self.form)

        self.seedsButton = QtWidgets.QPushButton(translate("Assembly", "Instances to pattern"))
        self.seedsButton.setCheckable(True)
        self.seedsList = QtWidgets.QListWidget()
        self.seedsList.setMaximumHeight(90)
        layout.addRow(self.seedsButton)
        layout.addRow(self.seedsList)

        circular = pattern.PatternType == "Circular"
        self.directionButton = QtWidgets.QPushButton(
            translate("Assembly", "Axis") if circular else translate("Assembly", "Direction")
        )
        self.directionButton.setCheckable(True)
        self.directionLabel = QtWidgets.QLabel()
        layout.addRow(self.directionButton, self.directionLabel)
        self.seedsButton.clicked.connect(lambda: self.setField("seeds"))
        self.directionButton.clicked.connect(lambda: self.setField("direction"))

        loader = Gui.UiLoader()
        self.bindings = []
        if circular:
            self.amount = loader.createWidget("Gui::QuantitySpinBox")
            self.amount.setProperty("unit", "deg")
            self.bind(self.amount, "Angle")
            layout.addRow(translate("Assembly", "Angle"), self.amount)
            self.equal = QtWidgets.QCheckBox(translate("Assembly", "Equal spacing"))
            self.equal.setChecked(pattern.EqualSpacing)
            self.equal.toggled.connect(self.onEqual)
            layout.addRow(self.equal)
        else:
            self.amount = loader.createWidget("Gui::QuantitySpinBox")
            self.amount.setProperty("unit", "mm")
            self.bind(self.amount, "Distance")
            layout.addRow(translate("Assembly", "Distance"), self.amount)
        self.amount.setObjectName("patternAmount")
        self.amount.setProperty("rawValue", pattern.Angle.Value if circular else pattern.Distance.Value)
        self.amount.valueChanged.connect(self.onAmount)
        self.count = loader.createWidget("Gui::IntSpinBox")
        self.count.setObjectName("patternCount")
        self.count.setMinimum(1)
        self.count.setMaximum(100000)
        self.count.setValue(int(pattern.Count))
        self.bind(self.count, "Count")
        self.count.valueChanged.connect(self.onCount)
        layout.addRow(translate("Assembly", "Instance count"), self.count)
        self.reversed = QtWidgets.QCheckBox(translate("Assembly", "Flip"))
        self.reversed.setChecked(pattern.Reversed)
        self.reversed.toggled.connect(self.onReversed)
        layout.addRow(self.reversed)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c00000")
        layout.addRow(self.message)

        self.refresh()
        self.setField("seeds" if not pattern.Seeds else "direction" if not pattern.Direction else "")
        Gui.Selection.clearSelection()
        # Picks with their whole path from the root, as the joint dialog takes them
        Gui.Selection.addObserver(self, Gui.Selection.ResolveMode.NoResolve)

    def bind(self, widget, name):
        binding = Gui.ExpressionBinding(widget)
        binding.bind(self.pattern, name)
        binding.setAutoApply(True)
        self.bindings.append(binding)

    # the fields
    def setField(self, field):
        self.field = field
        self.seedsButton.setChecked(field == "seeds")
        self.directionButton.setChecked(field == "direction")

    def refresh(self):
        self.seedsList.clear()
        for seed in self.pattern.Seeds:
            if seed is not None:
                self.seedsList.addItem(seed.Label)
        ref = self.pattern.Direction
        if ref and ref[0] is not None:
            sub = ref[1][0] if ref[1] else ""
            self.directionLabel.setText(f"{ref[0].Label}.{sub.split('.')[-1]}" if sub else ref[0].Label)
        else:
            self.directionLabel.setText(translate("Assembly", "(pick an edge or a face)"))

    def update(self):
        self.pattern.touch()
        self.doc.recompute()
        # Copies removed in a recompute go after it: the assembly solves again without them
        if self.assembly is not None and "Touched" in self.assembly.State:
            self.doc.recompute()
        self.refresh()
        if "Invalid" in self.pattern.State or "Error" in self.pattern.State:
            self.message.setText(self.lastError())
        else:
            self.message.setText("")

    def lastError(self):
        try:
            self.pattern.Proxy.transforms(self.pattern)
            if not self.pattern.Proxy.seeds(self.pattern):
                return translate("Assembly", "Pick the instances to pattern")
        except RuntimeError as error:
            return str(error)
        return translate("Assembly", "The pattern failed (see the report view)")

    def onAmount(self, *args):
        value = self.amount.property("rawValue")
        if self.pattern.PatternType == "Circular":
            if not hasExpression(self.pattern, "Angle") and abs(self.pattern.Angle.Value - value) > 1e-12:
                self.pattern.Angle = value
        elif not hasExpression(self.pattern, "Distance") and abs(self.pattern.Distance.Value - value) > 1e-12:
            self.pattern.Distance = value
        self.update()

    def onCount(self, value):
        if not hasExpression(self.pattern, "Count") and int(self.pattern.Count) != int(value):
            self.pattern.Count = int(value)
        self.update()

    def onReversed(self, checked):
        self.pattern.Reversed = checked
        self.update()

    def onEqual(self, checked):
        self.pattern.EqualSpacing = checked
        self.update()

    # picks
    def addSelection(self, doc_name, obj_name, sub_name, mousePos=None):
        # An error in a selection observer is lost: report it
        try:
            self.onPick(doc_name, obj_name, sub_name)
        except Exception:
            import traceback

            App.Console.PrintError(traceback.format_exc())

    def onPick(self, doc_name, obj_name, sub_name):
        import UtilsAssembly

        try:
            self.doc.Name
        except ReferenceError:
            # The dialog was closed without OK or Cancel and its document is gone
            Gui.Selection.removeObserver(self)
            return

        if self.assembly is None or doc_name != self.doc.Name:
            return
        root = self.doc.getObject(obj_name)
        comp, sub = UtilsAssembly.getComponentReference(self.assembly, root, sub_name)
        if comp is None:
            return
        if self.field == "direction":
            if not sub:
                return
            self.pattern.Direction = (comp, [sub])
            self.setField("")
        elif self.field == "seeds":
            seeds = [s for s in self.pattern.Seeds if s is not None]
            if isPatternCopy(comp):
                # A copy stands for its seed: it adds the seed, it never removes it
                comp = comp.PatternSeed
                if comp in seeds:
                    return
            if comp in seeds:
                seeds.remove(comp)
            else:
                seeds.append(comp)
            self.pattern.Seeds = seeds
        else:
            # No field chosen: a pick goes nowhere (click Instances or Direction first)
            return
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        self.update()

    # the dialog
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def finish(self):
        global activePanel
        if activePanel is self:
            activePanel = None
        Gui.Selection.removeObserver(self)
        self.bindings = []
        gdoc = Gui.getDocument(self.doc.Name) if self.doc.Name in App.listDocuments() else None
        if gdoc is not None and gdoc.getInEdit() == self.pattern.ViewObject:
            gdoc.resetEdit()

    def autoClosedOnTransactionChange(self):
        self.reject()

    def autoClosedOnDeletedDocument(self):
        Gui.Selection.removeObserver(self)
        self.bindings = []

    def accept(self):
        self.update()
        if "Invalid" in self.pattern.State or "Error" in self.pattern.State:
            # OK keeps the dialog while the pattern is in error (Cancel leaves)
            self.message.setText(self.lastError())
            return False
        self.finish()
        self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self.finish()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


class CommandCreatePattern:
    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        if self.kind == "Circular":
            menu = QT_TRANSLATE_NOOP("Assembly_CreatePatternCircular", "Circular Pattern")
            tip = QT_TRANSLATE_NOOP(
                "Assembly_CreatePatternCircular",
                "<p>Repeats the selected instances around an axis.</p>"
                "<p>The copies are instances that follow their seed.</p>",
            )
        else:
            menu = QT_TRANSLATE_NOOP("Assembly_CreatePatternLinear", "Linear Pattern")
            tip = QT_TRANSLATE_NOOP(
                "Assembly_CreatePatternLinear",
                "<p>Repeats the selected instances along a direction.</p>"
                "<p>The copies are instances that follow their seed.</p>",
            )
        return {
            "Pixmap": f"Assembly_CreatePattern{self.kind}",
            "MenuText": menu,
            "ToolTip": tip,
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        import UtilsAssembly

        return (
            UtilsAssembly.isAssemblyCommandActive()
            and UtilsAssembly.assembly_has_at_least_n_parts(1)
            and not Gui.Control.activeDialog()
        )

    def Activated(self):
        import UtilsAssembly

        assembly = UtilsAssembly.activeAssembly()
        if not assembly:
            return
        seeds = []
        for sel in Gui.Selection.getSelectionEx("*", 0):
            for sub in sel.SubElementNames or [""]:
                comp, _ = UtilsAssembly.getComponentReference(assembly, sel.Object, sub)
                if comp is not None and isPatternCopy(comp):
                    comp = comp.PatternSeed
                if comp is not None and comp not in seeds:
                    seeds.append(comp)
        doc = assembly.Document
        doc.openTransaction(translate("Assembly", "{0} pattern").format(self.kind))
        pattern = makePattern(assembly, self.kind, seeds)
        doc.recompute()
        showPanel(TaskInstancePattern(pattern, created=True))


if App.GuiUp:
    Gui.addCommand("Assembly_CreatePatternLinear", CommandCreatePattern("Linear"))
    Gui.addCommand("Assembly_CreatePatternCircular", CommandCreatePattern("Circular"))
