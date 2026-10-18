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

#include <functional>

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

/// Whether the calling thread is inside any document's Document::recompute() (ops#337).
AppExport bool isRecomputingOnThisThread();

/// Whether the calling thread is the async recompute worker (Application::recomputeWorker).
AppExport bool isRecomputeWorkerThread();

/**
 * Runs fn while the async recompute worker processes no request, for any document, and keeps it
 * from starting one until fn returns (ops#337). For a question asked beside the worker, such as
 * the GUI's Refresh poll of mustExecute(), that reads objects a worker recompute could change.
 *
 * Returns false without running fn when the worker is inside a request, or while another caller
 * runs one (a try-lock: the caller never waits). fn must not queue, cancel or wait for
 * recomputes, nor call runWhileRecomputeWorkerIdle again: the mutex isn't recursive, and a
 * try-lock by its owner is undefined (ops#352).
 */
AppExport bool runWhileRecomputeWorkerIdle(const std::function<void()>& fn);

}  // namespace App
