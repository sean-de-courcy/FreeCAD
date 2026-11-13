// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
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

namespace SketcherGui
{

/** FreeCAD-CH (ops#640, hands-on C-4): a sketch tool that takes Enter in the 3D view (the
 * Fillet tool's previewed corner). ViewProviderSketch::keyPressed finds it on the active handler
 * by a cross-cast, so the tool's own header (with its controller's specialisations) stays in one
 * translation unit.
 */
class SketchEnterTarget
{
public:
    virtual ~SketchEnterTarget() = default;
    /// True while the tool waits for Enter
    virtual bool takesEnter() const = 0;
    /// Enter pressed: the tool acts on it. The handler may be gone after it.
    virtual void enterPressed() = 0;

protected:
    SketchEnterTarget() = default;
    SketchEnterTarget(const SketchEnterTarget&) = default;
    SketchEnterTarget& operator=(const SketchEnterTarget&) = default;
};

}  // namespace SketcherGui
