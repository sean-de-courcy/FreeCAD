// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Gui helpers for studio features (FreeCAD-CH ops#654, S3, S4, P6a): rows of the list, the
// roll-back to an owner's place while its dialog is open, the owner's preview without a Body.
// Free functions, so that slices change no header.

#include <string>
#include <vector>

#include <Mod/PartDesign/PartDesignGlobal.h>

class QWidget;

namespace App
{
class DocumentObject;
}

namespace PartDesign
{
class Body;
}

namespace PartDesignGui
{

class ViewProvider;

/// The parts offered as targets or tools at owner's place: live parts only (P6a, report 26)
PartDesignGuiExport std::vector<PartDesign::Body*> liveStudioParts(const App::DocumentObject* at);

/// Rolls the studio back to just before owner while its dialog is open (S4); false with why
PartDesignGuiExport bool rollStudioToOwner(App::DocumentObject* owner, std::string* why);

/// Ends rollStudioToOwner()
PartDesignGuiExport void endStudioOwnerRollBack(App::DocumentObject* owner);

/// The Result box of a studio feature's dialog (S4): New / Add / Remove / Intersect and a tick per
/// live part; null when vp's object is no studio feature
PartDesignGuiExport QWidget* makeStudioResultBox(ViewProvider* vp);

}  // namespace PartDesignGui
