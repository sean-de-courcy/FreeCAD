// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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


#include <CXX/Extensions.hxx>
#include <CXX/Objects.hxx>

#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>
#include <Gui/Application.h>
#include <Gui/ForkKeymap.h>
#include <Gui/Language/Translator.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Feature.h>
#include <functional>
#include <string>
#include <QString>

#include "Workbench.h"
#include "FeaturesView.h"
#include "ViewProviderBase.h"
#include "ViewProviderBody.h"
#include "ViewProviderBoolean.h"
#include "ViewProviderSplit.h"
#include "ViewProviderChamfer.h"
#include "ViewProviderDefeaturing.h"
#include "ViewProviderFacePattern.h"
#include "ViewProviderDatumCS.h"
#include "ViewProviderDatumLine.h"
#include "ViewProviderDatumPlane.h"
#include "ViewProviderDatumPoint.h"
#include "ViewProviderDraft.h"
#include "ViewProviderDressUp.h"
#include "ViewProviderFillet.h"
#include "ViewProviderGroove.h"
#include "ViewProviderHelix.h"
#include "ViewProviderHole.h"
#include "ViewProviderLinearPattern.h"
#include "ViewProviderLoft.h"
#include "ViewProviderMirrored.h"
#include "ViewProviderMultiTransform.h"
#include "ViewProviderPad.h"
#include "ViewProviderPipe.h"
#include "ViewProviderPocket.h"
#include "ViewProviderPolarPattern.h"
#include "ViewProviderCurvePattern.h"
#include "ViewProviderPrimitive.h"
#include "ViewProviderRevolution.h"
#include "ViewProviderScaled.h"
#include "ViewProviderShapeBinder.h"
#include "ViewProviderSketchBased.h"
#include "ViewProviderThickness.h"
#include "ViewProviderTransformed.h"
#include "ViewProviderStudioList.h"


// FreeCAD-CH (ops#640 round 8): declared where they are used (no header names them): the edit
// status banner's words (TaskView.cpp), and the plain status words (FeaturesView.cpp)
namespace App
{
class DocumentObject;
}
namespace Gui::TaskView
{
GuiExport void setEditStatusText(
    std::function<QString(const App::DocumentObject*, const QString&)> text
);
}
namespace Gui
{
// FreeCAD-CH (ops#640 polish P8): Onshape's double click in the 3D view (NavigationStyle.cpp)
GuiExport void setDoubleClickElement(
    std::function<void(const std::string&, const std::string&, const std::string&)> handler
);
}
namespace PartDesignGui
{
QString plainStatusText(const App::DocumentObject* obj, const QString& message);
}

// use a different name to CreateCommand()
void CreatePartDesignCommands();
void CreatePartDesignBodyCommands();
void CreatePartDesignPrimitiveCommands();
void CreatePartDesignReferenceCommands();

void loadPartDesignResource()
{
    // add resources and reloads the translators
    Q_INIT_RESOURCE(PartDesign);
    Q_INIT_RESOURCE(PartDesign_translation);
    Gui::Translator::instance()->refresh();
}

namespace PartDesignGui
{
class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("PartDesignGui")
    {
        initialize("This module is the PartDesignGui module.");  // register with Python
    }

private:
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}

}  // namespace PartDesignGui


/* Python entry */
PyMOD_INIT_FUNC(PartDesignGui)
{
    if (!Gui::Application::Instance) {
        PyErr_SetString(PyExc_ImportError, "Cannot load Gui module in console application.");
        PyMOD_Return(nullptr);
    }

    try {
        Base::Interpreter().runString("import PartGui");
        Base::Interpreter().runString("import SketcherGui");
    }
    catch (const Base::Exception& e) {
        PyErr_SetString(PyExc_ImportError, e.what());
        PyMOD_Return(nullptr);
    }

    PyObject* mod = PartDesignGui::initModule();
    Base::Console().log("Loading GUI of Part Design module… done\n");

    // instantiating the commands
    CreatePartDesignCommands();
    CreatePartDesignBodyCommands();
    CreatePartDesignPrimitiveCommands();
    CreatePartDesignReferenceCommands();

    // clang-format off
    PartDesignGui::Workbench                 ::init();
    PartDesignGui::ViewProvider              ::init();
    PartDesignGui::ViewProviderPython        ::init();
    PartDesignGui::ViewProviderBody          ::init();
    PartDesignGui::ViewProviderSketchBased   ::init();
    PartDesignGui::ViewProviderExtrude       ::init();
    PartDesignGui::ViewProviderPocket        ::init();
    PartDesignGui::ViewProviderHole          ::init();
    PartDesignGui::ViewProviderPad           ::init();
    PartDesignGui::ViewProviderRevolution    ::init();
    PartDesignGui::ViewProviderDressUp       ::init();
    PartDesignGui::ViewProviderGroove        ::init();
    PartDesignGui::ViewProviderChamfer       ::init();
    PartDesignGui::ViewProviderFillet        ::init();
    PartDesignGui::ViewProviderDefeaturing   ::init();
    PartDesignGui::ViewProviderFacePattern   ::init();  // FreeCAD-CH (ops#655 T8)
    PartDesignGui::ViewProviderDraft         ::init();
    PartDesignGui::ViewProviderThickness     ::init();
    PartDesignGui::ViewProviderTransformed   ::init();
    PartDesignGui::ViewProviderMirrored      ::init();
    PartDesignGui::ViewProviderLinearPattern ::init();
    PartDesignGui::ViewProviderPolarPattern  ::init();
    PartDesignGui::ViewProviderCurvePattern  ::init();
    PartDesignGui::ViewProviderScaled        ::init();
    PartDesignGui::ViewProviderMultiTransform::init();
    PartDesignGui::ViewProviderDatum         ::init();
    PartDesignGui::ViewProviderDatumPoint    ::init();
    PartDesignGui::ViewProviderDatumLine     ::init();
    PartDesignGui::ViewProviderDatumPlane    ::init();
    PartDesignGui::ViewProviderDatumCoordinateSystem::init();
    PartDesignGui::ViewProviderShapeBinder   ::init();
    PartDesignGui::ViewProviderSubShapeBinder::init();
    PartDesignGui::ViewProviderSubShapeBinderPython::init();
    PartDesignGui::ViewProviderBoolean       ::init();
    PartDesignGui::ViewProviderSplit         ::init();
    PartDesignGui::ViewProviderPrimitive     ::init();
    PartDesignGui::ViewProviderPipe          ::init();
    PartDesignGui::ViewProviderLoft          ::init();
    PartDesignGui::ViewProviderHelix         ::init();
    PartDesignGui::ViewProviderBase          ::init();
    PartDesignGui::ViewProviderStudioList    ::init();  // FreeCAD-CH ops#654
    // clang-format on

    // add resources and reloads the translators
    loadPartDesignResource();

    // Under the Onshape keymap a PartDesign feature's dialog banner, or its sketch's, says what
    // its rows' tooltips say (round 8; review R8-8: other objects keep their words)
    Gui::TaskView::setEditStatusText([](const App::DocumentObject* obj, const QString& text) {
        const bool ours = obj
            && (obj->isDerivedFrom<PartDesign::Feature>() || obj->isDerivedFrom<PartDesign::Body>()
                || PartDesign::Body::findBodyOf(obj));  // datums, binders, sketches in a Body
        return ours && Gui::ForkKeymap::isOnshape() ? PartDesignGui::plainStatusText(obj, text)
                                                    : text;
    });
    // FreeCAD-CH (ops#640 polish P8): under the Onshape keymap a double click on an element
    // tints the feature that made it, and its sketch, in the list and the view
    Gui::setDoubleClickElement(&PartDesignGui::FeaturesView::showCreatorOf);
    // FreeCAD-CH (ops#640 round 10): an Assembly tab's list in the Model panel
    PartDesignGui::FeaturesView::followTabs();

    PyMOD_Return(mod);
}
