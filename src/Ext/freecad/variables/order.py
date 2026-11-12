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

"""A Variable Studio's rows: Move up / Move down and the type of a row (FreeCAD-CH, ops#640,
polish 13 P16 and P17).

Onshape's Variable Studio orders its variables, and the order matters: a variable may use only
those above it (VS Q5; App::VarSet::execute() fails a studio that breaks the rule). A VarSet's
dynamic properties have no order of their own: App::VarSet::VariableOrder holds it, and a move
rewrites it. The type of a row changes by taking the variable off and adding it again with the new
type, its group, description, status and value or expression carried over; VariableOrder keeps its
place. The users' expressions name the variables, not their places, and stay. Run inside one
transaction (the Variables panel's edit), so one undo step takes it back.
"""


def _snapshot(obj, name):
    expressions = dict(obj.ExpressionEngine)
    return {
        "name": name,
        "type": obj.getTypeIdOfProperty(name),
        "group": obj.getGroupOfProperty(name),
        "doc": obj.getDocumentationOfProperty(name),
        "status": obj.getPropertyStatus(name),
        "value": getattr(obj, name),
        "expression": expressions.get(name),
    }


def _restore(obj, row, type_=None):
    """Adds the row again; with @a type_ another type, its value or expression carried over."""
    name = row["name"]
    obj.addProperty(type_ or row["type"], name, row["group"], row["doc"])
    for status in row["status"]:
        if status in ("ReadOnly", "Hidden", "Output", "NoRecompute"):
            try:
                obj.setPropertyStatus(name, status)
            except Exception:
                pass
    if row["expression"] is not None:
        obj.setExpression(name, row["expression"])
        return
    try:
        setattr(obj, name, row["value"])
    except Exception:
        if type_ is None:
            raise
        # Another type that refuses the value as it is (10 mm in an Angle): kept as the value's
        # text in an expression, which then fails and shows the row invalid, as Onshape's VS4 keeps
        # what was typed and marks the cell; nothing is dropped silently
        value = row["value"]
        text = value.UserString if hasattr(value, "UserString") else str(value)
        if type_ == "App::PropertyString":
            setattr(obj, name, text)
        else:
            obj.setExpression(name, text)


def move(obj, order, name, offset):
    """Moves the variable @a name of @a obj up (@a offset -1) or down (+1) by one row; @a order:
    its variables in their order (the panel's rows, VarSet::getDynamicPropertyNames())."""
    order = list(order)
    if name not in order:
        raise ValueError("{} has no variable {}".format(obj.Label, name))
    i = order.index(name)
    j = i + offset
    if offset not in (-1, 1) or j < 0 or j >= len(order):
        raise ValueError("{} can't move there".format(name))
    order[i], order[j] = order[j], order[i]
    obj.VariableOrder = order


def retype(obj, order, name, type_):
    """Gives the variable @a name of @a obj the property type @a type_, in its place (@a order as
    for move())."""
    order = list(order)
    if name not in order:
        raise ValueError("{} has no variable {}".format(obj.Label, name))
    if obj.getTypeIdOfProperty(name) == type_:
        return
    row = _snapshot(obj, name)
    obj.VariableOrder = order  # its place, also where the order wasn't written yet
    obj.removeProperty(name)
    _restore(obj, row, type_)
