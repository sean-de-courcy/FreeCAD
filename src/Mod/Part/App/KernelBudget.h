// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                             *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 ****************************************************************************/

#pragma once

#include <functional>
#include <memory>

#include <Mod/Part/PartGlobal.h>

class Message_ProgressRange;
class TopoDS_Shape;

/** A time limit for the long geometry calls of a feature, with Esc (FreeCAD-CH, kernel safety S1).
 *
 * A fillet on a face with thousands of edges runs for minutes in OCCT, which has no way to stop it,
 * and a boolean polls a cancel only at a few points. run() makes such a call on a worker thread
 * while the calling thread waits: in the GUI the window keeps repainting (events pass through the
 * progress bar's filter, which lets only Esc through), Esc stops the call, and so does the time
 * limit. The feature then fails with a clear error; the document stays as before the feature.
 *
 * A stopped call can't be killed. It receives a cancel through its progress range (a boolean stops
 * at its next check). Work on copies (Inputs::Owned) is then abandoned: it runs on at idle priority
 * and frees what it holds when it ends. Work that reads the document's shapes (Inputs::Shared) is
 * waited for first. So the work must touch only what it owns: shapes captured by value, makers by
 * shared_ptr. Never a TopoShape (its element map and the document's string hasher), the Console,
 * Python or a document. The naming of the result is made by the caller afterwards.
 */
namespace Part::KernelBudget
{

/** The limit, in seconds: "User parameter:BaseApp/Preferences/Mod/Part/General", float
 * "GeometryTimeLimit", default 60. 0 means no limit (Esc still works); a negative value runs the work on
 * the calling thread, as before the limit (no Esc), to measure what the worker costs.
 */
PartExport double limit();

/** Runs work under the limit of the outermost Scope on this thread (a feature's recompute); outside
 * every Scope (a script, a command) there is no limit, only Esc.
 * @param what Names the operation in the error ("Fillet", "Cut", "Shape check"...)
 * @param work What the worker does, given the range to pass to OCCT's Build()
 * @throws Base::CADKernelError on a timeout or Esc; work's own exception otherwise
 */
/// What the work reads
enum class Inputs
{
    /// Only its own data (copies): abandoned 0.3 s after its cancel
    Owned,
    /// The document's shapes, read in place (a boolean, a draft): waited for after its cancel, as
    /// OCCT reads it at its own checks, up to 30 s; abandoned only then. An abandoned reader would
    /// race the redraw of the feature's pass-through, which meshes the same shapes
    Shared
};

PartExport void run(
    const char* what,
    const std::function<void(const Message_ProgressRange&)>& work,
    Inputs inputs = Inputs::Owned
);

/** BRepCheck_Analyzer(shape).IsValid() under the limit, on a copy of the shape's topology. */
PartExport bool isValid(const TopoDS_Shape& shape, const char* what = "Shape check");

/** One deadline for every run() inside it, the outermost one's. */
class PartExport Scope
{
public:
    Scope();
    ~Scope();
    Scope(const Scope&) = delete;
    Scope(Scope&&) = delete;
    Scope& operator=(const Scope&) = delete;
    Scope& operator=(Scope&&) = delete;

private:
    bool outermost {false};
};

/** Calls abandoned in this process that are still running, and all ever abandoned (for tests). */
PartExport int abandonedRunning();
PartExport int abandonedTotal();

}  // namespace Part::KernelBudget
