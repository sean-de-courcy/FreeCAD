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
#include <chrono>
#include <condition_variable>
#include <exception>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <QThread>

#include <BRepCheck_Analyzer.hxx>
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
    return App::GetApplication()
        .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/Part/General")
        ->GetFloat("GeometryTimeLimit", 60.0);
}

Scope::Scope()
{
    if (scopeDepth++ == 0) {
        outermost = true;
        scopeLimit = limit();
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

void run(const char* what, const std::function<void(const Message_ProgressRange&)>& work)
{
    if (onWorker) {
        // Inside a worker's own work: it runs under that worker's limit
        work(Message_ProgressRange());
        return;
    }
    const double seconds_ = scopeDepth > 0 ? scopeLimit : limit();
    if (seconds_ < 0) {
        // No worker: as before the time limit (to measure what the worker costs)
        work(Message_ProgressRange());
        return;
    }
    sweep();
    const Clock::time_point started = Clock::now();
    const bool limited = seconds_ > 0;
    const Clock::time_point deadline = scopeDepth > 0
        ? scopeDeadline
        : started
            + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds_));
    const std::string name = what ? what : "The geometry";
    auto timedOut = [&]() {
        return Base::CADKernelError(
            name + " took longer than " + seconds(seconds_)
            + " s, the time limit for one feature's geometry (Part preference GeometryTimeLimit), "
              "and was stopped: the feature is not built"
        );
    };
    auto stopped = [&]() {
        const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        return Base::CADKernelError(
            name + " was stopped with Esc after " + seconds(elapsed) + " s: the feature is not built"
        );
    };
    if (Base::Sequencer().wasCanceled()) {
        throw stopped();
    }
    if (limited && started >= deadline) {
        throw timedOut();
    }

    auto call = std::make_shared<Call>();
    call->work = work;
    QThread* thread = QThread::create([call]() { runWorker(call); });
    thread->setStackSize(workerStackSize);
    thread->start();

    bool timeout = false;
    bool cancelled = false;
    if (!waitFor(call, std::chrono::milliseconds(150))) {
        // Long enough to show: a progress bar of its own when no recompute shows one
        std::unique_ptr<Base::SequencerLauncher> launcher;
        if (!Base::Sequencer().isRunning()) {
            launcher = std::make_unique<Base::SequencerLauncher>((name + "...").c_str(), 0);
        }
        size_t step = 0;
        try {
            while (!waitFor(call, std::chrono::milliseconds(40))) {
                if (Base::Sequencer().wasCanceled()) {
                    cancelled = true;
                    break;
                }
                if (limited && Clock::now() >= deadline) {
                    timeout = true;
                    break;
                }
                // Repaints and reads Esc: the progress bar's filter passes nothing else
                if (launcher) {
                    launcher->setProgress(++step);
                }
                else {
                    Base::Sequencer().checkAbort();
                }
            }
        }
        catch (const Base::AbortException&) {
            // Esc confirmed in the bar's dialog (checkAbort())
            cancelled = true;
        }
    }

    if (timeout || cancelled) {
        call->cancel = true;
        // A boolean stops at its next check of the cancel: often soon
        if (waitFor(call, std::chrono::milliseconds(300))) {
            thread->wait();
            delete thread;
        }
        else {
            thread->setPriority(QThread::IdlePriority);
            Registry& reg = registry();
            std::lock_guard<std::mutex> lock(reg.mutex);
            reg.abandoned.push_back(thread);
            ++reg.total;
        }
        if (cancelled) {
            throw stopped();
        }
        throw timedOut();
    }
    thread->wait();
    delete thread;
    if (call->error) {
        std::rethrow_exception(call->error);
    }
}

bool isValid(const TopoDS_Shape& shape, const char* what)
{
    auto valid = std::make_shared<bool>(false);
    run(what, [shape, valid](const Message_ProgressRange& /*range*/) {
        *valid = BRepCheck_Analyzer(shape).IsValid() == Standard_True;
    });
    return *valid;
}

}  // namespace Part::KernelBudget
