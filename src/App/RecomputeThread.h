// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/

#pragma once

#include <FCGlobal.h>

namespace App
{

class Document;

/**
 * Whether the calling thread is inside doc's Document::recompute() (FreeCAD-CH ops#318).
 *
 * While a recompute runs on the worker thread, the GUI keeps asking objects mustExecute() from
 * the main thread (the Refresh command's state). An object whose answer reads other objects can
 * tell those calls, which run beside the recompute, from the recompute's own: the document is
 * Recomputing, and this is false.
 */
AppExport bool isRecomputingOnThisThread(const Document* doc);

}  // namespace App
