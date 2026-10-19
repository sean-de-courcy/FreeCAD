// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileCopyrightText: 2026 Joao Matos
// SPDX-FileNotice: Part of the FreeCAD project.

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

#include <atomic>
#include <chrono>
#include <future>
#include <optional>
#include <thread>

#include <boost/scope_exit.hpp>
#include <gtest/gtest.h>

#include "App/Application.h"
#include "App/Document.h"
#include "App/FeatureTest.h"
#include <src/App/InitApplication.h>
#include <src/App/RecomputeWorkerHop.h>

using namespace std::chrono_literals;

class AsyncRecomputeTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("async_recompute");
        _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
    }

    void TearDown() override
    {
        if (!_docName.empty() && App::GetApplication().getDocument(_docName.c_str())) {
            App::GetApplication().closeDocument(_docName.c_str());
        }
    }

    std::string _docName;
    App::Document* _doc {};
};

TEST_F(AsyncRecomputeTest, CloseDocumentWaitsForInFlightAsyncRecompute)
{
    auto* object = dynamic_cast<App::FeatureTestAsyncBlocker*>(
        _doc->addObject("App::FeatureTestAsyncBlocker", "BlockingFeature")
    );
    ASSERT_NE(object, nullptr);

    App::FeatureTestAsyncBlocker::resetBlocker();
    BOOST_SCOPE_EXIT_ALL(&)
    {
        App::FeatureTestAsyncBlocker::releaseBlocker();
    };

    object->touch();

    App::GetApplication().queueRecomputeRequest(App::RecomputeRequest::fromDocumentObject(*object));

    ASSERT_TRUE(App::FeatureTestAsyncBlocker::waitUntilStarted(2s));

    auto closeFuture = std::async(std::launch::async, [this] {
        return App::GetApplication().closeDocument(_docName.c_str());
    });

    EXPECT_EQ(closeFuture.wait_for(50ms), std::future_status::timeout);

    App::FeatureTestAsyncBlocker::releaseBlocker();

    ASSERT_EQ(closeFuture.wait_for(2s), std::future_status::ready);
    EXPECT_TRUE(closeFuture.get());

    _doc = nullptr;
}

TEST_F(AsyncRecomputeTest, WorkerSafetyIsCheckedFromRequest)
{
    auto* safeObject = dynamic_cast<App::FeatureTest*>(
        _doc->addObject("App::FeatureTest", "SafeFeature")
    );
    auto* unsafeObject = dynamic_cast<App::FeatureTestAttribute*>(
        _doc->addObject("App::FeatureTestAttribute", "UnsafeFeature")
    );

    ASSERT_NE(safeObject, nullptr);
    ASSERT_NE(unsafeObject, nullptr);

    EXPECT_TRUE(
        App::GetApplication().canRecomputeRequestOnWorker(
            App::RecomputeRequest::fromDocumentObject(*safeObject)
        )
    );
    EXPECT_FALSE(
        App::GetApplication().canRecomputeRequestOnWorker(
            App::RecomputeRequest::fromDocumentObject(*unsafeObject)
        )
    );
    EXPECT_FALSE(
        App::GetApplication().canRecomputeRequestOnWorker(App::RecomputeRequest::fromDocument(*_doc))
    );
}

// A document signal emitted off the main thread runs its slots there while the emitting thread
// waits (MainThreadSignal's hop), whether the emitting thread holds the GIL or not, and a slot can
// take the GIL. A thread without it has none to release: the hop crashed in PyEval_SaveThread()
// (ops#349, PR 330 round 2; off Windows the worker's single-object recompute emits without it)
class MainThreadHopTest: public AsyncRecomputeTest, public ::testing::WithParamInterface<bool>
{};

TEST_P(MainThreadHopTest, AnEmissionOffTheMainThreadHops)
{
    const bool holdingTheGil = GetParam();
    auto* object = _doc->addObject("App::FeatureTest", "Feature");
    ASSERT_NE(object, nullptr);

    const auto here = std::this_thread::get_id();
    bool ran = false;
    bool onThisThread = false;
    bool tookTheGil = false;
    fastsignals::scoped_connection connection =
        _doc->signalRecomputedObject.connect([&](const App::DocumentObject& o) {
            if (&o == object) {
                ran = true;
                onThisThread = std::this_thread::get_id() == here;
                Base::PyGILStateLocker gil;
                tookTheGil = PyGILState_Check() != 0;
            }
        });

    tests::MainThreadHopHooks hooks;
    std::atomic<bool> emitted {false};
    std::thread emitter([&] {
        std::optional<Base::PyGILStateLocker> gil;
        if (holdingTheGil) {
            gil.emplace();
        }
        _doc->signalRecomputedObject(*object);
        emitted = true;
    });
    const bool inTime = tests::MainThreadHopHooks::pumpUntil(
        [&] { return emitted.load(); },
        std::chrono::seconds(10)
    );
    emitter.join();

    EXPECT_TRUE(inTime);
    EXPECT_TRUE(ran);
    EXPECT_TRUE(onThisThread);
    EXPECT_TRUE(tookTheGil);
}

INSTANTIATE_TEST_SUITE_P(
    Emitter,
    MainThreadHopTest,
    ::testing::Bool(),
    [](const ::testing::TestParamInfo<bool>& info) {
        return info.param ? "HoldingTheGil" : "WithoutTheGil";
    }
);

// The worker's own emissions hop too: Document::recompute(), compiled in FreeCADApp, emits
// signalRecomputedObject on the worker, and its slot runs on the main thread while the worker
// waits. On Windows FreeCADApp.dll had its own copy of the hooks, which setHooks from another
// library (Gui, or this test) never set, so the slot ran on the worker (ops#365)
TEST_F(AsyncRecomputeTest, TheWorkersEmissionsRunTheirSlotsOnTheMainThread)
{
    auto* object = _doc->addObject("App::FeatureTest", "Feature");
    ASSERT_NE(object, nullptr);
    object->touch();
    auto request = App::RecomputeRequest::fromDocument(*_doc, true);
    ASSERT_TRUE(App::GetApplication().canRecomputeRequestOnWorker(request));

    const auto here = std::this_thread::get_id();
    std::atomic<bool> ran {false};
    std::atomic<bool> onThisThread {false};
    std::atomic<bool> forTheWorker {false};
    fastsignals::scoped_connection connection =
        _doc->signalRecomputedObject.connect([&](const App::DocumentObject& o) {
            if (&o == object && !ran) {
                onThisThread = std::this_thread::get_id() == here;
                // Emitted by the worker: the hop carries its recompute (ops#349)
                forTheWorker = App::isRecomputeWorkerThread();
                ran = true;
            }
        });

    tests::MainThreadHopHooks hooks;
    App::GetApplication().queueRecomputeRequest(request);
    EXPECT_TRUE(tests::MainThreadHopHooks::pumpUntil(
        [&] { return ran.load() && App::runWhileRecomputeWorkerIdle([] {}); },
        std::chrono::seconds(10)
    ));

    EXPECT_TRUE(ran);
    EXPECT_TRUE(onThisThread);
    EXPECT_TRUE(forTheWorker);
}

// Closing a document while the worker waits in a hop for this thread: the close waits for the
// worker's request, so it runs the hops meanwhile, without the GIL, which the worker takes back
// after its hop. It waited without either, for a worker that waited for it (ops#365; before the
// fix only off Windows, where the hop happened)
TEST_F(AsyncRecomputeTest, CloseDocumentRunsTheWorkersHopsWhileItWaits)
{
    auto* object = _doc->addObject("App::FeatureTest", "Feature");
    ASSERT_NE(object, nullptr);
    object->touch();
    auto request = App::RecomputeRequest::fromDocument(*_doc, true);
    ASSERT_TRUE(App::GetApplication().canRecomputeRequestOnWorker(request));

    tests::MainThreadHopHooks hooks;
    App::GetApplication().queueRecomputeRequest(request);
    // The worker waits in its first hop (signalBeforeRecompute)
    ASSERT_TRUE(tests::MainThreadHopHooks::waitUntilQueued(10s));

    // A deadlocked close fails the test instead of hanging it: after a while another thread runs
    // the hops, and the worker finishes
    std::atomic<bool> closed {false};
    std::atomic<bool> rescued {false};
    std::thread watchdog([&] {
        const auto until = std::chrono::steady_clock::now() + 10s;
        while (!closed && std::chrono::steady_clock::now() < until) {
            std::this_thread::sleep_for(10ms);
        }
        if (!closed) {
            rescued = true;
            tests::MainThreadHopHooks::pumpUntil([&] { return closed.load(); }, 30s);
        }
    });
    {
        // As App.closeDocument() from Python
        Base::PyGILStateLocker gil;
        EXPECT_TRUE(App::GetApplication().closeDocument(_docName.c_str()));
    }
    closed = true;
    watchdog.join();
    _doc = nullptr;

    EXPECT_FALSE(rescued);
    EXPECT_TRUE(tests::MainThreadHopHooks::pumpUntil(
        [] { return App::runWhileRecomputeWorkerIdle([] {}); },
        std::chrono::seconds(10)
    ));
}

// A slot in the worker's hop can't close the document being recomputed: the close would wait for
// the request, which waits for the slot. It refuses instead (ops#365)
TEST_F(AsyncRecomputeTest, ASlotInTheWorkersHopCantCloseItsDocument)
{
    auto* object = _doc->addObject("App::FeatureTest", "Feature");
    ASSERT_NE(object, nullptr);
    object->touch();
    auto request = App::RecomputeRequest::fromDocument(*_doc, true);
    ASSERT_TRUE(App::GetApplication().canRecomputeRequestOnWorker(request));

    std::atomic<bool> ran {false};
    std::atomic<bool> refused {false};
    fastsignals::scoped_connection connection =
        _doc->signalRecomputedObject.connect([&](const App::DocumentObject& o) {
            if (&o == object && !ran) {
                ran = true;
                try {
                    App::GetApplication().closeDocument(_docName.c_str());
                }
                catch (const Base::RuntimeError&) {
                    refused = true;
                }
            }
        });

    tests::MainThreadHopHooks hooks;
    App::GetApplication().queueRecomputeRequest(request);
    EXPECT_TRUE(tests::MainThreadHopHooks::pumpUntil(
        [&] { return ran.load() && App::runWhileRecomputeWorkerIdle([] {}); },
        std::chrono::seconds(10)
    ));

    EXPECT_TRUE(ran);
    EXPECT_TRUE(refused);
    EXPECT_NE(App::GetApplication().getDocument(_docName.c_str()), nullptr);
}
