// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// FreeCAD-CH ops#671 (notes/configurations-design.md 3.2, 3.6): two hooks a module installs so
// App core defers to a part studio's configurations without depending on the module.
//  - The expression write hook: PropertyExpressionEngine::setValue asks it first. It returns true
//    when it took the write (a configured path: the write becomes the active row's cell), throws
//    to refuse one (clearing a configured path), and false to let the write through.
//  - The reader check: an App::Link asks it on execute whether what it shows is the configuration
//    it was made with; a non-empty answer is the Link's error.

#include <functional>
#include <memory>
#include <string>

#include <FCGlobal.h>

namespace App
{

class DocumentObject;
class Expression;
class ObjectIdentifier;

using ExpressionWriteHook = std::function<
    bool(DocumentObject* owner, const ObjectIdentifier& path, const std::shared_ptr<Expression>& expr)>;
using ConfigReaderCheck = std::function<std::string(const DocumentObject* reader,
                                                    const DocumentObject* source)>;

/// Installs the expression write hook (one; a later call replaces it; an empty function removes it)
AppExport void setExpressionWriteHook(ExpressionWriteHook hook);
/// The hook's answer for a write of expr (null: a clear) to path of owner; false when none is set
AppExport bool callExpressionWriteHook(DocumentObject* owner,
                                       const ObjectIdentifier& path,
                                       const std::shared_ptr<Expression>& expr);

/// Installs the reader check (one; a later call replaces it)
AppExport void setConfigReaderCheck(ConfigReaderCheck check);
/// Why reader may not show source as it is now (empty: it may)
AppExport std::string callConfigReaderCheck(const DocumentObject* reader,
                                            const DocumentObject* source);

}  // namespace App
