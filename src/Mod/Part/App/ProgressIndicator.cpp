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

#include <BRepCheck_Analyzer.hxx>
#include <BinTools.hxx>
#include <Message_ProgressRange.hxx>
#include <Message_ProgressScope.hxx>
#include <TopoDS_Shape.hxx>

#include <App/Application.h>
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

/// What the caller and the worker share; the worker frees the work's captures on its thread
struct Call
{
    std::mutex mutex;
    std::condition_variable finished;
    bool done {false};
    std::exception_ptr error;
    std::atomic<bool> cancel {false};
    std::function<void(const Message_ProgressRange&)> work;
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
    try {
        Handle(CancelIndicator) indicator = new CancelIndicator(call);
        call->work(indicator->Start());
    }
    catch (...) {
        call->error = std::current_exception();
    }
    // The work's captures (makers, shapes) are freed here, on this thread
    call->work = nullptr;
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
}  // namespace

double limit()
{
    const double value = App::GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/Part/General")
                             ->GetFloat("GeometryTimeLimit", 60.0);
    // A limit no feature reaches is none (and its deadline would overflow the clock)
    if (!std::isfinite(value) || value > 1e6) {
        return 0.0;
    }
    return value;
}

Scope::Scope()
{
    if (scopeDepth++ == 0) {
        outermost = true;
        scopeLimit = limit();
        scopeFired.clear();
        scopeDeadline = Clock::now()
            + std::chrono::duration_cast<Clock::duration>(
                            std::chrono::duration<double>(std::max(0.0, scopeLimit))
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
    return scopeDepth > 0 && !onWorker && scopeLimit > 0 && Clock::now() >= scopeDeadline;
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
        std::string(what ? what : "The geometry") + " could not start: the feature's geometry took longer than "
        + seconds(scopeLimit)
        + " s, the time limit for one feature's geometry (Part preference GeometryTimeLimit) already: "
          "the feature is not built"
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
    const Clock::time_point deadline = scopeDeadline;
    const std::string name = what ? what : "The geometry";
    const std::string limitText = seconds(seconds_)
        + " s, the time limit for one feature's geometry (Part preference GeometryTimeLimit)";
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
    if (limited && started >= deadline) {
        throw limitStop(Base::CADKernelError(
            name + " could not start: the feature's geometry took longer than " + limitText
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
                timeout = !cancelled && limited && Clock::now() >= deadline;
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
            name + " took longer than " + limitText + ", and was stopped: the feature is not built"
        ));
    }
    thread->wait();
    delete thread;
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
    run(what, [copy, valid](const Message_ProgressRange& /*range*/) {
        *valid = BRepCheck_Analyzer(copy).IsValid() == Standard_True;
    });
    return *valid;
}

}  // namespace Part::KernelBudget
