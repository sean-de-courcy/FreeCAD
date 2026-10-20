/***************************************************************************
 *   Copyright (c) 2023 Peter McB                                          *
 *   Copyright (c) 2013 Jürgen Riegel (FreeCAD@juergen-riegel.net)         *
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


#include <SMESH_Version.h>

#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <CXX/Extensions.hxx>

#include "FemAnalysis.h"
#include "FemConstraintBearing.h"
#include "FemConstraintContact.h"
#include "FemConstraintDisplacement.h"
#include "FemConstraintFixed.h"
#include "FemConstraintFluidBoundary.h"
#include "FemConstraintForce.h"
#include "FemConstraintGear.h"
#include "FemConstraintHeatflux.h"
#include "FemConstraintInitialTemperature.h"
#include "FemConstraintPlaneRotation.h"
#include "FemConstraintPressure.h"
#include "FemConstraintPulley.h"
#include "FemConstraintRigidBody.h"
#include "FemConstraintSpring.h"
#include "FemConstraintTemperature.h"
#include "FemConstraintTransform.h"
#include "FemMesh.h"
#include "FemMeshObject.h"
#include "FemMeshProperty.h"
#include "FemMeshPy.h"
#include "FemMeshShapeNetgenObject.h"
#include "FemMeshShapeObject.h"
#include "FemResultObject.h"
#include "FemSetElementNodesObject.h"
#include "FemSetElementsObject.h"
#include "FemSetFacesObject.h"
#include "FemSetGeometryObject.h"
#include "FemSetNodesObject.h"
#include "FemSolverObject.h"
#include "FemShapeExtension.h"
#include "HypothesisPy.h"
#include "WorkerExtension.h"

#ifdef FC_USE_VTK
# include <string>
# include <vtkLogger.h>
# include <vtkObjectFactory.h>
# include <vtkOutputWindow.h>
# include <vtkSmartPointer.h>

# include "FemPostFilter.h"
# include "FemPostFunction.h"
# include "FemPostPipeline.h"
# include "FemPostBranchFilter.h"
# include "PropertyPostDataObject.h"
#endif


namespace Fem
{
extern PyObject* initModule();
}

#ifdef FC_USE_VTK
namespace
{
/** Sends VTK's messages to the Console (ops#382). VTK's default output window on Windows,
 * vtkWin32OutputWindow, opens a window on the desktop for every VTK warning or error (e.g.
 * vtkSmoothPolyDataFilter's "No data to smooth!" on empty data). */
class FemVtkOutputWindow: public vtkOutputWindow
{
public:
    static FemVtkOutputWindow* New();
    vtkTypeMacro(FemVtkOutputWindow, vtkOutputWindow);

    void DisplayText(const char* text) override
    {
        if (!text) {
            return;
        }
        std::string msg(text);
        msg.erase(msg.find_last_not_of(" \t\r\n") + 1);
        if (msg.empty()) {
            return;
        }
        msg += '\n';
        switch (GetCurrentMessageType()) {
            case MESSAGE_TYPE_ERROR:
                Base::Console().developerError("VTK", "%s", msg.c_str());
                break;
            case MESSAGE_TYPE_WARNING:
            case MESSAGE_TYPE_GENERIC_WARNING:
                Base::Console().developerWarning("VTK", "%s", msg.c_str());
                break;
            default:
                Base::Console().log("VTK", "%s", msg.c_str());
                break;
        }
    }
};

vtkStandardNewMacro(FemVtkOutputWindow);

void forwardVtkMessagesToConsole()
{
    vtkOutputWindow::SetInstance(vtkSmartPointer<FemVtkOutputWindow>::New());
    // VTK's logger writes its errors and warnings to stderr as well: the Console has them now
    vtkLogger::SetStderrVerbosity(vtkLogger::VERBOSITY_OFF);
}
}  // namespace
#endif

/* Python entry */
PyMOD_INIT_FUNC(Fem)
{
    // load dependent module
    try {
        Base::Interpreter().loadModule("Part");
    }
    catch (const Base::Exception& e) {
        PyErr_SetString(PyExc_ImportError, e.what());
        PyMOD_Return(nullptr);
    }
    PyObject* femModule = Fem::initModule();
    Base::Console().log("Loading FEM module… done\n");

    // clang-format off
    Fem::StdMeshers_Arithmetic1DPy              ::init_type(femModule);
    Fem::StdMeshers_AutomaticLengthPy           ::init_type(femModule);
    Fem::StdMeshers_NotConformAllowedPy         ::init_type(femModule);
    Fem::StdMeshers_MaxLengthPy                 ::init_type(femModule);
    Fem::StdMeshers_LocalLengthPy               ::init_type(femModule);
    Fem::StdMeshers_QuadranglePreferencePy      ::init_type(femModule);
    Fem::StdMeshers_Quadrangle_2DPy             ::init_type(femModule);
    Fem::StdMeshers_MaxElementAreaPy            ::init_type(femModule);
    Fem::StdMeshers_Regular_1DPy                ::init_type(femModule);
    Fem::StdMeshers_UseExisting_1DPy            ::init_type(femModule);
    Fem::StdMeshers_UseExisting_2DPy            ::init_type(femModule);
    Fem::StdMeshers_CompositeSegment_1DPy       ::init_type(femModule);
    Fem::StdMeshers_Deflection1DPy              ::init_type(femModule);
    Fem::StdMeshers_LayerDistributionPy         ::init_type(femModule);
    Fem::StdMeshers_LengthFromEdgesPy           ::init_type(femModule);
    Fem::StdMeshers_MaxElementVolumePy          ::init_type(femModule);
#if SMESH_VERSION_MAJOR <= 9 && SMESH_VERSION_MINOR < 10
    Fem::StdMeshers_MEFISTO_2DPy                ::init_type(femModule);
#endif
    Fem::StdMeshers_NumberOfLayersPy            ::init_type(femModule);
    Fem::StdMeshers_NumberOfSegmentsPy          ::init_type(femModule);
    Fem::StdMeshers_Prism_3DPy                  ::init_type(femModule);
    Fem::StdMeshers_Projection_1DPy             ::init_type(femModule);
    Fem::StdMeshers_Projection_2DPy             ::init_type(femModule);
    Fem::StdMeshers_Projection_3DPy             ::init_type(femModule);
    Fem::StdMeshers_ProjectionSource1DPy        ::init_type(femModule);
    Fem::StdMeshers_ProjectionSource2DPy        ::init_type(femModule);
    Fem::StdMeshers_ProjectionSource3DPy        ::init_type(femModule);
    Fem::StdMeshers_QuadraticMeshPy             ::init_type(femModule);
    Fem::StdMeshers_RadialPrism_3DPy            ::init_type(femModule);
    Fem::StdMeshers_SegmentAroundVertex_0DPy    ::init_type(femModule);
    Fem::StdMeshers_SegmentLengthAroundVertexPy ::init_type(femModule);
    Fem::StdMeshers_StartEndLengthPy            ::init_type(femModule);
    Fem::StdMeshers_Hexa_3DPy                   ::init_type(femModule);

    // Add Types to module
    Base::Interpreter().addType(&Fem::FemMeshPy::Type,femModule,"FemMesh");


    // NOTE: To finish the initialization of our own type objects we must
    // call PyType_Ready, otherwise we run into a segmentation fault, later on.
    // This function is responsible for adding inherited slots from a type's base class.

    Fem::DocumentObject                       ::init();
    Fem::FeaturePython                        ::init();

    Fem::FemAnalysis                          ::init();
    Fem::FemAnalysisPython                    ::init();

    Fem::Constraint                           ::init();
    Fem::ConstraintPython                     ::init();

    Fem::ConstraintBearing                    ::init();
    Fem::ConstraintContact                    ::init();
    Fem::ConstraintDisplacement               ::init();
    Fem::ConstraintFixed                      ::init();
    Fem::ConstraintRigidBody                  ::init();
    Fem::ConstraintFluidBoundary              ::init();
    Fem::ConstraintForce                      ::init();
    Fem::ConstraintGear                       ::init();
    Fem::ConstraintHeatflux                   ::init();
    Fem::ConstraintInitialTemperature         ::init();
    Fem::ConstraintPlaneRotation              ::init();
    Fem::ConstraintPressure                   ::init();
    Fem::ConstraintPulley                     ::init();
    Fem::ConstraintTemperature                ::init();
    Fem::ConstraintTransform                  ::init();
    Fem::ConstraintSpring                     ::init();

    Fem::FemMesh                              ::init();
    Fem::FemMeshObject                        ::init();
    Fem::FemMeshObjectPython                  ::init();
    Fem::FemMeshShapeBaseObject               ::init();
    Fem::FemMeshShapeBaseObjectPython         ::init();
    Fem::FemMeshShapeObject                   ::init();
    Fem::FemMeshShapeNetgenObject             ::init();
    Fem::PropertyFemMesh                      ::init();

    Fem::FemResultObject                      ::init();
    Fem::FemResultObjectPython                ::init();

    Fem::FemSetObject                         ::init();
    Fem::FemSetElementNodesObject             ::init();
    Fem::FemSetElementsObject                 ::init();
    Fem::FemSetFacesObject                    ::init();
    Fem::FemSetGeometryObject                 ::init();
    Fem::FemSetNodesObject                    ::init();

    Fem::FemSolverObject                      ::init();
    Fem::FemSolverObjectPython                ::init();

    Fem::WorkerExtension                      ::init();
    Fem::WorkerExtensionPython                ::init();
    Fem::BoxExtension                         ::init();
    Fem::BoxExtensionPython                   ::init();
    Fem::CylinderExtension                    ::init();
    Fem::CylinderExtensionPython              ::init();
    Fem::SphereExtension                      ::init();
    Fem::SphereExtensionPython                ::init();
    Fem::PlaneExtension                       ::init();
    Fem::PlaneExtensionPython                 ::init();

#ifdef FC_USE_VTK
    forwardVtkMessagesToConsole();

    Fem::FemPostSmoothFilterExtension         ::init();

    Fem::FemPostObject                        ::init();
    Fem::FemPostGroupExtension                ::init();
    Fem::FemPostPipeline                      ::init();
    Fem::FemPostFilter                        ::init();
    Fem::FemPostBranchFilter                  ::init();
    Fem::FemPostCalculatorFilter              ::init();
    Fem::FemPostClipFilter                    ::init();
    Fem::FemPostContoursFilter                ::init();
    Fem::FemPostCutFilter                     ::init();
    Fem::FemPostDataAlongLineFilter           ::init();
    Fem::FemPostDataAtPointFilter             ::init();
    Fem::FemPostScalarClipFilter              ::init();
    Fem::FemPostWarpVectorFilter              ::init();

    Fem::FemPostFunction                      ::init();
    Fem::FemPostFunctionProvider              ::init();
    Fem::FemPostBoxFunction                   ::init();
    Fem::FemPostCylinderFunction              ::init();
    Fem::FemPostPlaneFunction                 ::init();
    Fem::FemPostSphereFunction                ::init();

    Fem::PropertyPostDataObject               ::init();

    Fem::PostFilterPython                     ::init();
#endif
    // clang-format on

    PyMOD_Return(femModule);
}
