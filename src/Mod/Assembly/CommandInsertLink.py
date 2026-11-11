# SPDX-License-Identifier: LGPL-2.1-or-later
# /**************************************************************************
#                                                                           *
#    Copyright (c) 2023 Ondsel <development@ondsel.com>                     *
#                                                                           *
#    This file is part of FreeCAD.                                          *
#                                                                           *
#    FreeCAD is free software: you can redistribute it and/or modify it     *
#    under the terms of the GNU Lesser General Public License as            *
#    published by the Free Software Foundation, either version 2.1 of the   *
#    License, or (at your option) any later version.                        *
#                                                                           *
#    FreeCAD is distributed in the hope that it will be useful, but         *
#    WITHOUT ANY WARRANTY; without even the implied warranty of             *
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
#    Lesser General Public License for more details.                        *
#                                                                           *
#    You should have received a copy of the GNU Lesser General Public       *
#    License along with FreeCAD. If not, see                                *
#    <https://www.gnu.org/licenses/>.                                       *
#                                                                           *
# **************************************************************************/

import re
import os
import FreeCAD as App

from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
    from PySide.QtGui import QIcon

import UtilsAssembly
import Preferences
import CommandCreateJoint

__title__ = "Assembly Command Insert Component"
__author__ = "Ondsel"
__url__ = "https://www.freecad.org"


tooltip = QT_TRANSLATE_NOOP(
    "Assembly_InsertLink",
    "<p>Inserts a component into the active assembly. This will create dynamic links to parts, bodies, primitives, and assemblies. To insert external components, make sure that the file is <b>open in the current session</b></p>"
    "<ul>"
    "<li>Insert by left clicking items in the list.</li>"
    "<li>Remove by right clicking items in the list.</li>"
    "<li>Press shift to add several instances of the component while clicking on the view.</li>"
    "</ul>",
)

# FreeCAD-CH (ops#640 round 7, gap A16): the implicit Part Studio's tab name (App::DocumentTabs)
IMPLICIT_STUDIO = UtilsAssembly.IMPLICIT_STUDIO


def typedTabsOn():
    """Whether the typed tabs are on (the Onshape keymap, Gui::DocumentTabs::isOn)."""
    return hasattr(Gui, "DocumentTabs") and Gui.DocumentTabs.isOn() and hasattr(App, "DocumentTabs")


def onshapeKeymap():
    """Whether the fork's Onshape keymap is the active one (Gui::ForkKeymap::isOnshape)."""
    general = App.ParamGet("User parameter:BaseApp/Preferences/General")
    return general.GetString("Keymap", "Onshape") != "FreeCAD"


def instanceLabel(assembly, source):
    """FreeCAD-CH (ops#640 round 10, gap A27): Onshape's instance name, "<source> <N>" ("Part 1
    <1>", "Part 1 <2>", "Part Studio 2 <1>"), N the lowest number no instance of the source in this
    assembly reads. Labels are unique in a document unless the preference allows duplicates: a
    number another assembly's instance reads is taken too, where Onshape counts per assembly."""
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


class CommandGroupInsert:
    def GetCommands(self):
        return ("Assembly_InsertLink", "Assembly_InsertNewPart")

    def GetResources(self):
        """Set icon, menu and tooltip."""

        return {
            "Pixmap": "Assembly_InsertLink",
            "MenuText": QT_TRANSLATE_NOOP("Assembly_Insert", "Insert Component"),
            "ToolTip": tooltip,
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        return UtilsAssembly.isAssemblyCommandActive()


class CommandInsertLink:
    def __init__(self):
        pass

    def GetResources(self):
        return {
            "Pixmap": "Assembly_InsertLink",
            "MenuText": QT_TRANSLATE_NOOP("Assembly_InsertLink", "Insert Component"),
            "Accel": "I",
            "ToolTip": tooltip,
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        return UtilsAssembly.isAssemblyCommandActive()

    def Activated(self):
        assembly = UtilsAssembly.activeAssembly()
        if not assembly:
            return
        view = Gui.activeDocument().activeView()
        self.panel = TaskAssemblyInsertLink(assembly, view)
        Gui.Control.showDialog(self.panel)


class InsertLinkObserver:
    def __init__(self, callback):
        self.callback = callback

    def slotDeletedObject(self, obj):
        self.callback(obj)


class TaskAssemblyInsertLink(QtCore.QObject):
    def __init__(self, assembly, view):
        super().__init__()

        self.assembly = assembly
        self.view = view
        self.doc = App.ActiveDocument
        self.showHidden = False

        self.form = Gui.PySideUic.loadUi(":/panels/TaskAssemblyInsertLink.ui")
        self.form.installEventFilter(self)
        self.form.partList.installEventFilter(self)

        pref = Preferences.preferences()
        self.form.CheckBox_ShowOnlyParts.setChecked(pref.GetBool("InsertShowOnlyParts", False))
        self.form.CheckBox_RigidSubAsm.setChecked(pref.GetBool("InsertRigidSubAssemblies", True))

        # Actions
        self.form.openFileButton.clicked.connect(self.openFiles)
        self.form.partList.itemClicked.connect(self.onItemClicked)
        self.form.filterPartList.textChanged.connect(self.onFilterChange)
        self.form.CheckBox_ShowOnlyParts.stateChanged.connect(self.buildPartList)

        self.form.partList.header().hide()

        self.translation = 0
        # self.partMoving = False
        self.totalTranslation = App.Vector()
        self.prevScreenCenter = App.Vector()
        self.groundedObj = None

        self.insertionStack = []  # used to handle cancellation of insertions.
        self.doc_item_map = {}

        self.buildPartList()

        Gui.ActiveDocument.openCommand("Insert Component")

        # Listen for external deletions to keep the list in sync
        self.docObserver = InsertLinkObserver(self.onObjectDeleted)
        App.addDocumentObserver(self.docObserver)

    def accept(self):
        self.deactivated()

        Gui.addModule("UtilsAssembly")
        commands = "assembly = UtilsAssembly.activeAssembly()\n"
        for insertionItem in self.insertionStack:
            object = insertionItem["addedObject"]
            translation = insertionItem["translation"]

            # Check if object.Name & object.LinkedObject.Name exists
            if (
                not hasattr(object, "Name")
                or not hasattr(object, "LinkedObject")
                or not hasattr(object.LinkedObject, "Name")
            ):
                continue

            commands = commands + (
                f'item = assembly.newObject("App::Link", "{object.Name}")\n'
                f'item.LinkedObject = App.ActiveDocument.getObject("{object.LinkedObject.Name}")\n'
                f'item.Label = "{object.Label}"\n'
            )

            if translation != App.Vector():
                commands = commands + (
                    f"item.Placement.base = App.Vector({translation.x},"
                    f"{translation.y},"
                    f"{translation.z})\n"
                )

        # Ground the first item if that happened
        if self.groundedObj:
            commands = (
                commands
                + f'CommandCreateJoint.createGroundedJoint(App.ActiveDocument.getObject("{self.groundedObj.Name}"))\n'
            )

        Gui.doCommandSkip(commands[:-1])  # Get rid of last \n
        Gui.ActiveDocument.commitCommand()
        return True

    def reject(self):
        self.deactivated()

        Gui.ActiveDocument.abortCommand()
        return True

    def deactivated(self):
        if hasattr(self, "docObserver") and self.docObserver:
            App.removeDocumentObserver(self.docObserver)
            self.docObserver = None

        pref = Preferences.preferences()
        pref.SetBool("InsertShowOnlyParts", self.form.CheckBox_ShowOnlyParts.isChecked())
        pref.SetBool("InsertRigidSubAssemblies", self.form.CheckBox_RigidSubAsm.isChecked())
        Gui.Selection.clearSelection()

    def buildPartList(self):
        self.form.partList.clear()
        self.doc_item_map.clear()

        docList = list(App.listDocuments().values())
        if len(docList) > 20:
            collapse = True
        else:
            collapse = False

        # FreeCAD-CH (ops#640 round 7, gap A16): with the typed tabs, this document first
        studioTabs = typedTabsOn()
        if studioTabs and self.doc in docList:
            docList.remove(self.doc)
            docList.insert(0, self.doc)

        for doc in docList:
            # Create a new tree item for the document
            docItem = QtGui.QTreeWidgetItem()
            itemName = doc.Label
            icon = QIcon.fromTheme("add", QIcon(":/icons/Document.svg"))
            if doc.Partial:
                itemName = (
                    itemName + " (" + QT_TRANSLATE_NOOP("Assembly_Insert", "Partially loaded") + ")"
                )
                icon = self.createDisabledIcon(icon)
            docItem.setText(0, itemName)
            docItem.setIcon(0, icon)
            self.doc_item_map[docItem] = doc

            if not any(
                (child.isDerivedFrom("Part::Feature") or child.isDerivedFrom("App::Part"))
                for child in doc.Objects
            ):
                continue  # Skip this doc if no relevant objects

            self.form.partList.addTopLevelItem(docItem)

            def process_objects(objs, item):
                onlyParts = self.form.CheckBox_ShowOnlyParts.isChecked()
                for obj in objs:
                    if obj == self.assembly:
                        continue  # Skip current assembly

                    if obj in self.assembly.InListRecursive:
                        continue  # Prevent dependency loop.
                        # For instance if asm1/asm2 with asm2 active, we don't want to have asm1 in the list

                    if not obj.ViewObject.ShowInTree and not self.showHidden:
                        continue

                    if UtilsAssembly.isMergedPart(obj):
                        continue  # FreeCAD-CH (ops#325): a part merged into another is in that one
                    if UtilsAssembly.isConsumedPart(obj):
                        continue  # FreeCAD-CH (ops#654 P6a): a Boolean consumed it (ghost part)

                    if (
                        obj.isDerivedFrom("Part::Feature")
                        or obj.isDerivedFrom("App::Part")
                        or obj.isDerivedFrom("App::DocumentObjectGroup")
                    ):
                        # Special handling for DocumentObjectGroup: only add if it contains relevant child objects
                        if obj.isDerivedFrom("App::DocumentObjectGroup"):
                            if not any(
                                (
                                    (not onlyParts and child.isDerivedFrom("Part::Feature"))
                                    or child.isDerivedFrom("App::Part")
                                )
                                for child in obj.ViewObject.claimChildrenRecursive()
                            ):
                                continue  # Skip this object if no relevant children

                        if obj.isDerivedFrom("Part::Feature"):
                            if onlyParts:
                                continue  # Ignore solids if we show only Parts

                        # Now add the object under the document item
                        objItem = QtGui.QTreeWidgetItem(item)
                        objItem.setText(0, obj.Label)
                        objItem.setIcon(
                            0, obj.ViewObject.Icon if hasattr(obj, "ViewObject") else QtGui.QIcon()
                        )  # Use object's icon if available

                        if not obj.isDerivedFrom("App::DocumentObjectGroup"):
                            objItem.setData(0, QtCore.Qt.UserRole, obj)

                        if obj.isDerivedFrom("App::Part") or obj.isDerivedFrom(
                            "App::DocumentObjectGroup"
                        ):
                            process_objects(obj.ViewObject.claimChildren(), objItem)

            guiDoc = Gui.getDocument(doc.Name)
            if studioTabs and doc == self.doc:
                self.addStudioItems(doc, docItem, guiDoc.TreeRootObjects, process_objects)
            else:
                process_objects(guiDoc.TreeRootObjects, docItem)
            if collapse:
                self.form.partList.collapseAll()
            else:
                self.form.partList.expandToDepth(0)

        self.adjustTreeWidgetSize()

    def addStudioItems(self, doc, docItem, rootObjects, process_objects):
        """FreeCAD-CH (ops#640 round 7, gap A16): this document's Part Studios first, by tab name
        and in tab order, each a row that inserts the whole studio (Onshape's "Insert entire Part
        Studio"), its parts below it; then the other root objects (assemblies...) as before.

        A studio that is an App::Part inserts as one link, which follows the studio. The implicit
        studio (the top level, "Part Studio 1" of an old file) is a heading only: its parts insert
        one by one, as before round 7 (R7A-3: a rigid group of per-part links wouldn't follow the
        parts added, deleted or moved later, as Onshape's whole-studio instance does; debt).

        A studio that uses the assembly (a part on a binder of the assembly's face) is not offered
        whole, as Insert skips such an object (R7A-2): the link would close a cycle. A heading with
        nothing left to insert below it is dropped."""
        users = self.assembly.InListRecursive
        listed = set()
        for name, kind, label in App.DocumentTabs.tabs(doc):
            if kind != "PartStudio":
                continue
            studioItem = QtGui.QTreeWidgetItem(docItem)
            studioItem.setText(0, label)
            if name == IMPLICIT_STUDIO:
                members = [obj for obj in rootObjects if App.DocumentTabs.tabOf(obj) == name]
                studioItem.setIcon(0, QIcon(":/icons/PartDesign_Body.svg"))
                process_objects(members, studioItem)
                listed.update(obj.Name for obj in members)
            else:
                studio = doc.getObject(name)
                studioItem.setIcon(0, studio.ViewObject.Icon)
                usesAssembly = studio in users or any(
                    obj in users for obj in studio.ViewObject.claimChildrenRecursive()
                )
                if not usesAssembly:
                    studioItem.setData(0, QtCore.Qt.UserRole, studio)
                process_objects(studio.ViewObject.claimChildren(), studioItem)
                listed.add(name)
            if studioItem.childCount() == 0 and not studioItem.data(0, QtCore.Qt.UserRole):
                docItem.removeChild(studioItem)
        process_objects([obj for obj in rootObjects if obj.Name not in listed], docItem)

    def adjustTreeWidgetSize(self):
        # Adjust the height of the part list based on item count
        item_count = 1

        def count_items(item):
            nonlocal item_count
            item_count += 1
            for i in range(item.childCount()):
                count_items(item.child(i))

        for i in range(self.form.partList.topLevelItemCount()):
            count_items(self.form.partList.topLevelItem(i))

        item_height = self.form.partList.sizeHintForRow(0)
        total_height = item_count * item_height
        max_height = 500

        self.form.partList.setMinimumHeight(min(total_height, max_height))

    def onFilterChange(self):
        filter_str = self.form.filterPartList.text().strip().lower()

        def filter_tree_item(item):
            # This function recursively filters items based on the filter string.
            item_text = item.text(0).lower()  # Assuming the relevant text is in the first column
            is_visible = filter_str in item_text if filter_str else True

            child_count = item.childCount()
            for i in range(child_count):
                child = item.child(i)
                child_is_visible = filter_tree_item(child)  # Recursively filter children
                is_visible = (
                    is_visible or child_is_visible
                )  # Parent is visible if any child matches

            item.setHidden(not is_visible)
            return is_visible

        root_count = self.form.partList.topLevelItemCount()
        for i in range(root_count):
            root_item = self.form.partList.topLevelItem(i)
            filter_tree_item(root_item)  # Filter from each root item

    def openFiles(self):
        selected_files, _ = QtGui.QFileDialog.getOpenFileNames(
            None,
            "Select FreeCAD documents to import parts from",
            "",
            "Supported Formats (*.FCStd *.fcstd);;All files (*)",
        )

        for filename in selected_files:
            requested_file = os.path.split(filename)[1]
            import_doc_is_open = any(
                requested_file == os.path.split(doc.FileName)[1]
                for doc in App.listDocuments().values()
            )

            if not import_doc_is_open:
                if filename.lower().endswith(".fcstd"):
                    App.openDocument(filename, True)
                    App.setActiveDocument(self.doc.Name)
                    self.buildPartList()

    def onItemClicked(self, item):
        selectedPart = item.data(0, QtCore.Qt.UserRole)
        if not selectedPart:
            # If there's no part associated, toggle the expanded state
            item.setExpanded(not item.isExpanded())
            return

        # check that the current document had been saved or that it's the same document as that of the selected part
        if not self.doc == selectedPart.Document:
            if self.doc.FileName == "":
                msgBox = QtWidgets.QMessageBox()
                msgBox.setIcon(QtWidgets.QMessageBox.Warning)
                msgBox.setText(
                    "The current document must be saved before inserting external parts."
                )
                msgBox.setWindowTitle("Save Document")
                saveButton = msgBox.addButton("Save", QtWidgets.QMessageBox.AcceptRole)
                cancelButton = msgBox.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)

                msgBox.exec_()

                if not (msgBox.clickedButton() == saveButton and Gui.ActiveDocument.saveAs()):
                    return

            # check that the selectedPart document is saved.
            if selectedPart.Document.FileName == "":
                msgBox = QtWidgets.QMessageBox()
                msgBox.setIcon(QtWidgets.QMessageBox.Warning)
                msgBox.setText("The selected object's document must be saved before inserting it.")
                msgBox.setWindowTitle("Save Document")
                saveButton = msgBox.addButton("Save", QtWidgets.QMessageBox.AcceptRole)
                cancelButton = msgBox.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)

                msgBox.exec_()

                if not (
                    msgBox.clickedButton() == saveButton
                    and selectedPart.ViewObject.Document.saveAs()
                ):
                    return

                # Update the document item text - useless because Document.Name still return 'Unnamed'
                """documentItem = item
                while documentItem.parent() is not None:
                    documentItem = documentItem.parent()
                newDocName = selectedPart.Document.Name
                print(selectedPart.Document.Name)
                documentItem.setText(0, f"{newDocName}.FCStd")"""

        self.insertLink(selectedPart, item)

    def insertLink(self, selectedPart, item):
        """Inserts a link to selectedPart for the list's row item and returns it."""
        if selectedPart.isDerivedFrom("Assembly::AssemblyObject"):
            objType = "Assembly::AssemblyLink"
        else:
            objType = "App::Link"

        addedObject = self.assembly.newObject(objType, selectedPart.Label)

        # set placement of the added object to the center of the screen.
        view = Gui.activeView()
        x, y = view.getSize()
        screenCenter = view.getPointOnFocalPlane(x // 2, y // 2)
        screenCorner = view.getPointOnFocalPlane(x, y)

        addedObject.LinkedObject = selectedPart
        addedObject.Label = selectedPart.Label  # non-ASCII characters fails with newObject. #12164
        if onshapeKeymap():
            # Onshape's instance name (ops#640 round 10)
            addedObject.Label = instanceLabel(self.assembly, selectedPart)
        addedObject.recompute()

        insertionDict = {}
        insertionDict["item"] = item
        insertionDict["addedObject"] = addedObject
        self.insertionStack.append(insertionDict)
        self.increment_counter(item)

        translation = App.Vector()
        resetThreshold = (screenCorner - screenCenter).Length * 0.1
        if len(self.insertionStack) == 1:
            translation = App.Vector()  # No translation for first object.
        elif (self.prevScreenCenter - screenCenter).Length > resetThreshold:
            self.totalTranslation = App.Vector()
            self.prevScreenCenter = screenCenter
        else:
            translation = self.getTranslationVec(addedObject)

        insertionDict["translation"] = translation
        self.totalTranslation += translation

        originX, originY = view.getPointOnViewport(App.Vector() + translation)
        if originX > 0 and originX < x and originY > 0 and originY < y:
            # If the origin is within view then we insert at the origin.
            addedObject.Placement.Base = self.totalTranslation
        else:
            #
            bboxCenter = addedObject.ViewObject.getBoundingBox().Center
            addedObject.Placement.Base = screenCenter - bboxCenter + self.totalTranslation

        self.prevScreenCenter = screenCenter

        # We turn it flexible after changing the position so that it uses the logic in
        # AssemblyLink::onChanged to handle positioning correctly.
        if selectedPart.isDerivedFrom("Assembly::AssemblyObject"):
            addedObject.Rigid = self.form.CheckBox_RigidSubAsm.isChecked()

        # highlight the link
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, addedObject.Name, "")

        item.setSelected(False)

        if len(self.insertionStack) == 1 and not UtilsAssembly.isAssemblyGrounded():
            self.handleFirstInsertion()

        return addedObject

    def handleFirstInsertion(self):
        # FreeCAD-CH (ops#640, rank 60; Onshape hands-on E4): the first instance is not fixed and
        # nothing asks: the joints solve without a grounded part (AssemblyObject::solve). Toggle
        # Grounded fixes a part; the preference's 'Always' still grounds the first one.
        pref = Preferences.preferences()
        fixPart = pref.GetInt("GroundFirstPart", 0) == 1

        if fixPart:
            # Create groundedJoint.
            if len(self.insertionStack) != 1:
                return

            targetObj = self.insertionStack[0]["addedObject"]

            # If the object is a flexible AssemblyLink, we should ground its internal 'base' part
            if targetObj.isDerivedFrom("Assembly::AssemblyLink") and not targetObj.Rigid:
                linkedAsm = targetObj.LinkedObject
                if linkedAsm and hasattr(linkedAsm, "Group"):
                    srcGrounded = None
                    # Attempt to find the grounded joint in the source assembly
                    # We look for a joint where JointType is 'Grounded'
                    for obj in linkedAsm.InListRecursive:
                        if hasattr(obj, "ObjectToGround"):
                            srcGrounded = obj.ObjectToGround
                            break

                    # Search the sub-assembly group for the link pointing to the source grounded object
                    # Fallback to the first valid part if no grounded joint was found in source
                    candidate = None
                    for child in targetObj.Group:
                        if not candidate and (
                            child.isDerivedFrom("App::Link") or child.isDerivedFrom("Part::Feature")
                        ):
                            candidate = child

                        if (
                            srcGrounded
                            and hasattr(child, "LinkedObject")
                            and child.LinkedObject == srcGrounded
                        ):
                            candidate = child
                            break

                    if not candidate:  # Nothing to ground
                        return

                    targetObj = candidate

            self.groundedObj = targetObj
            self.groundedJoint = CommandCreateJoint.createGroundedJoint(self.groundedObj)

    def increment_counter(self, item):
        text = item.text(0)
        match = re.search(r"(\d+) inserted$", text)

        if match:
            # Counter exists, increment it
            counter = int(match.group(1)) + 1
            new_text = re.sub(r"\d+ inserted$", f"{counter} inserted", text)
        else:
            # Counter does not exist, add it
            new_text = f"{text} : 1 inserted"

        item.setText(0, new_text)

    def decrement_counter(self, item):
        text = item.text(0)
        match = re.search(r"(\d+) inserted$", text)

        if match:
            counter = int(match.group(1)) - 1
            if counter > 0:
                # Update the counter
                new_text = re.sub(r"\d+ inserted$", f"{counter} inserted", text)
            elif counter == 0:
                # Remove the counter part from the text
                new_text = re.sub(r" : \d+ inserted$", "", text)
            else:
                return

            item.setText(0, new_text)

    """def clickMouse(self, info):
        if info["Button"] == "BUTTON1" and info["State"] == "DOWN":
            Gui.Selection.clearSelection()
            if info["ShiftDown"]:
                # Create a new link and moves this one now
                addedObject = self.insertionStack[-1]["addedObject"]
                currentPos = addedObject.Placement.Base
                selectedPart = addedObject
                if addedObject.TypeId == "App::Link":
                    selectedPart = addedObject.LinkedObject

                addedObject = self.assembly.newObject("App::Link", selectedPart.Label)
                addedObject.LinkedObject = selectedPart
                addedObject.Placement.Base = currentPos

                insertionDict = {}
                insertionDict["translation"] = App.Vector()
                insertionDict["item"] = self.insertionStack[-1]["item"]
                insertionDict["addedObject"] = addedObject
                self.insertionStack.append(insertionDict)

            else:
                self.endMove()

        elif info["Button"] == "BUTTON2" and info["State"] == "DOWN":
            self.dismissPart()"""

    # Taskbox keyboard event handler
    def eventFilter(self, watched, event):

        if event.type() == QtCore.QEvent.ContextMenu and watched is self.form.partList:
            item = watched.itemAt(event.pos())

            if item:
                if item.parent() is None:
                    doc = self.doc_item_map.get(item)
                    if doc and doc.Partial:
                        menu = QtWidgets.QMenu()
                        load_action_text = QT_TRANSLATE_NOOP(
                            "Assembly_Insert", "Fully load document"
                        )
                        load_action = menu.addAction(load_action_text)
                        load_action.triggered.connect(lambda: self.fullyLoadDocument(doc))
                        menu.exec_(event.globalPos())
                        return True  # Event was handled

                # Iterate through the insertionStack in reverse
                for i in reversed(range(len(self.insertionStack))):
                    stack_item = self.insertionStack[i]

                    if stack_item["item"] == item:
                        obj = stack_item["addedObject"]

                        # ONLY remove the object from the document.
                        # The Observer (onObjectDeleted) will handle the rest.
                        if obj and obj.Document:
                            UtilsAssembly.removeObjAndChilds(obj)

                        return True
            else:
                menu = QtWidgets.QMenu()

                # Add the checkbox action
                showHiddenAction = QtWidgets.QAction("Show objects hidden in tree view", menu)
                showHiddenAction.setCheckable(True)
                showHiddenAction.setChecked(self.showHidden)

                # Connect the action to toggle `self.showHidden`
                showHiddenAction.toggled.connect(self.toggleShowHidden)
                menu.addAction(showHiddenAction)
                menu.exec_(event.globalPos())
                return True

        return super().eventFilter(watched, event)

    def fullyLoadDocument(self, doc_to_load):
        """Closes and re-opens a document to load it fully."""
        if not doc_to_load.FileName:
            return

        # Save UI state
        scrollbar = self.form.partList.verticalScrollBar()
        scroll_position = scrollbar.value()

        # Perform the reload
        App.open(doc_to_load.FileName)
        App.setActiveDocument(self.doc.Name)

        # Refresh the UI
        self.buildPartList()

        # Restore UI state
        scrollbar.setValue(scroll_position)

    def createDisabledIcon(self, icon):
        if icon.isNull():
            return QIcon()

        # Get a pixmap from the icon at a standard size
        pixmap = icon.pixmap(icon.actualSize(QtCore.QSize(16, 16)))

        # Ask the application's style to generate a disabled version of the pixmap
        style = QtWidgets.QApplication.style()
        disabled_pixmap = style.generatedIconPixmap(
            QtGui.QIcon.Disabled, pixmap, QtWidgets.QStyleOption()
        )

        return QIcon(disabled_pixmap)

    def toggleShowHidden(self, checked):
        self.showHidden = checked
        self.buildPartList()

    def getTranslationVec(self, part):
        bb = part.Shape.BoundBox
        if bb:
            translation = (bb.XMax + bb.YMax + bb.ZMax) * 0.15
        else:
            translation = 10
        return App.Vector(translation, translation, translation)

    def onObjectDeleted(self, obj):
        """
        Handles cleanup when an object is deleted (via Right Click OR Tree View).
        """
        # Iterate backwards to safely delete
        for i in reversed(range(len(self.insertionStack))):
            stack_item = self.insertionStack[i]

            if stack_item["addedObject"] == obj:
                # 1. Revert translation
                self.totalTranslation -= stack_item["translation"]

                # 2. Update UI counter
                item = stack_item["item"]
                self.decrement_counter(item)

                # 3. Handle Grounded Joint cleanup
                if self.groundedObj == obj:
                    if self.groundedJoint:
                        try:
                            # Remove the joint if it still exists
                            if self.groundedJoint.Document:
                                self.groundedJoint.Document.removeObject(self.groundedJoint.Name)
                        except Exception:
                            pass
                    self.groundedObj = None
                    self.groundedJoint = None

                # 4. Remove from stack
                del self.insertionStack[i]

                # 5. Clear selection
                if item:
                    item.setSelected(False)


if App.GuiUp:
    Gui.addCommand("Assembly_InsertLink", CommandInsertLink())
    Gui.addCommand("Assembly_Insert", CommandGroupInsert())
