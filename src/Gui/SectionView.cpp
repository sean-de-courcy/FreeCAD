// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

#include <Inventor/SbPlane.h>
#include <Inventor/SbVec3f.h>
#include <Inventor/SoPickedPoint.h>
#include <Inventor/details/SoFaceDetail.h>
#include <Inventor/events/SoMouseButtonEvent.h>
#include <Inventor/nodes/SoClipPlane.h>
#include <Inventor/nodes/SoEventCallback.h>
#include <Inventor/nodes/SoGroup.h>
#include <QDockWidget>
#include <QDoubleSpinBox>
#include <QHBoxLayout>
#include <QKeySequence>
#include <QLabel>
#include <QPushButton>
#include <QShortcut>
#include <QSignalBlocker>
#include <QTimer>
#include <QVBoxLayout>

#include <App/DocumentObject.h>
#include <App/GeoFeature.h>
#include <Base/Placement.h>
#include <Base/Rotation.h>
#include <Base/Vector3D.h>

#include "SectionView.h"
#include "DockWindowManager.h"
#include "Inventor/SoSectionCap.h"
#include "Selection/Selection.h"
#include "Selection/SoFCUnifiedSelection.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"

using namespace Gui;

namespace
{
const char* clipName = "FCSectionViewClip";
const char* capName = "FCSectionViewCap";

SoGroup* sceneRoot(const View3DInventorViewer* viewer)
{
    SoNode* root = viewer ? viewer->getSceneGraph() : nullptr;
    if (root && root->isOfType(SoGroup::getClassTypeId())) {
        return static_cast<SoGroup*>(root);
    }
    return nullptr;
}

SoNode* findChildOfType(SoGroup* root, const SoType& type, const char* name = nullptr)
{
    for (int i = 0; i < root->getNumChildren(); ++i) {
        SoNode* child = root->getChild(i);
        if (child->isOfType(type) && (!name || child->getName() == name)) {
            return child;
        }
    }
    return nullptr;
}
}  // namespace

bool SectionView::set(View3DInventorViewer* viewer, const SbVec3f& origin, const SbVec3f& cutNormal)
{
    SbVec3f cut = cutNormal;
    SoGroup* root = sceneRoot(viewer);
    if (!root || cut.normalize() == 0.0F) {
        return false;
    }
    SoNode* model = findChildOfType(root, Gui::SoFCUnifiedSelection::getClassTypeId());
    if (!model) {
        return false;
    }

    // the clip plane keeps the side its normal points to
    const SbVec3f keep = -cut;

    auto clip = static_cast<SoClipPlane*>(
        findChildOfType(root, SoClipPlane::getClassTypeId(), clipName)
    );
    if (!clip) {
        clip = new SoClipPlane;
        clip->setName(clipName);
        root->insertChild(clip, root->findChild(model));
    }
    clip->on.setValue(true);
    clip->plane.setValue(SbPlane(keep, origin));

    auto cap = static_cast<SoSectionCap*>(
        findChildOfType(root, SoSectionCap::getClassTypeId(), capName)
    );
    if (!cap) {
        cap = new SoSectionCap;
        cap->setName(capName);
        cap->setModel(model);
        root->addChild(cap);
    }
    cap->on.setValue(true);
    cap->origin.setValue(origin);
    cap->normal.setValue(keep);
    return true;
}

void SectionView::clear(View3DInventorViewer* viewer)
{
    SoGroup* root = sceneRoot(viewer);
    if (!root) {
        return;
    }
    if (SoNode* cap = findChildOfType(root, SoSectionCap::getClassTypeId(), capName)) {
        root->removeChild(cap);
    }
    if (SoNode* clip = findChildOfType(root, SoClipPlane::getClassTypeId(), clipName)) {
        root->removeChild(clip);
    }
}

bool SectionView::get(const View3DInventorViewer* viewer, SbVec3f& origin, SbVec3f& cutNormal)
{
    SoGroup* root = sceneRoot(viewer);
    if (!root) {
        return false;
    }
    auto cap = static_cast<SoSectionCap*>(
        findChildOfType(root, SoSectionCap::getClassTypeId(), capName)
    );
    if (!cap) {
        return false;
    }
    origin = cap->origin.getValue();
    cutNormal = -cap->normal.getValue();
    return true;
}

// ---------------------------------------------------------------------------------------------

using namespace Gui::Dialog;

struct SectionViewPanel::Data
{
    QPointer<Gui::View3DInventor> view;
    QPointer<QDockWidget> dock;
    QDoubleSpinBox* offset {nullptr};
    QPushButton* pick {nullptr};
    SbVec3f base {0.0F, 0.0F, 0.0F};
    SbVec3f dir {0.0F, -1.0F, 0.0F};
    double offsetValue {0.0};
    bool picking {false};
};

SectionViewPanel* SectionViewPanel::makeDockWidget(Gui::View3DInventor* view)
{
    auto panel = new SectionViewPanel(view);
    Gui::DockWindowManager* dockManager = Gui::DockWindowManager::instance();
    QDockWidget* dock = dockManager->addDockWindow("SectionView", panel, Qt::LeftDockWidgetArea);
    dock->setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetFloatable);
    dock->show();
    panel->d->dock = dock;
    return panel;
}

SectionViewPanel::SectionViewPanel(Gui::View3DInventor* view, QWidget* parent)
    : QWidget(parent)
    , d(new Data)
{
    d->view = view;
    setWindowTitle(tr("Section view"));

    auto layout = new QVBoxLayout(this);

    layout->addWidget(new QLabel(tr("Section plane"), this));
    auto planes = new QHBoxLayout;
    const QString names[] = {tr("Front"), tr("Right"), tr("Top")};
    for (int i = 0; i < 3; ++i) {
        auto button = new QPushButton(names[i], this);
        connect(button, &QPushButton::clicked, this, [this, i]() { setAxisPlane(i); });
        planes->addWidget(button);
    }
    layout->addLayout(planes);

    auto selected = new QPushButton(tr("Selected plane"), this);
    selected->setToolTip(tr("Use the selected origin plane or datum plane"));
    connect(selected, &QPushButton::clicked, this, &SectionViewPanel::onSelectedPlane);
    layout->addWidget(selected);

    d->pick = new QPushButton(tr("Pick a face"), this);
    d->pick->setCheckable(true);
    d->pick->setToolTip(tr("Click a face in the 3D view to put the plane on it"));
    connect(d->pick, &QPushButton::toggled, this, &SectionViewPanel::onPickFace);
    layout->addWidget(d->pick);

    auto offsetRow = new QHBoxLayout;
    offsetRow->addWidget(new QLabel(tr("Offset"), this));
    d->offset = new QDoubleSpinBox(this);
    constexpr double limit = 1.0e9;
    d->offset->setRange(-limit, limit);
    d->offset->setDecimals(3);
    d->offset->setSingleStep(1.0);
    d->offset->setSuffix(tr(" mm"));
    connect(
        d->offset,
        qOverload<double>(&QDoubleSpinBox::valueChanged),
        this,
        &SectionViewPanel::onOffsetChanged
    );
    offsetRow->addWidget(d->offset, 1);
    layout->addLayout(offsetRow);

    auto flip = new QPushButton(tr("Flip"), this);
    flip->setToolTip(tr("Hide the other side of the plane"));
    connect(flip, &QPushButton::clicked, this, &SectionViewPanel::onFlip);
    layout->addWidget(flip);

    auto close = new QPushButton(tr("Close"), this);
    connect(close, &QPushButton::clicked, this, &SectionViewPanel::closePanel);
    layout->addWidget(close);
    layout->addStretch();

    auto escape = new QShortcut(QKeySequence(Qt::Key_Escape), this);
    escape->setContext(Qt::WidgetWithChildrenShortcut);
    connect(escape, &QShortcut::activated, this, &SectionViewPanel::closePanel);

    if (view) {
        connect(view, &QObject::destroyed, this, &SectionViewPanel::closePanel);
        // keep a section that is already there, else start on the front plane
        SbVec3f origin;
        SbVec3f cut;
        if (SectionView::get(view->getViewer(), origin, cut)) {
            d->base = origin;
            d->dir = cut;
        }
        else {
            applyPlane();
        }
    }
}

SectionViewPanel::~SectionViewPanel()
{
    stopPicking();
    if (d->view) {
        SectionView::clear(d->view->getViewer());
    }
    delete d;
}

Gui::View3DInventor* SectionViewPanel::getView() const
{
    return d->view;
}

void SectionViewPanel::closePanel()
{
    // the section goes now, not when the (deferred) deletion happens: a section that is set
    // right after closing must stay
    stopPicking();
    if (d->view) {
        SectionView::clear(d->view->getViewer());
        d->view.clear();
    }
    if (d->dock) {
        d->dock->deleteLater();
    }
    else {
        deleteLater();
    }
}

void SectionViewPanel::applyPlane()
{
    if (d->view) {
        const SbVec3f origin = d->base + d->dir * static_cast<float>(d->offsetValue);
        SectionView::set(d->view->getViewer(), origin, d->dir);
    }
}

void SectionViewPanel::setPlane(const SbVec3f& base, const SbVec3f& cutNormal)
{
    SbVec3f cut = cutNormal;
    if (cut.normalize() == 0.0F) {
        return;
    }
    d->base = base;
    d->dir = cut;
    d->offsetValue = 0.0;
    {
        QSignalBlocker block(d->offset);
        d->offset->setValue(0.0);
    }
    applyPlane();
}

void SectionViewPanel::setAxisPlane(int axis)
{
    // the cut side is the one nearest to the viewer of the standard view: front looks along +Y
    // from -Y, right looks along -X from +X, top looks along -Z from +Z
    const SbVec3f front(0.0F, -1.0F, 0.0F);
    const SbVec3f right(1.0F, 0.0F, 0.0F);
    const SbVec3f top(0.0F, 0.0F, 1.0F);
    setPlane(SbVec3f(0.0F, 0.0F, 0.0F), axis == 0 ? front : (axis == 1 ? right : top));
}

void SectionViewPanel::onOffsetChanged(double value)
{
    d->offsetValue = value;
    applyPlane();
}

void SectionViewPanel::onFlip()
{
    // the plane stays where it is: the offset changes its sign with the normal
    d->dir = -d->dir;
    d->offsetValue = -d->offsetValue;
    {
        QSignalBlocker block(d->offset);
        d->offset->setValue(d->offsetValue);
    }
    applyPlane();
}

void SectionViewPanel::onSelectedPlane()
{
    for (const auto& sel : Gui::Selection().getSelection()) {
        auto geo = dynamic_cast<App::GeoFeature*>(sel.pObject);
        if (!geo) {
            continue;
        }
        const Base::Placement pla = geo->globalPlacement();
        Base::Vector3d normal;
        pla.getRotation().multVec(Base::Vector3d(0.0, 0.0, 1.0), normal);
        const Base::Vector3d pos = pla.getPosition();
        setPlane(
            SbVec3f(float(pos.x), float(pos.y), float(pos.z)),
            SbVec3f(float(normal.x), float(normal.y), float(normal.z))
        );
        return;
    }
}

void SectionViewPanel::onPickFace(bool on)
{
    if (!d->view) {
        return;
    }
    View3DInventorViewer* viewer = d->view->getViewer();
    if (on && !d->picking) {
        d->picking = true;
        viewer->addEventCallback(SoMouseButtonEvent::getClassTypeId(), pickCallback, this);
    }
    else if (!on && d->picking) {
        d->picking = false;
        viewer->removeEventCallback(SoMouseButtonEvent::getClassTypeId(), pickCallback, this);
    }
}

void SectionViewPanel::stopPicking()
{
    if (d->picking) {
        onPickFace(false);
    }
    if (d->pick && d->pick->isChecked()) {
        QSignalBlocker block(d->pick);
        d->pick->setChecked(false);
    }
}

void SectionViewPanel::pickCallback(void* userdata, SoEventCallback* node)
{
    auto self = static_cast<SectionViewPanel*>(userdata);
    const SoEvent* event = node->getEvent();
    if (!event->isOfType(SoMouseButtonEvent::getClassTypeId())) {
        return;
    }
    auto button = static_cast<const SoMouseButtonEvent*>(event);
    if (button->getButton() != SoMouseButtonEvent::BUTTON1
        || button->getState() != SoButtonEvent::DOWN) {
        return;
    }

    node->setHandled();
    const SoPickedPoint* picked = node->getPickedPoint();
    const SoDetail* detail = picked ? picked->getDetail() : nullptr;
    if (!detail || !detail->isOfType(SoFaceDetail::getClassTypeId())) {
        return;  // an edge or a vertex has no normal of its own: wait for a face
    }
    // the face normal points out of the part: the cut side is the outside
    self->setPlane(picked->getPoint(), picked->getNormal());
    // the callback list must not change while it is called
    QTimer::singleShot(0, self, [self]() { self->stopPicking(); });
}

#include "moc_SectionView.cpp"
