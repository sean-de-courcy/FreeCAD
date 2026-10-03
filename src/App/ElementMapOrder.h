// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

namespace Data
{

/** While one exists on this thread, ElementMap::getAll(), and so
 * ComplexGeoData::getElementMap(), lists an interned map's names in no particular order.
 *
 * getAll() sorts an interned map's names by their expansions, so that readers taking the first
 * of several matches pick the same element as in a plain map (ops#6). Callers that need no
 * order, such as a check of every name's form, skip that sort with this (ops#101). It is kept
 * out of ElementMap.h, which most of FreeCAD includes.
 */
class AppExport UnsortedElementMapScope
{
public:
    UnsortedElementMapScope();
    ~UnsortedElementMapScope();
    UnsortedElementMapScope(const UnsortedElementMapScope&) = delete;
    UnsortedElementMapScope& operator=(const UnsortedElementMapScope&) = delete;
    UnsortedElementMapScope(UnsortedElementMapScope&&) = delete;
    UnsortedElementMapScope& operator=(UnsortedElementMapScope&&) = delete;

    /// Whether one exists on this thread.
    static bool active();
};

}  // namespace Data
