// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include <vector>

#include <App/DocumentObserver.h>

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

/** FreeCAD-CH (ops#640, rank 2): the model shown as it is just before a feature of its Body, for
 * the edit of that feature (Onshape shows the part studio rolled back to a sketch while it is
 * edited, so the face picked is the one the user sees).
 *
 * The solid before the feature is shown, and every solid after it that is shown is hidden, both in the
 * scene only (PartDesignGui::ViewProvider::makeTemporaryVisible): no Visibility property changes,
 * so nothing goes into the document, its undo or the saved file. restore(), or the destructor,
 * puts back what it changed, unless the user has changed that object's visibility since.
 * Lists rank 8 (rank 32, the studio's edit roll-back) uses showBodyAt() for the other Bodies.
 */
class RollbackView
{
public:
    RollbackView() = default;
    RollbackView(const RollbackView&) = delete;
    RollbackView& operator=(const RollbackView&) = delete;
    ~RollbackView();

    /// Shows \a feature's Body rolled back to it; outside a Body nothing changes.
    void rollBackTo(App::DocumentObject* feature);
    /** FreeCAD-CH (ops#640 rank 32, lists plan 8): shows \a body as it is at its solid feature
     * \a solid (null: before its first one), for the edit of a member of another Body of its part
     * studio (Onshape rolls every part back to the feature edited): \a solid is shown, and every
     * solid of \a body after it that is shown is hidden, in the scene only, as rollBackTo().
     */
    void showBodyAt(PartDesign::Body* body, App::DocumentObject* solid);
    /// Puts the scene back as it was.
    void restore();
    /// The solid shown for the roll-back, or null (it was shown already, or there is none).
    App::DocumentObject* shownBase() const
    {
        return base.getObject();
    }
    /// The first solid after the feature hidden for the roll-back, or null.
    App::DocumentObject* hiddenAfter() const
    {
        return hidden.empty() ? nullptr : hidden.front().getObject();
    }

private:
    App::DocumentObjectT base;
    std::vector<App::DocumentObjectT> hidden;
};

}  // namespace PartDesignGui
