// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2009 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include "PreCompiled.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <QThread>

#ifdef _WIN32
# ifndef NOMINMAX
#  define NOMINMAX
# endif
# ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
# endif
# include <windows.h>
#elif defined(__APPLE__)
# include <mach/mach.h>
# include <mach/thread_info.h>
# include <pthread.h>
# include <time.h>
#else
# include <pthread.h>
# include <time.h>
#endif

#include <initializer_list>

#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepCheck_Shell.hxx>
#include <BRepCheck_Solid.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BinTools.hxx>
#include <Bnd_Box2d.hxx>
#include <Geom_Surface.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_MapOfOrientedShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Wire.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Shell.hxx>
#include <Message_ProgressRange.hxx>
#include <Message_ProgressScope.hxx>
#include <TopoDS_Shape.hxx>

#include <App/Application.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>

#include "KernelBudget.h"
#include "ProgressIndicator.h"


using namespace Part;
/*!
  \code
  #include <XSControl_WorkSession.hxx>
  #include <Transfer_TransientProcess.hxx>

  STEPControl_Reader aReader;
  Handle(Message_ProgressIndicator) pi = new ProgressIndicator();

  aReader.ReadFile("myfile.stp");
  aReader.TransferRoots(pi->Start());

  \endcode
 */

ProgressIndicator::ProgressIndicator()
{
    progress = std::make_unique<Base::SequencerLauncher>("Processing...", 100);
}

ProgressIndicator::~ProgressIndicator()
{
    progress->stop();
}

void ProgressIndicator::Show(const Message_ProgressScope& theScope, const Standard_Boolean isForce)
{
    (void)isForce;
    const char* name = theScope.Name();
    progress->setText(name ? name : "Processing...");
    std::size_t current = static_cast<std::size_t>(100. * theScope.Value() / theScope.MaxValue());
    if (current != currentStep) {
        currentStep = current;
        progress->setProgress(currentStep);
    }
}

Standard_Boolean ProgressIndicator::UserBreak()
{
    return progress->wasCanceled();
}

void ProgressIndicator::Reset()
{}

// ---------------------------------------------------------------------------------------------
// FreeCAD-CH kernel safety S1: a time limit and Esc for a feature's long geometry calls
// (KernelBudget.h)

namespace Part::KernelBudget
{
namespace
{
using Clock = std::chrono::steady_clock;

#ifdef _WIN32
double fileTimeSeconds(const FILETIME& time)
{
    ULARGE_INTEGER value;
    value.LowPart = time.dwLowDateTime;
    value.HighPart = time.dwHighDateTime;
    return static_cast<double>(value.QuadPart) * 1e-7;  // 100 ns units
}

double threadTimes(HANDLE thread)
{
    FILETIME created, ended, kernel, user;
    if (!GetThreadTimes(thread, &created, &ended, &kernel, &user)) {
        return 0.0;
    }
    return fileTimeSeconds(kernel) + fileTimeSeconds(user);
}
#endif

/// The calling thread's own CPU time (user and kernel), in seconds; 0 where it can't be read
double ownCpuSeconds()
{
#ifdef _WIN32
    return threadTimes(GetCurrentThread());
#else
    timespec time {};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &time) != 0) {
        return 0.0;
    }
    return static_cast<double>(time.tv_sec) + static_cast<double>(time.tv_nsec) * 1e-9;
#endif
}

/// Another thread's CPU time, read while it runs: the worker opens it on itself (open()), the
/// caller reads it (seconds())
class ThreadCpuClock
{
public:
    ThreadCpuClock() = default;
    ThreadCpuClock(const ThreadCpuClock&) = delete;
    ThreadCpuClock& operator=(const ThreadCpuClock&) = delete;
    ThreadCpuClock(ThreadCpuClock&&) = delete;
    ThreadCpuClock& operator=(ThreadCpuClock&&) = delete;
    ~ThreadCpuClock()
    {
#ifdef _WIN32
        if (handle) {
            CloseHandle(handle);
        }
#endif
    }
    /// On the thread to read later
    void open()
    {
#ifdef _WIN32
        HANDLE own = nullptr;
        if (DuplicateHandle(
                GetCurrentProcess(),
                GetCurrentThread(),
                GetCurrentProcess(),
                &own,
                THREAD_QUERY_LIMITED_INFORMATION,
                FALSE,
                0
            )) {
            handle = own;
            ready.store(true, std::memory_order_release);
        }
#elif defined(__APPLE__)
        port = pthread_mach_thread_np(pthread_self());
        ready.store(port != MACH_PORT_NULL, std::memory_order_release);
#else
        ready.store(pthread_getcpuclockid(pthread_self(), &clock) == 0, std::memory_order_release);
#endif
    }
    /// From another thread, while the thread runs; 0 before open()
    double seconds() const
    {
        if (!ready.load(std::memory_order_acquire)) {
            return 0.0;
        }
#ifdef _WIN32
        return threadTimes(handle);
#elif defined(__APPLE__)
        thread_basic_info_data_t info {};
        mach_msg_type_number_t count = THREAD_BASIC_INFO_COUNT;
        if (thread_info(port, THREAD_BASIC_INFO, reinterpret_cast<thread_info_t>(&info), &count)
            != KERN_SUCCESS) {
            return 0.0;
        }
        return static_cast<double>(info.user_time.seconds + info.system_time.seconds)
            + static_cast<double>(info.user_time.microseconds + info.system_time.microseconds)
            * 1e-6;
#else
        timespec time {};
        if (clock_gettime(clock, &time) != 0) {
            return 0.0;
        }
        return static_cast<double>(time.tv_sec) + static_cast<double>(time.tv_nsec) * 1e-9;
#endif
    }

private:
    std::atomic<bool> ready {false};
#ifdef _WIN32
    HANDLE handle {nullptr};
#elif defined(__APPLE__)
    mach_port_t port {MACH_PORT_NULL};
#else
    clockid_t clock {};
#endif
};

/// What the caller and the worker share; the worker frees the work's captures on its thread
struct Call
{
    std::mutex mutex;
    std::condition_variable finished;
    bool done {false};
    std::exception_ptr error;
    std::atomic<bool> cancel {false};
    std::function<void(const Message_ProgressRange&)> work;
    // The worker's own CPU time: read through its clock while it runs, its total once it ends
    ThreadCpuClock clock;
    std::atomic<bool> ended {false};
    double cpuAtEnd {0.0};

    double cpuSeconds() const
    {
        if (ended.load(std::memory_order_acquire)) {
            return cpuAtEnd;
        }
        return clock.seconds();
    }
};

/// The worker's progress: no display (no GUI off the main thread), a cancel the caller sets
class CancelIndicator: public Message_ProgressIndicator
{
public:
    explicit CancelIndicator(std::shared_ptr<Call> call)
        : call(std::move(call))
    {}
    void Show(const Message_ProgressScope& /*theScope*/, const Standard_Boolean /*isForce*/) override
    {}
    Standard_Boolean UserBreak() override
    {
        return call->cancel.load() ? Standard_True : Standard_False;
    }

private:
    std::shared_ptr<Call> call;
};

/// Abandoned workers. Never destroyed: a worker may outlive every static at exit
struct Registry
{
    std::mutex mutex;
    std::vector<QThread*> abandoned;
    int total {0};
};

Registry& registry()
{
    static auto* instance = new Registry;
    return *instance;
}

/// Deletes the abandoned workers that have ended
void sweep()
{
    Registry& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    auto& list = reg.abandoned;
    for (auto it = list.begin(); it != list.end();) {
        if ((*it)->isFinished()) {
            (*it)->wait();
            delete *it;
            it = list.erase(it);
        }
        else {
            ++it;
        }
    }
}

thread_local int scopeDepth = 0;
thread_local double scopeLimit = 0.0;
// The limit is CPU time (ruling c758, ops#743): the calling thread's own since the outermost Scope
// began, and its workers' own. Other programs' load doesn't count. Neither does work in OCCT's
// thread pool, which a worker waits for: the wall clock's backstop stops a hang there
thread_local double scopeCpuStart = 0.0;
thread_local double scopeWorkerCpu = 0.0;
thread_local Clock::time_point scopeDeadline;
thread_local bool onWorker = false;
// Why the outermost Scope's limit or Esc stopped a call, where one did (the first)
thread_local std::string scopeFired;
// runOptional(): a stop by the limit is the caller's to report, and was it one
thread_local bool limitStopIsOptional = false;
thread_local bool limitStopped = false;

// Large: OCCT recurses deeply, and a secondary thread gets 512 KB on macOS by default
constexpr unsigned workerStackSize = 64U * 1024U * 1024U;

std::string seconds(double value)
{
    std::ostringstream text;
    text.precision(value < 10 ? 2 : 3);
    text << value;
    return text.str();
}

void runWorker(const std::shared_ptr<Call>& call)
{
    onWorker = true;
    call->clock.open();
    try {
        Handle(CancelIndicator) indicator = new CancelIndicator(call);
        call->work(indicator->Start());
    }
    catch (...) {
        call->error = std::current_exception();
    }
    // The work's captures (makers, shapes) are freed here, on this thread
    call->work = nullptr;
    call->cpuAtEnd = ownCpuSeconds();
    call->ended.store(true, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(call->mutex);
        call->done = true;
    }
    call->finished.notify_all();
}

bool waitFor(const std::shared_ptr<Call>& call, std::chrono::milliseconds time)
{
    std::unique_lock<std::mutex> lock(call->mutex);
    return call->finished.wait_for(lock, time, [&call]() { return call->done; });
}

/// The CPU time the outermost Scope on this thread has spent: this thread's since it began, and
/// its ended workers'
double scopeSpent()
{
    return std::max(0.0, ownCpuSeconds() - scopeCpuStart) + scopeWorkerCpu;
}

/// Whether the outermost Scope's limit has passed, with `running` CPU seconds of a worker still at
/// work, or the wall clock's backstop
bool scopeOverLimit(double running = 0.0)
{
    return scopeLimit > 0
        && (scopeSpent() + running >= scopeLimit || Clock::now() >= scopeDeadline);
}

/// The limit that has passed, for the error: the CPU time, or the wall clock's backstop
std::string limitText()
{
    // The computing time first: where both have passed, the work computed past its limit
    if (scopeSpent() < scopeLimit && Clock::now() >= scopeDeadline) {
        return seconds(wallBackstop * scopeLimit) + " s on the clock, " + seconds(wallBackstop)
            + " times the time limit for one feature's geometry (Part preference GeometryTimeLimit, "
            + seconds(scopeLimit) + " s of computing time)";
    }
    return seconds(scopeLimit)
        + " s of computing time, the time limit for one feature's geometry (Part preference "
          "GeometryTimeLimit)";
}
}  // namespace

double limit()
{
    const double value = App::GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/Part/General")
                             ->GetFloat("GeometryTimeLimit", 300.0);
    // A limit no feature reaches is none (and its deadline would overflow the clock)
    if (!std::isfinite(value) || value > 1e6) {
        return 0.0;
    }
    return value;
}

Scope::Scope(bool timeLimited)
{
    if (scopeDepth++ == 0) {
        outermost = true;
        // Unlimited: no deadline but Esc (0), or no worker at all when the preference is negative,
        // as a call outside any Scope (run())
        scopeLimit = timeLimited ? limit() : std::min(limit(), 0.0);
        scopeFired.clear();
        scopeCpuStart = ownCpuSeconds();
        scopeWorkerCpu = 0.0;
        scopeDeadline = Clock::now()
            + std::chrono::duration_cast<Clock::duration>(
                            std::chrono::duration<double>(wallBackstop * std::max(0.0, scopeLimit))
            );
    }
}

Scope::~Scope()
{
    --scopeDepth;
}

std::string Scope::fired() const
{
    return outermost ? scopeFired : std::string();
}

bool pastDeadline()
{
    return scopeDepth > 0 && !onWorker && scopeOverLimit();
}

bool inScope()
{
    return scopeDepth > 0 && !onWorker;
}

void stopIfPastDeadline(const char* what)
{
    if (!pastDeadline()) {
        return;
    }
    Base::CADKernelError error(
        std::string(what ? what : "The geometry")
        + " could not start: the feature's geometry took longer than " + limitText()
        + " already: the feature is not built"
    );
    if (scopeFired.empty()) {
        scopeFired = error.what();
    }
    throw error;
}

int abandonedRunning()
{
    sweep();
    Registry& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    return static_cast<int>(reg.abandoned.size());
}

int abandonedTotal()
{
    Registry& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
    return reg.total;
}

namespace
{
#ifndef _WIN32
/** At exit, a worker still inside OCCT would meet OCCT's, Qt's and FreeCAD's static destructors
 * (Windows ends the other threads before its DLLs' destructors run; Linux and macOS don't): the
 * workers get a cancel and a moment, and if one still runs, the process ends without destructors.
 */
void endAbandoned()
{
    Registry& reg = registry();
    const auto until = Clock::now() + std::chrono::seconds(2);
    for (;;) {
        {
            std::lock_guard<std::mutex> lock(reg.mutex);
            bool running = false;
            for (auto* thread : reg.abandoned) {
                running = running || !thread->isFinished();
            }
            if (!running) {
                return;
            }
        }
        if (Clock::now() >= until) {
            std::fflush(nullptr);
            std::_Exit(EXIT_SUCCESS);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
}
#endif

void abandon(QThread* thread)
{
    thread->setPriority(QThread::IdlePriority);
    Registry& reg = registry();
    std::lock_guard<std::mutex> lock(reg.mutex);
#ifndef _WIN32
    static const bool registered = std::atexit(endAbandoned) == 0;
    (void)registered;
#endif
    reg.abandoned.push_back(thread);
    ++reg.total;
}

/// Keeps the GUI repainting and reads Esc while the worker runs; true when the worker ended
bool waitProcessing(
    const std::shared_ptr<Call>& call,
    std::unique_ptr<Base::SequencerLauncher>& launcher,
    const std::string& name,
    size_t& step,
    const std::function<bool()>& stop
)
{
    if (!launcher && !Base::Sequencer().isRunning()) {
        // Its own progress bar when no recompute shows one
        launcher = std::make_unique<Base::SequencerLauncher>((name + "...").c_str(), 0);
    }
    while (!waitFor(call, std::chrono::milliseconds(40))) {
        if (stop()) {
            return false;
        }
        // Repaints and reads Esc: the progress bar's filter passes nothing else
        if (launcher) {
            launcher->setProgress(++step);
        }
        else if (!Base::Sequencer().wasCanceled()) {
            Base::Sequencer().checkAbort();
        }
    }
    return true;
}

// How long a worker that reads the document's own shapes is waited for after its cancel: it is
// abandoned only after this (OCCT reads the cancel at its own checks), since the document's
// shapes change after the feature fails (its pass-through is redrawn and meshed)
constexpr auto sharedGrace = std::chrono::seconds(30);
}  // namespace

void run(const char* what, const std::function<void(const Message_ProgressRange&)>& work, Inputs inputs)
{
    if (onWorker) {
        // Inside a worker's own work: it runs under that worker's limit
        work(Message_ProgressRange());
        return;
    }
    // A feature's limit; outside one (a script, a command), no limit but Esc
    const double seconds_ = scopeDepth > 0 ? scopeLimit : std::min(limit(), 0.0);
    if (seconds_ < 0) {
        // No worker: as before the time limit (to measure what the worker costs)
        work(Message_ProgressRange());
        return;
    }
    sweep();
    const Clock::time_point started = Clock::now();
    const bool limited = seconds_ > 0;
    const std::string name = what ? what : "The geometry";
    // Noted for the feature: whatever its code does with the exception, it fails (kernel-4)
    auto fire = [](Base::CADKernelError error) {
        if (scopeDepth > 0 && scopeFired.empty()) {
            scopeFired = error.what();
        }
        return error;
    };
    auto limitStop = [&fire](Base::CADKernelError error) {
        limitStopped = true;
        return limitStopIsOptional ? error : fire(error);
    };
    auto stopped = [&]() {
        const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        return fire(Base::CADKernelError(
            name + " was stopped with Esc after " + seconds(elapsed) + " s: the feature is not built"
        ));
    };
    if (Base::Sequencer().wasCanceled()) {
        throw stopped();
    }
    if (limited && scopeOverLimit()) {
        throw limitStop(Base::CADKernelError(
            name + " could not start: the feature's geometry took longer than " + limitText()
            + " already: the feature is not built"
        ));
    }

    auto call = std::make_shared<Call>();
    call->work = work;
    QThread* thread = QThread::create([call]() { runWorker(call); });
    thread->setStackSize(workerStackSize);
    thread->start();

    bool timeout = false;
    bool cancelled = false;
    std::unique_ptr<Base::SequencerLauncher> launcher;
    size_t step = 0;
    if (!waitFor(call, std::chrono::milliseconds(150))) {
        try {
            waitProcessing(call, launcher, name, step, [&]() {
                cancelled = Base::Sequencer().wasCanceled();
                timeout = !cancelled && limited && scopeOverLimit(call->cpuSeconds());
                return cancelled || timeout;
            });
        }
        catch (const Base::AbortException&) {
            // Esc confirmed in the bar's dialog (checkAbort())
            cancelled = true;
        }
    }

    if (timeout || cancelled) {
        call->cancel = true;
        bool ended = waitFor(call, std::chrono::milliseconds(300));
        if (!ended && inputs == Inputs::Shared) {
            // It reads the document's shapes: waited for until OCCT reads the cancel
            const auto until = Clock::now() + sharedGrace;
            try {
                ended = waitProcessing(call, launcher, name + " (stopping)", step, [&]() {
                    return Clock::now() >= until;
                });
            }
            catch (const Base::AbortException&) {
                ended = waitFor(call, sharedGrace);
            }
        }
        if (scopeDepth > 0) {
            scopeWorkerCpu += call->cpuSeconds();
        }
        if (ended) {
            thread->wait();
            delete thread;
        }
        else {
            abandon(thread);
        }
        if (cancelled) {
            throw stopped();
        }
        throw limitStop(Base::CADKernelError(
            name + " took longer than " + limitText() + ", and was stopped: the feature is not built"
        ));
    }
    thread->wait();
    delete thread;
    if (scopeDepth > 0) {
        scopeWorkerCpu += call->cpuSeconds();
    }
    if (call->error) {
        std::rethrow_exception(call->error);
    }
}

bool runOptional(const char* what, const std::function<void(const Message_ProgressRange&)>& work)
{
    struct Restore
    {
        bool optional = limitStopIsOptional;
        ~Restore()
        {
            limitStopIsOptional = optional;
        }
    } restore;
    limitStopIsOptional = true;
    limitStopped = false;
    try {
        run(what, work, Inputs::Owned);
    }
    catch (const Base::CADKernelError&) {
        if (limitStopped) {
            limitStopped = false;
            return false;
        }
        throw;
    }
    return true;
}

TopoDS_Shape exactCopy(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return shape;
    }
    // Without triangulations: they are the redraw's, and the work doesn't read them
    std::stringstream stream(std::ios::in | std::ios::out | std::ios::binary);
    BinTools::Write(shape, stream, false, false, BinTools_FormatVersion_CURRENT);
    TopoDS_Shape copy;
    BinTools::Read(copy, stream);
    return copy;
}

bool isValid(const TopoDS_Shape& shape, const char* what)
{
    if (shape.IsNull()) {
        return false;
    }
    // A copy: an abandoned check reads nothing the document changes
    const TopoDS_Shape copy = exactCopy(shape);
    auto valid = std::make_shared<bool>(false);
    run(what, [copy, valid](const Message_ProgressRange& /*range*/) { *valid = checkValid(copy); });
    return *valid;
}

namespace
{
// A face checked by parts from this many wires on: below it OCCT's check of the whole face is as
// fast (a pocket's floor of 97 wires: 0.07 s whole, 0.4 s by single holes, kernel-9's profile)
constexpr int manyWires = 300;
// Holes checked together with the outer wire in one part: OCCT compares each two of them, so a
// batch checks more pairs than the boxes ask for, and the outer wire once per batch
constexpr std::size_t holesPerPart = 30;

int wireCount(const TopoDS_Face& face)
{
    int count = 0;
    for (TopoDS_Iterator it(face); it.More(); it.Next()) {
        ++count;
    }
    return count;
}

// Whether a face is checked by parts: many wires, every one a wire, on a surface that is neither
// periodic nor closed (no seams: the outer wire is one loop), without natural restriction
bool byParts(const TopoDS_Face& face)
{
    if (wireCount(face) < manyWires || BRep_Tool::NaturalRestriction(face)) {
        return false;
    }
    for (TopoDS_Iterator it(face); it.More(); it.Next()) {
        if (it.Value().ShapeType() != TopAbs_WIRE) {
            return false;
        }
    }
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    return !surface.IsNull() && !surface->IsUPeriodic() && !surface->IsVPeriodic()
        && !surface->IsUClosed() && !surface->IsVClosed();
}

// The face with only these wires: the same surface, location, tolerance and orientation, so the
// wires' edges find their curves on it as on the face
bool partValid(const TopoDS_Face& face, std::initializer_list<const TopoDS_Shape*> wires)
{
    TopoDS_Face part = TopoDS::Face(face.EmptyCopied());
    BRep_Builder builder;
    for (const TopoDS_Shape* wire : wires) {
        builder.Add(part, *wire);
    }
    return BRepCheck_Analyzer(part).IsValid() == Standard_True;
}

bool faceValidByParts(const TopoDS_Face& face)
{
    const TopoDS_Wire outer = BRepTools::OuterWire(face);
    if (outer.IsNull()) {
        return BRepCheck_Analyzer(face).IsValid() == Standard_True;
    }
    std::vector<TopoDS_Shape> holes;
    for (TopoDS_Iterator it(face); it.More(); it.Next()) {
        if (!it.Value().IsSame(outer)) {
            holes.push_back(it.Value());
        }
    }
    // The holes in batches with the outer wire: the holes' own checks, their orientation, inside
    // the outer wire, and each two holes of a batch
    for (std::size_t first = 0; first < holes.size(); first += holesPerPart) {
        TopoDS_Face part = TopoDS::Face(face.EmptyCopied());
        BRep_Builder builder;
        builder.Add(part, outer);
        for (std::size_t k = first; k < std::min(holes.size(), first + holesPerPart); ++k) {
            builder.Add(part, holes[k]);
        }
        if (BRepCheck_Analyzer(part).IsValid() != Standard_True) {
            return false;
        }
    }
    // Two holes whose boxes in the parameters overlap, each two once (a sweep along u): crossing
    // or nested holes overlap there. The margin, a millionth of the face's span, only adds pairs
    Bnd_Box2d all;
    BRepTools::AddUVBounds(face, all);
    double u0 = 0;
    double v0 = 0;
    double u1 = 0;
    double v1 = 0;
    all.Get(u0, v0, u1, v1);
    const double margin = 1e-6 * std::hypot(u1 - u0, v1 - v0) + 1e-9;
    struct Box
    {
        double u0, v0, u1, v1;
        std::size_t hole;
    };
    std::vector<Box> boxes;
    boxes.reserve(holes.size());
    for (std::size_t k = 0; k < holes.size(); ++k) {
        Bnd_Box2d box;
        BRepTools::AddUVBounds(face, TopoDS::Wire(holes[k]), box);
        if (box.IsVoid()) {
            return BRepCheck_Analyzer(face).IsValid() == Standard_True;
        }
        Box b {0, 0, 0, 0, k};
        box.Get(b.u0, b.v0, b.u1, b.v1);
        boxes.push_back({b.u0 - margin, b.v0 - margin, b.u1 + margin, b.v1 + margin, k});
    }
    std::sort(boxes.begin(), boxes.end(), [](const Box& a, const Box& b) { return a.u0 < b.u0; });
    for (std::size_t a = 0; a < boxes.size(); ++a) {
        for (std::size_t b = a + 1; b < boxes.size() && boxes[b].u0 <= boxes[a].u1; ++b) {
            if (boxes[b].v0 > boxes[a].v1 || boxes[a].v0 > boxes[b].v1
                || boxes[a].hole / holesPerPart == boxes[b].hole / holesPerPart) {
                continue;  // apart, or checked together in their batch
            }
            if (!partValid(face, {&outer, &holes[boxes[a].hole], &holes[boxes[b].hole]})) {
                return false;
            }
        }
    }
    return true;
}

bool statusOk(const Handle(BRepCheck_Result)& result)
{
    const auto& list = result->Status();
    return list.IsEmpty() || list.First() == BRepCheck_NoError;
}
}  // namespace

bool checkValid(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return false;
    }
    // By parts only for solids (alone or in compounds) with a face that has many wires, every
    // face in a shell and every shell in a solid; anything else as BRepCheck_Analyzer checks it
    bool anyByParts = false;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More() && !anyByParts; it.Next()) {
        anyByParts = byParts(TopoDS::Face(it.Current()));
    }
    const bool solidsOnly = TopExp_Explorer(shape, TopAbs_SHELL, TopAbs_SOLID).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SHELL).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_EDGE, TopAbs_FACE).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_VERTEX, TopAbs_EDGE).More() == Standard_False;
    const bool oneFace = shape.ShapeType() == TopAbs_FACE;
    if (!anyByParts || !(solidsOnly || oneFace)) {
        return BRepCheck_Analyzer(shape).IsValid() == Standard_True;
    }
    if (oneFace) {
        return faceValidByParts(TopoDS::Face(shape));
    }
    // Each face once (shared faces too), as the analyzer checks each sub-shape once
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    for (int k = 1; k <= faces.Extent(); ++k) {
        const TopoDS_Face& face = TopoDS::Face(faces(k));
        const bool valid = byParts(face) ? faceValidByParts(face)
                                         : BRepCheck_Analyzer(face).IsValid() == Standard_True;
        if (!valid) {
            return false;
        }
    }
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        Handle(BRepCheck_Solid) solidCheck = new BRepCheck_Solid(TopoDS::Solid(solid.Current()));
        if (!statusOk(solidCheck)) {
            return false;
        }
        for (TopExp_Explorer it(solid.Current(), TopAbs_SHELL); it.More(); it.Next()) {
            Handle(BRepCheck_Shell) shell = new BRepCheck_Shell(TopoDS::Shell(it.Current()));
            if (!statusOk(shell) || shell->Closed() != BRepCheck_NoError
                || !orientedConsistently(*shell, TopoDS::Shell(it.Current()))) {
                return false;
            }
        }
    }
    return true;
}

namespace
{
std::string fastOrientationMode()
{
#ifdef _MSC_VER
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, "FREECAD_CH_FAST_ORIENTATION") != 0 || !value) {
        return {};
    }
    std::string text(value);
    std::free(value);
    return text;
#else
    const char* value = std::getenv("FREECAD_CH_FAST_ORIENTATION");
    return value ? std::string(value) : std::string();
#endif
}

// True only where BRepCheck_Shell::Orientation() finds no error: it takes the faces as the shell's
// explorer gives them (keyed without orientation: a face twice is RedundantFace), and for each edge
// that isn't degenerated the faces that use it; with two faces, the edge's first use in each, an
// error where they agree; with one face (once, or twice as a seam) nothing; three or more uses are
// left to OCCT, as are unoriented faces and uses (which its edge map leaves out)
bool fastOriented(const TopoDS_Shell& shell)
{
    struct Use
    {
        int face {0};
        TopAbs_Orientation orientation {TopAbs_FORWARD};
    };
    struct Uses
    {
        int count {0};
        Use use[2];
    };
    TopTools_IndexedMapOfShape faces;
    TopTools_IndexedMapOfShape edges;
    std::vector<Uses> uses;
    for (TopExp_Explorer f(shell, TopAbs_FACE); f.More(); f.Next()) {
        const TopoDS_Shape& face = f.Current();
        if (face.Orientation() != TopAbs_FORWARD && face.Orientation() != TopAbs_REVERSED) {
            return false;
        }
        if (faces.Contains(face)) {
            return false;
        }
        const int faceIndex = faces.Add(face);
        for (TopExp_Explorer e(face, TopAbs_EDGE); e.More(); e.Next()) {
            const TopoDS_Shape& edge = e.Current();
            if (edge.Orientation() != TopAbs_FORWARD && edge.Orientation() != TopAbs_REVERSED) {
                return false;
            }
            const int k = edges.Add(edge);
            if (static_cast<std::size_t>(k) > uses.size()) {
                uses.resize(k);
            }
            Uses& u = uses[k - 1];
            if (u.count == 2) {
                return false;
            }
            u.use[u.count++] = {faceIndex, edge.Orientation()};
        }
    }
    for (int k = 1; k <= edges.Extent(); ++k) {
        const Uses& u = uses[k - 1];
        if (u.count < 2 || u.use[0].face == u.use[1].face) {
            continue;
        }
        if (BRep_Tool::Degenerated(TopoDS::Edge(edges(k)))) {
            continue;
        }
        if (u.use[0].orientation == u.use[1].orientation) {
            return false;
        }
    }
    return true;
}
}  // namespace

bool orientedConsistently(BRepCheck_Shell& check, const TopoDS_Shell& shell)
{
    const std::string mode = fastOrientationMode();
    if (mode == "off") {
        return check.Orientation() == BRepCheck_NoError;
    }
    const bool fast = fastOriented(shell);
    if (mode != "verify") {
        return fast || check.Orientation() == BRepCheck_NoError;
    }
    const bool occt = check.Orientation() == BRepCheck_NoError;
    if (fast && !occt) {
        Base::Console().error("fast orientation: true where BRepCheck_Shell finds an error\n");
    }
    return occt;
}


namespace
{
std::string narrowCheckMode()
{
#ifdef _MSC_VER
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, "FREECAD_CH_NARROW_CHECK") != 0 || !value) {
        return {};
    }
    std::string text(value);
    std::free(value);
    return text;
#else
    const char* value = std::getenv("FREECAD_CH_NARROW_CHECK");
    return value ? std::string(value) : std::string();
#endif
}

bool solidsOnly(const TopoDS_Shape& shape)
{
    return TopExp_Explorer(shape, TopAbs_SHELL, TopAbs_SOLID).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SHELL).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_EDGE, TopAbs_FACE).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_VERTEX, TopAbs_EDGE).More() == Standard_False
        && TopExp_Explorer(shape, TopAbs_SOLID).More() == Standard_True;
}

bool narrowValid(const TopoDS_Shape& shape, const TopoDS_Shape& base)
{
    if (base.IsNull() || !solidsOnly(shape)) {
        return checkValid(shape);
    }
    // The base's faces as its explorer gives them: with their orientation and transform
    TopTools_MapOfOrientedShape kept;
    for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
        kept.Add(it.Current());
    }
    // Each face once (shared faces too), as the analyzer checks each sub-shape once
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    std::vector<char> check(faces.Extent() + 1, 0);
    std::vector<int> changed;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        if (!kept.Contains(it.Current())) {
            const int k = faces.FindIndex(it.Current());
            if (!check[k]) {
                check[k] = 1;
                changed.push_back(k);
            }
        }
    }
    // Their neighbours: every face with a vertex of a changed face (those with an edge of it too)
    if (!changed.empty()) {
        TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
        TopExp::MapShapesAndAncestors(shape, TopAbs_VERTEX, TopAbs_FACE, vertexFaces);
        for (const int k : changed) {
            TopTools_IndexedMapOfShape vertices;
            TopExp::MapShapes(faces(k), TopAbs_VERTEX, vertices);
            for (int v = 1; v <= vertices.Extent(); ++v) {
                const int index = vertexFaces.FindIndex(vertices(v));
                if (index == 0) {
                    continue;
                }
                for (const auto& face : vertexFaces(index)) {
                    check[faces.FindIndex(face)] = 1;
                }
            }
        }
    }
    for (int k = 1; k <= faces.Extent(); ++k) {
        if (!check[k]) {
            continue;
        }
        const TopoDS_Face& face = TopoDS::Face(faces(k));
        const bool valid = byParts(face) ? faceValidByParts(face)
                                         : BRepCheck_Analyzer(face).IsValid() == Standard_True;
        if (!valid) {
            return false;
        }
    }
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        Handle(BRepCheck_Solid) solidCheck = new BRepCheck_Solid(TopoDS::Solid(solid.Current()));
        if (!statusOk(solidCheck)) {
            return false;
        }
        for (TopExp_Explorer it(solid.Current(), TopAbs_SHELL); it.More(); it.Next()) {
            Handle(BRepCheck_Shell) shell = new BRepCheck_Shell(TopoDS::Shell(it.Current()));
            if (!statusOk(shell) || shell->Closed() != BRepCheck_NoError
                || !orientedConsistently(*shell, TopoDS::Shell(it.Current()))) {
                return false;
            }
        }
    }
    return true;
}
}  // namespace

bool checkValidChanged(const TopoDS_Shape& shape, const TopoDS_Shape& base)
{
    if (shape.IsNull()) {
        return false;
    }
    const std::string mode = narrowCheckMode();
    if (mode == "off") {
        return BRepCheck_Analyzer(shape).IsValid() == Standard_True;
    }
    if (mode != "verify") {
        return narrowValid(shape, base);
    }
    const bool narrow = narrowValid(shape, base);
    const bool whole = BRepCheck_Analyzer(shape).IsValid() == Standard_True;
    if (narrow != whole) {
        Base::Console().error(
            "narrow check: %s where BRepCheck_Analyzer finds the shape %s\n",
            narrow ? "valid" : "invalid",
            whole ? "valid" : "invalid"
        );
    }
    return whole;
}

}  // namespace Part::KernelBudget
