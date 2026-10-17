// SPDX-License-Identifier: LGPL-2.1-or-later

// The Split panel (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include <QCheckBox>
#include <QLabel>
#include <QVBoxLayout>

#include <App/Document.h>
#include <Gui/CommandT.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureSplit.h>

#include "TaskSplitParameters.h"

using namespace PartDesignGui;

namespace
{
QString label(const App::DocumentObject* obj)
{
    return obj ? QString::fromUtf8(obj->Label.getValue()) : QStringLiteral("?");
}

// The new half that reads @p split, or null
PartDesign::Split* newHalfOf(PartDesign::Split* split)
{
    for (auto obj : split->getInList()) {
        auto other = freecad_cast<PartDesign::Split*>(obj);
        if (other && other->partnerSplit() == split) {
            return other;
        }
    }
    return nullptr;
}
}  // namespace

TaskSplitParameters::TaskSplitParameters(ViewProvider* vp, QWidget* parent)
    : TaskFeatureParameters(vp, parent, "PartDesign_Boolean", tr("Split Parameters"))
{
    auto widget = new QWidget(this);
    auto layout = new QVBoxLayout(widget);
    plane = new QLabel(widget);
    plane->setObjectName(QStringLiteral("labelPlane"));
    plane->setWordWrap(true);
    sides = new QLabel(widget);
    sides->setObjectName(QStringLiteral("labelSides"));
    sides->setWordWrap(true);
    flip = new QCheckBox(tr("Flip"), widget);
    flip->setObjectName(QStringLiteral("checkBoxFlip"));
    flip->setToolTip(tr("Keep the other side of the plane in this part"));
    layout->addWidget(plane);
    layout->addWidget(sides);
    layout->addWidget(flip);
    groupLayout()->addWidget(widget);

    auto split = getObject<PartDesign::Split>();
    if (split && split->NewHalf.getValue()) {
        // The original's Split decides: its Flip flips both halves
        flip->setEnabled(false);
    }
    else if (split) {
        flip->setChecked(split->Side.getValue() != 0);
    }
    connect(flip, &QCheckBox::toggled, this, &TaskSplitParameters::onFlip);
    updateText();
}

void TaskSplitParameters::onFlip(bool flipped)
{
    auto split = getObject<PartDesign::Split>();
    if (!split || split->NewHalf.getValue()) {
        return;
    }
    split->Side.setValue(flipped ? 1L : 0L);
    updateText();
    recomputeFeature();
}

void TaskSplitParameters::updateText()
{
    auto split = getObject<PartDesign::Split>();
    if (!split) {
        return;
    }
    PartDesign::Split* original = split->NewHalf.getValue() ? split->partnerSplit() : split;
    if (!original) {
        plane->setText(tr("Its partner Split was deleted."));
        sides->clear();
        return;
    }
    PartDesign::Split* half = split->NewHalf.getValue() ? split : newHalfOf(original);
    const App::DocumentObject* tool = original->Tool.getValue();
    const std::vector<std::string>& subs = original->Tool.getSubValues();
    QString planeText = label(tool);
    if (!subs.empty() && !subs.front().empty()) {
        planeText += QStringLiteral(".") + QString::fromStdString(subs.front());
    }
    plane->setText(tr("Plane: %1").arg(planeText));
    const bool front = original->Side.getValue() == 0;
    const QString kept = front ? tr("front") : tr("back");
    const QString other = front ? tr("back") : tr("front");
    QString text = tr("%1 keeps the %2 side (where the plane's normal points: front).")
                       .arg(label(PartDesign::Body::findBodyOf(original)), kept);
    if (half) {
        text += QStringLiteral(" ")
            + tr("%1 gets the %2 side.").arg(label(PartDesign::Body::findBodyOf(half)), other);
    }
    if (split->NewHalf.getValue()) {
        text += QStringLiteral(" ")
            + tr("Flip it in %1's Split.").arg(label(PartDesign::Body::findBodyOf(original)));
    }
    sides->setText(text);
}

void TaskSplitParameters::apply()
{
    auto split = getObject<PartDesign::Split>();
    if (!split || split->NewHalf.getValue()) {
        return;
    }
    FCMD_OBJ_CMD(split, "Side = '" << split->Side.getValueAsString() << "'");
}

TaskDlgSplitParameters::TaskDlgSplitParameters(ViewProvider* vp)
    : TaskDlgFeatureParameters(vp)
{
    Content.push_back(new TaskSplitParameters(vp));
    Content.push_back(preview);
}

#include "moc_TaskSplitParameters.cpp"
