// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <App/Application.h>
#include <Build/ForkIdentity.h>

namespace tests
{

static void initApplication()
{
    if (App::Application::GetARGC() == 0) {
        constexpr int argc = 1;
        std::array<const char*, argc> argv {"FreeCAD"};
        // FreeCAD-CH: the fork's own settings folder, never official FreeCAD's
        App::Application::Config()["ExeName"] = FCForkName;
        App::Application::init(argc, const_cast<char**>(argv.data()));  // NOLINT
    }
}

}  // namespace tests
