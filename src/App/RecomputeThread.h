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
#include <vector>

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

/**
 * Whether the calling thread is the async recompute worker (Application::recomputeWorker).
 *
 * Both this and isRecomputingOnThisThread() also answer for a thread running the slots of a
 * RecomputeHop, as they would on the thread that waits in it.
 */
AppExport bool isRecomputeWorkerThread();

/**
 * The recompute a thread is in, carried to the thread that runs a signal's slots for it while it
 * waits (FreeCAD-CH ops#349). MainThreadSignal makes one on the emitting thread before its
 * blocking hop to the GUI thread, and enters it there around the slots.
 *
 * The emitting thread changes nothing while it waits, so a slot's question is its question: a
 * slot of signalRecomputedObject that asks mustExecute() (PartDesign's ContainerMoves, ops#342)
 * walks as the worker does, where the poll beside the worker would answer "nothing moved".
 */
class AppExport RecomputeHop
{
public:
    /// On the emitting thread, before it blocks
    RecomputeHop();

    /// On the thread that runs the slots, while the emitting thread waits; nests
    class AppExport Scope
    {
    public:
        explicit Scope(const RecomputeHop& hop);
        ~Scope();
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;

    private:
        const RecomputeHop* previous;
    };

    /// The hop the calling thread runs slots of, or null (Application.cpp, Document.cpp)
    static const RecomputeHop* current();

    /// The emitting thread's: whether it is the worker, and the documents it is inside
    /// recompute() of (its own list, which it doesn't change while it waits)
    const bool worker;
    const std::vector<const Document*>* const recomputing;
};

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
