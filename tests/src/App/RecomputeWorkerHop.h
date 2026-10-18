// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A GUI's main-thread hop for tests (FreeCAD-CH ops#349): MainThreadSignal hooks that make the
// test's thread the main thread, and an emission of a document signal from the async recompute
// worker, inside its request, whose slots then run on the test's thread while the worker waits

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include <boost/scope_exit.hpp>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/MainThreadSignal.h>
#include <App/RecomputeThread.h>

namespace tests
{

/// While it lives, the constructing thread is the main thread to MainThreadSignal: an emission on
/// another thread queues its slots for it and waits, and pumpUntil() runs them
class MainThreadHopHooks
{
public:
    MainThreadHopHooks()
    {
        state().mainThread = std::this_thread::get_id();
        App::MainThreadSignalConfig::setHooks(&isMainThread, &invoke);
    }
    ~MainThreadHopHooks()
    {
        App::MainThreadSignalConfig::setHooks(nullptr, nullptr);
    }
    MainThreadHopHooks(const MainThreadHopHooks&) = delete;
    MainThreadHopHooks& operator=(const MainThreadHopHooks&) = delete;

    /// Runs the queued slots until done() holds; false at the time limit
    static bool pumpUntil(const std::function<bool()>& done, std::chrono::seconds limit)
    {
        const auto until = std::chrono::steady_clock::now() + limit;
        auto& s = state();
        while (!done()) {
            if (std::chrono::steady_clock::now() > until) {
                return false;
            }
            std::unique_lock lock(s.mutex);
            s.cv.wait_for(lock, std::chrono::milliseconds(5), [&] { return !s.queue.empty(); });
            while (!s.queue.empty()) {
                auto task = std::move(s.queue.front());
                s.queue.pop_front();
                lock.unlock();
                task->fn();
                lock.lock();
                task->done = true;
                s.cv.notify_all();
            }
        }
        return true;
    }

private:
    struct Task
    {
        std::function<void()> fn;
        bool done = false;
    };
    struct State
    {
        std::thread::id mainThread;
        std::mutex mutex;
        std::condition_variable cv;
        std::deque<std::shared_ptr<Task>> queue;
    };
    static State& state()
    {
        static State s;
        return s;
    }
    static bool isMainThread()
    {
        return std::this_thread::get_id() == state().mainThread;
    }
    static void invoke(std::function<void()>&& fn, bool blocking)
    {
        auto& s = state();
        auto task = std::make_shared<Task>();
        task->fn = std::move(fn);
        std::unique_lock lock(s.mutex);
        s.queue.push_back(task);
        s.cv.notify_all();
        if (blocking) {
            s.cv.wait(lock, [&] { return task->done; });
        }
    }
};

/// Which request the worker is inside when it emits
enum class HopRequest
{
    /// A single-object request for an object in a second document: it sets no document's status
    OneObject,
    /// A document request for a second document
    AnotherDocument,
    /// A document request for the asked object's own document, emitted as its recompute starts
    /// (Recomputing set), as ContainerMoves (ops#342) asks when a container moved mid-recompute
    ThisDocument,
};

inline const char* hopRequestName(HopRequest request)
{
    switch (request) {
        case HopRequest::OneObject:
            return "OneObject";
        case HopRequest::AnotherDocument:
            return "AnotherDocument";
        case HopRequest::ThisDocument:
            return "ThisDocument";
    }
    return "";
}

/**
 * Emits doc.signalRecomputedObject(obj) from the async recompute worker inside a request, with
 * MainThreadHopHooks set: its slots run on this thread while the worker waits, as a GUI's do. On
 * Windows only an emission compiled outside FreeCADApp hops (ops#365): this one is. For the two
 * requests in a second document it comes from the request's callback (the worker is still inside
 * the request); for ThisDocument from a slot of doc.signalBeforeRecompute, which runs on the
 * worker on Windows and in its hop elsewhere.
 */
inline void emitFromTheWorkersRequest(
    HopRequest kind,
    App::Document& doc,
    const App::DocumentObject& obj
)
{
    auto& app = App::GetApplication();
    std::atomic<bool> emitted {false};
    std::atomic<bool> inRequest {false};
    auto emit = [&] {
        if (emitted) {
            return;
        }
        // The worker is inside its request: the GUI's poll from another thread doesn't walk
        inRequest = !App::runWhileRecomputeWorkerIdle([] {});
        // As inside Document::recompute(): the hop releases the GIL while it waits, so the
        // emitting thread holds it (the request's callback runs without it)
        Base::PyGILStateLocker gil;
        doc.signalRecomputedObject(obj);
        emitted = true;
    };

    const std::string otherName = app.getUniqueDocumentName("hop");
    auto other = app.newDocument(otherName.c_str(), "testUser");
    BOOST_SCOPE_EXIT_ALL(&)
    {
        app.closeDocument(otherName.c_str());
    };
    auto feature = other->addObject("App::FeatureTest", "Feature");
    ASSERT_TRUE(feature);
    feature->touch();

    App::RecomputeRequest request;
    fastsignals::scoped_connection starting;
    switch (kind) {
        case HopRequest::OneObject:
            request = App::RecomputeRequest::fromDocumentObject(*feature);
            break;
        case HopRequest::AnotherDocument:
            request = App::RecomputeRequest::fromDocument(*other, true);
            break;
        case HopRequest::ThisDocument:
            request = App::RecomputeRequest::fromDocument(doc, true);
            starting = doc.signalBeforeRecompute.connect([&](const App::Document&) { emit(); });
            break;
    }
    if (kind != HopRequest::ThisDocument) {
        request.callback = [&](App::RecomputeRequest&, App::RecomputeResult&) { emit(); };
    }
    ASSERT_TRUE(app.canRecomputeRequestOnWorker(request));

    MainThreadHopHooks hooks;
    app.queueRecomputeRequest(request);
    ASSERT_TRUE(MainThreadHopHooks::pumpUntil(
        [&] { return emitted.load(); },
        std::chrono::seconds(10)
    ));
    // Until the worker has left the request (its own emissions hop here too, off Windows)
    ASSERT_TRUE(MainThreadHopHooks::pumpUntil(
        [] { return App::runWhileRecomputeWorkerIdle([] {}); },
        std::chrono::seconds(10)
    ));
    EXPECT_TRUE(inRequest);
}

/// What a slot of signalRecomputedObject for obj saw in the worker's hop: whether it ran, whether
/// on this thread, and ask()'s answer there
struct AskedInTheHop
{
    bool ran = false;
    bool onThisThread = false;
    bool answer = false;
};

inline AskedInTheHop askInTheWorkersHop(
    HopRequest kind,
    App::Document& doc,
    const App::DocumentObject& obj,
    const std::function<bool()>& ask
)
{
    AskedInTheHop seen;
    const auto here = std::this_thread::get_id();
    fastsignals::scoped_connection connection =
        doc.signalRecomputedObject.connect([&](const App::DocumentObject& o) {
            if (&o == &obj && !seen.ran) {
                seen.ran = true;
                seen.onThisThread = std::this_thread::get_id() == here;
                seen.answer = ask();
            }
        });
    emitFromTheWorkersRequest(kind, doc, obj);
    return seen;
}

}  // namespace tests
