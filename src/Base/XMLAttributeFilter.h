// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCGlobal.h>

#include <functional>
#include <string>

namespace Base
{

class XMLReader;

/** Rewrites the attribute values that one XMLReader reads, while the filter lives.
 *
 * A document whose saved names need rewriting on load (interned names whose IDs collide in this
 * process, ops#6) installs one after it has read what the rewrite depends on: every attribute of
 * every element read afterwards passes through the function before anyone sees it. Filters are
 * per thread and must be destroyed in the reverse order of their construction.
 */
class BaseExport XMLAttributeFilter
{
public:
    using Function = std::function<void(std::string& value)>;

    XMLAttributeFilter(const XMLReader& reader, Function function);
    ~XMLAttributeFilter();
    XMLAttributeFilter(const XMLAttributeFilter&) = delete;
    XMLAttributeFilter& operator=(const XMLAttributeFilter&) = delete;
    XMLAttributeFilter(XMLAttributeFilter&&) = delete;
    XMLAttributeFilter& operator=(XMLAttributeFilter&&) = delete;

    /// True if any filter is active on this thread.
    static bool anyActive();
    /// Passes \a value through every filter active on this thread for \a reader.
    static void apply(const XMLReader& reader, std::string& value);

private:
    const XMLReader* _reader;
    Function _function;
    XMLAttributeFilter* _previous;
};

}  // namespace Base
