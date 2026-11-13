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

#include <array>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <Mod/Part/PartGlobal.h>

class Message_ProgressRange;
class TopoDS_Shape;
class TopoDS_Shell;
class BRepCheck_Shell;

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

/** The limit, in seconds of CPU time: "User parameter:BaseApp/Preferences/Mod/Part/General", float
 * "GeometryTimeLimit", default 300. 0 means no limit (Esc still works); a negative value runs the work
 * on the calling thread, as before the limit (no Esc), to measure what the worker costs.
 *
 * What counts (ruling c758, ops#743): the CPU time of the thread that runs the feature, since its
 * outermost Scope began, and of its workers, so other programs' load on the machine doesn't make a
 * feature fail that an idle machine builds. Work in OCCT's thread pool, which a worker waits for,
 * isn't counted: a backstop on the clock, wallBackstop times the limit, stops a hang there.
 */
PartExport double limit();

/** The memory ceiling, in GB (ops#640, breakthrough 3): the same group's float
 * "GeometryMemoryLimit", default 4; 0 or less means none. A feature (any Scope, time-limited or
 * not) whose geometry makes the process's memory grow by more since its outermost Scope began is
 * stopped as by the time limit, and fails with the growth in its error: at a run()'s wait (every
 * 40 ms), before a run() or a stopIfPastDeadline() step starts, and at the feature's end
 * (Scope::fired()). Never a warning only (decision 418): runOptional() throws for it. Outside a
 * Scope a run() has the ceiling for its own growth. A stopped call that doesn't read its cancel
 * runs on abandoned, and may grow on. Nor does the ceiling reach code no run() covers (a link
 * assignment, outside every feature). For those, in unattended runs: FREECAD_CH_MEMORY_ABORT_GB,
 * the whole process's hard stop, read four times a second by the Sampler's thread once a first
 * Sampler was made (a feature's recompute, or Part.kernelSampleBegin()); past it, the stack of the
 * thread that ran the last feature goes to stderr and the process ends with exit code 86. */
PartExport double memoryLimit();

/// The clock's backstop for a feature's geometry: this many times the limit()
constexpr double wallBackstop = 4.0;

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

/** As run(), for a check the result doesn't need (work on copies only): false, with nothing noted
 * as a stop, where the limit stopped it or it could not start; the caller warns. Esc and the
 * work's own errors throw as from run(). */
PartExport bool runOptional(
    const char* what,
    const std::function<void(const Message_ProgressRange&)>& work
);

/** An exact copy of the shape, its geometry included (a binary round trip, as a file saves it),
 * for work under run() that must not read the document's shapes. BRepBuilderAPI_Copy's copy isn't
 * exact: a valid B-spline face of a cut by a degenerate ellipsoid came out "unorientable" from it,
 * also with its geometry copied (kernel-4). Costs what the shape's size does. */
PartExport TopoDS_Shape exactCopy(const TopoDS_Shape& shape);

/** BRepCheck_Analyzer(shape).IsValid() under the limit, on an exact copy of the shape. */
PartExport bool isValid(const TopoDS_Shape& shape, const char* what = "Shape check");

/** BRepCheck_Analyzer(shape).IsValid(), in time that grows with the faces' holes and not with their
 * square (kernel-9, ops#640): OCCT 8.0.1's face check compares every two wires of a face, minutes
 * for a plate with thousands of holes. A face with many wires on a surface that isn't periodic is
 * checked as its outer wire with each hole, and with each two holes whose boxes in the surface's
 * parameters overlap (holes apart can't cross or nest); its solids' shells and solids by
 * BRepCheck_Shell and BRepCheck_Solid. Any other shape: BRepCheck_Analyzer itself. Runs here. */
PartExport bool checkValid(const TopoDS_Shape& shape);

/** check.Orientation() == BRepCheck_NoError, for the check of \a shell whose Closed() gave
 * BRepCheck_NoError, in time linear in the shell's edges (perf profile 3, ops#640): OCCT finds each
 * edge again in its other face by going through that face's edges, the square of a face's edges
 * for a plate with thousands of holes. True here, without OCCT's check, only where OCCT finds no
 * error: every face oriented (forward or reversed) and in the shell once, every use of an edge in
 * a face oriented, and every edge that isn't degenerated used once, twice in one face (a seam), or
 * once in each of two faces with opposite orientations. Anything else is OCCT's check.
 * FREECAD_CH_FAST_ORIENTATION: "off" (OCCT's check always), "verify" (both, an error logged where
 * the fast answer is true and OCCT's isn't; OCCT's answer returned). */
PartExport bool orientedConsistently(BRepCheck_Shell& check, const TopoDS_Shell& shell);

/** checkValid() of a result made from \a base by an operation that keeps what it doesn't touch
 * (a fillet or chamfer from its maker's input), narrowed to what it touched (perf profile 3, ruling
 * c753, ops#640): of the result's faces, those \a base doesn't have (the same TShape, orientation
 * and transform) and every face that shares a vertex with one of them are checked, as checkValid()
 * checks a face; the faces it shares with \a base, apart from those, are not checked again. Its
 * shells and solids are checked whole (BRepCheck_Shell, BRepCheck_Solid). A shape that isn't solids
 * only, or a null base: checkValid() of the whole. FREECAD_CH_NARROW_CHECK: "off" (the whole
 * BRepCheck_Analyzer, as before), "verify" (both, an error logged where they differ; the whole
 * check's answer returned). */
PartExport bool checkValidChanged(const TopoDS_Shape& shape, const TopoDS_Shape& base);

/** Whether this thread's feature (its outermost Scope) has a limit that has passed. A step on the
 * calling thread that can't be stopped, and that the result doesn't need (a refine, a check), is
 * skipped then, with a warning on the feature. */
PartExport bool pastDeadline();

/** Whether this thread runs a feature's recompute (inside a Scope, not on a worker). */
PartExport bool inScope();

/** For a step on the calling thread that can't be stopped and that the result needs (a repair):
 * throws Base::CADKernelError, noted as a stop for the feature (Scope::fired()), when the
 * feature's limit has passed. \a what names the step ("The repair of the shape"). */
PartExport void stopIfPastDeadline(const char* what);

/** Where a slow step's time goes (ops#640, breakthrough 1): the wall time this thread spends in
 * each phase, for Sampler's report. Inclusive: a phase inside another counts in both, and a phase
 * inside itself once. Cheap: two reads of the clock per outermost timer. */
enum class Phase
{
    Solve,       ///< SketchObject::solve()
    BuildShape,  ///< SketchObject::buildShape()
    Occt,        ///< run(): a long geometry call, waited for on this thread
    Check,       ///< isValid(), checkValid()
    Refine,      ///< TopoShape::makeElementRefine()
    ElementMap   ///< TopoShape::makeShapeWithElementMap()
};
constexpr int phaseCount = 6;
PartExport const char* phaseName(Phase phase);

class PartExport PhaseTimer
{
public:
    explicit PhaseTimer(Phase phase);
    ~PhaseTimer();
    PhaseTimer(const PhaseTimer&) = delete;
    PhaseTimer(PhaseTimer&&) = delete;
    PhaseTimer& operator=(const PhaseTimer&) = delete;
    PhaseTimer& operator=(PhaseTimer&&) = delete;

private:
    int index;
    bool outer;
    long long began {0};
};

/// One function in a Sampler's report: in how many of the samples it was on the stack
struct SampleFrame
{
    std::string name;
    int count {0};
};

/// What a Sampler saw
struct SampleReport
{
    /// Seconds on the clock from the Sampler's start to finish()
    double wall {0.0};
    /// Stacks taken (none below the delay)
    int samples {0};
    /// Functions by the samples they were on the stack in (each once per sample), most first;
    /// equal counts the deeper first. Left out: a function with nine tenths of its samples in
    /// one callee (it only passes on), and the frames below the
    /// Sampler's start (Windows)
    std::vector<SampleFrame> top;
    /// The innermost function of each sample, most first
    std::vector<SampleFrame> self;
    /// Seconds of each Phase on this thread meanwhile
    std::array<double, phaseCount> phases {};
};

/** Names a slow step's hot function (ops#640, breakthrough 1): past `delay` seconds on the clock,
 * a thread of its own samples the stack of the thread that made the Sampler every `period`
 * seconds (Windows: SuspendThread and the x64 unwinder; POSIX: SIGPROF and backtrace()), until
 * finish(). One Sampler runs at a time in the process: another made meanwhile isn't armed (its
 * report has the wall and phases only). Below the delay it costs about what making a thread
 * handle does. finish() names the functions (Windows: DbgHelp and the build's PDBs; POSIX:
 * dladdr(), exported symbols only), the first time a module is named it loads its symbols.
 * The outermost Scope makes one for every feature's recompute and logs its report past the
 * delay; FREECAD_CH_SAMPLER=off turns that off, a number of seconds sets its delay. */
class PartExport Sampler
{
public:
    static constexpr double defaultDelay = 10.0;
    static constexpr double defaultPeriod = 0.5;
    explicit Sampler(double delay = defaultDelay, double period = defaultPeriod);
    ~Sampler();
    bool armed() const
    {
        return ticket != 0;
    }
    /// Stops the sampling (once) and names the `top` functions found most
    SampleReport finish(int top = 10);
    Sampler(const Sampler&) = delete;
    Sampler(Sampler&&) = delete;
    Sampler& operator=(const Sampler&) = delete;
    Sampler& operator=(Sampler&&) = delete;

private:
    unsigned long long ticket {0};
    long long started {0};
    std::array<double, phaseCount> phasesAtStart {};
    bool finished {false};
};

/** A report as one line: "12.3 s, 24 samples; hot: f (100 %), g (96 %)...; phases: solve 4.1 s..." */
PartExport std::string describe(const SampleReport& report);

/** One deadline for every run() inside it, the outermost one's.  timeLimited: whether the
 * outermost one has the time limit; else Esc only, as outside any Scope. The limit is PartDesign
 * features' only (the coordinator's ruling, 11-11): a Part, Arch/BIM or other workbench's object
 * runs as long as it takes, as a script's call does (bimtests.TestArchCovering). */
class PartExport Scope
{
public:
    explicit Scope(bool timeLimited = true);
    ~Scope();
    /** The outermost Scope: why the limit or Esc stopped a run() inside it, else empty. The
     * feature then fails with it, whatever its code did with the exception (a script's feature
     * that catches it would otherwise pass a partial result, kernel-4) */
    std::string fired() const;
    Scope(const Scope&) = delete;
    Scope(Scope&&) = delete;
    Scope& operator=(const Scope&) = delete;
    Scope& operator=(Scope&&) = delete;

private:
    bool outermost {false};
    /// The outermost one's, past its delay its report goes to the log
    std::unique_ptr<Sampler> sampler;
};

/** Calls abandoned in this process that are still running, and all ever abandoned (for tests). */
PartExport int abandonedRunning();
PartExport int abandonedTotal();

}  // namespace Part::KernelBudget
