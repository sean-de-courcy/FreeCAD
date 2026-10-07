// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH (ops#152): an expression's text as the GUI shows it, with references to variables as
// `#Name` (notes/variables-design.md section 8). For what the user reads or edits only: what is
// written back, recorded or copied out stays the stored text (Expression::toString()).
// Header only, so the modules' Gui code can use it without an export.

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <QString>

#include <App/VariableLookup.h>

namespace Gui
{

/// @a expr's text for an editor or a value text; empty for no expression.
inline QString expressionDisplayText(const App::Expression* expr)
{
    return expr ? QString::fromStdString(App::toDisplayString(expr)) : QString();
}

/// @a expr's text for a tooltip: as above, plus one line per name shortened, saying where it lives
/// (`#Width: VarSet.Width`).
inline QString expressionToolTipText(const App::Expression* expr)
{
    if (!expr) {
        return {};
    }
    std::vector<std::pair<std::string, std::string>> shortened;
    QString text = QString::fromStdString(App::toDisplayString(expr, &shortened));
    for (const auto& [name, path] : shortened) {
        text += u'\n' + QString::fromStdString(name) + QStringLiteral(": ")
            + QString::fromStdString(path);
    }
    return text;
}

}  // namespace Gui
