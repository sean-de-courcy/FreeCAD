// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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


#pragma once

#include <App/DocumentObject.h>
#include <Gui/ViewProviderFeaturePython.h>
#include <Gui/ViewProviderSuppressibleExtension.h>
#include <Mod/Part/Gui/ViewProvider.h>
#include <Mod/Part/Gui/ViewProviderAttachExtension.h>
#include <Mod/Part/Gui/ViewProviderPreviewExtension.h>
#include <Mod/PartDesign/App/Feature.h>

#include "ViewProviderBody.h"


namespace PartDesignGui
{

class TaskDlgFeatureParameters;

/**
 * A common base class for all part design features view providers
 */
class PartDesignGuiExport ViewProvider: public PartGui::ViewProviderPart,
                                        Gui::ViewProviderSuppressibleExtension,
                                        PartGui::ViewProviderAttachExtension,
                                        public PartGui::ViewProviderPreviewExtension
{
    using inherited = PartGui::ViewProviderPart;
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesignGui::ViewProvider);

public:
    /// constructor
    ViewProvider();
    /// destructor
    ~ViewProvider() override;

    void beforeDelete() override;
    void attach(App::DocumentObject* pcObject) override;

    bool doubleClicked() override;
    void onChanged(const App::Property* prop) override;

    Gui::ViewProvider* startEditing(int ModNum) override;

    void setTipIcon(bool onoff);

    // body mode means that the object is part of a body and that the body is used to set the
    // visual properties, not the features. Hence setting body mode to true will hide most
    // viewprovider properties.
    void setBodyMode(bool bodymode);

    // makes this viewprovider visible in the scene graph without changing any properties,
    // not the visibility one and also not the display mode. This can be used to show the
    // shape of this viewprovider from other viewproviders without doing anything to the
    // document and properties.
    void makeTemporaryVisible(bool);

    // Returns the ViewProvider of the body the feature belongs to, or NULL, if not in a body
    ViewProviderBody* getBodyViewProvider();

    void toggleVisibility() override;

    /// Toggles visibility of the preview
    void showPreviousFeature(bool);

    /// The preview overlay's opacity, 0..1: the Preview box's slider (ops#150 W5), saved in the
    /// preview parameters in percent; the theme's PreviewShapeOpacity until it is set.
    static double previewOpacity();
    /// A subtractive feature's tool shape: the theme's PreviewToolOpacity, scaled as
    /// previewOpacity() scales the theme's PreviewShapeOpacity.
    static double previewToolOpacity();
    /// Gives the preview shapes previewOpacity() (the tool shapes previewToolOpacity()).
    virtual void updatePreviewOpacity();

    PyObject* getPyObject() override;

    QIcon mergeColorfulOverlayIcons(const QIcon& orig) const override;

    /// Default implementation is a no-op; derived classes override if needed.
    /// Called on recompute and when any feature in the Body changes visibility.
    /// Serves as the entry point for ViewProviders that apply visual overlays
    /// (e.g. textures, highlights, thread visualization).
    virtual void updateOverlay() {};

protected:
    void setupContextMenu(QMenu* menu, QObject* receiver, const char* member) override;
    bool setEdit(int ModNum) override;
    void unsetEdit(int ModNum) override;
    /// Esc in the 3D view with a reference field armed disarms it, and the edit stays (ops#150).
    bool keyPressed(bool pressed, int key) override;

    void attachPreview() override;
    void updatePreview() override;

    /// Shows the claimed children, except those in keepHidden (ops#149)
    virtual void makeChildrenVisible(const std::vector<App::DocumentObject*>& keepHidden);
    bool onDelete(const std::vector<std::string>&) override;

    /**
     * Returns a newly create dialog for the part to be placed in the task view
     * Must be reimplemented in subclasses.
     */
    virtual TaskDlgFeatureParameters* getEditDialog();

    std::string oldWb;
    ViewProvider* previouslyShownViewProvider {nullptr};

    bool isSetTipIcon {false};

private:
    Gui::CoinPtr<PartGui::SoPreviewShape> pcToolPreview;
};

using ViewProviderPython = Gui::ViewProviderFeaturePythonT<ViewProvider>;

}  // namespace PartDesignGui
