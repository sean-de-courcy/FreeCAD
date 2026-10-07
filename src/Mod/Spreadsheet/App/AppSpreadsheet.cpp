// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2002 Juergen Riegel <juergen.riegel@web.de>             *
 *   Copyright (c) 2015 Eivind Kvedalen <eivind@kvedalen.name>             *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>
#include <App/VariableLookup.h>

#include "Sheet.h"


namespace Spreadsheet
{
class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("Spreadsheet")
    {
        initialize("This module is the Spreadsheet module.");  // register with Python
    }

private:
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}
}  // namespace Spreadsheet

/* Python entry */
PyMOD_INIT_FUNC(Spreadsheet)
{
    Spreadsheet::PropertySpreadsheetQuantity::init();
    Spreadsheet::PropertyColumnWidths::init();
    Spreadsheet::PropertyRowHeights::init();
    Spreadsheet::PropertySheet::init();

    Spreadsheet::Sheet::init();
    Spreadsheet::SheetPython::init();

    // FreeCAD-CH (ops#152): a sheet's aliases are variables for `#name`. The alias map is read,
    // not the cell properties, so an alias resolves before the sheet's first execute.
    App::VariableLookup::registerProvider(
        Spreadsheet::Sheet::getClassTypeId(),
        [](const App::DocumentObject* obj, const std::string& name) {
            return !static_cast<const Spreadsheet::Sheet*>(obj)->getAddressFromAlias(name).empty();
        },
        [](const App::DocumentObject* obj) {
            return static_cast<const Spreadsheet::Sheet*>(obj)->getAliases();
        }
    );

    PyObject* mod = Spreadsheet::initModule();
    Base::Console().log("Loading Spreadsheet module... done\n");
    PyMOD_Return(mod);
}
