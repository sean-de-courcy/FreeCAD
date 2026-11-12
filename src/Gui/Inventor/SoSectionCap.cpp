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

#include <FCConfig.h>

#ifdef FC_OS_WIN32
# include <Windows.h>
#endif
#ifdef FC_OS_MACOSX
# include <OpenGL/gl.h>
#else
# include <GL/gl.h>
#endif

#include <cmath>

#include <Inventor/SbBox.h>
#include <Inventor/SbColor.h>
#include <Inventor/SbLine.h>
#include <Inventor/SbMatrix.h>
#include <Inventor/SbVec3f.h>
#include <Inventor/SoPickedPoint.h>
#include <Inventor/actions/SoActions.h>
#include <Inventor/details/SoFaceDetail.h>
#include <Inventor/elements/SoCacheElement.h>
#include <Inventor/elements/SoModelMatrixElement.h>
#include <Inventor/misc/SoChildList.h>
#include <Inventor/misc/SoState.h>
#include <Inventor/nodes/SoDepthBuffer.h>
#include <Inventor/nodes/SoShapeHints.h>

#include "SoSectionCap.h"


using namespace Gui;

SO_NODE_SOURCE(SoSectionCap)

void SoSectionCap::initClass()
{
    SO_NODE_INIT_CLASS(SoSectionCap, SoSeparator, "Separator");
}

SoSectionCap::SoSectionCap()
{
    SO_NODE_CONSTRUCTOR(SoSectionCap);

    SO_NODE_ADD_FIELD(on, (true));
    SO_NODE_ADD_FIELD(origin, (0.0F, 0.0F, 0.0F));
    SO_NODE_ADD_FIELD(normal, (0.0F, 0.0F, 1.0F));
    SO_NODE_ADD_FIELD(color, (SbColor(0.60F, 0.62F, 0.66F)));

    // raw OpenGL calls are made while rendering: nothing may be cached
    renderCaching.setValue(OFF);
    boundingBoxCaching.setValue(OFF);
    renderCulling.setValue(OFF);
    pickCulling.setValue(OFF);
}

SoSectionCap::~SoSectionCap() = default;

void SoSectionCap::setModel(SoNode* model)
{
    removeAllChildren();
    if (!model) {
        return;
    }

    // Both passes draw the model without touching depth. The shape hints declare the model a
    // solid with the wanted winding, so that only the back faces (first pass) or only the front
    // faces (second pass) are drawn. Overriding makes them win over the hints inside the model.
    for (int pass = 0; pass < 2; ++pass) {
        auto depth = new SoDepthBuffer;
        depth->test.setValue(false);
        depth->write.setValue(false);

        auto hints = new SoShapeHints;
        hints->vertexOrdering.setValue(
            pass == 0 ? SoShapeHints::CLOCKWISE : SoShapeHints::COUNTERCLOCKWISE
        );
        hints->shapeType.setValue(SoShapeHints::SOLID);
        hints->faceType.setIgnored(true);
        hints->creaseAngle.setIgnored(true);
        hints->setOverride(true);

        auto sep = new SoSeparator;
        sep->renderCaching.setValue(SoSeparator::OFF);
        sep->addChild(depth);
        sep->addChild(hints);
        sep->addChild(model);
        addChild(sep);
    }
}

void SoSectionCap::GLRenderBelowPath(SoGLRenderAction* action)
{
    if (!on.getValue() || getNumChildren() != 2) {
        return;
    }

    SoState* state = action->getState();
    SoCacheElement::invalidate(state);

    GLint stencilBits = 0;
    glGetIntegerv(GL_STENCIL_BITS, &stencilBits);
    if (stencilBits < 1) {
        return;
    }

    SbVec3f n = normal.getValue();
    if (n.normalize() == 0.0F) {
        return;
    }

    // the section of the whole model is covered by a square on the plane
    SoNode* model = static_cast<SoSeparator*>(getChild(0))->getChild(2);
    SoGetBoundingBoxAction bboxAction(action->getViewportRegion());
    bboxAction.apply(model);
    const SbBox3f box = bboxAction.getBoundingBox();
    if (box.isEmpty()) {
        return;
    }
    const SbVec3f center = box.getCenter();
    const float half = (box.getMax() - box.getMin()).length();
    const SbVec3f onPlane = center - n * n.dot(center - origin.getValue());
    SbVec3f u = (std::abs(n[0]) < 0.9F ? SbVec3f(1.0F, 0.0F, 0.0F) : SbVec3f(0.0F, 1.0F, 0.0F))
                    .cross(n);
    u.normalize();
    SbVec3f v = n.cross(u);
    v.normalize();
    u *= half;
    v *= half;

    glPushAttrib(
        GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT
        | GL_POLYGON_BIT | GL_CURRENT_BIT | GL_LIGHTING_BIT
    );

    // count: back faces up, front faces down. Clipping is on, so a view ray that enters the
    // clipped half space inside a solid leaves a non-zero count.
    glStencilMask(0xFF);
    glClearStencil(0);
    glClear(GL_STENCIL_BUFFER_BIT);
    glEnable(GL_STENCIL_TEST);
    glStencilFunc(GL_ALWAYS, 0, 0xFF);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);

    glStencilOp(GL_KEEP, GL_KEEP, GL_INCR);
    getChildren()->traverse(action, 0, 0);
    glStencilOp(GL_KEEP, GL_KEEP, GL_DECR);
    getChildren()->traverse(action, 1, 1);

    // fill the plane where the count is not zero, without the clip planes (the square lies
    // on the section plane) and a little behind coplanar faces of the model
    GLboolean clipWasOn[6];
    for (int i = 0; i < 6; ++i) {
        clipWasOn[i] = glIsEnabled(GL_CLIP_PLANE0 + i);
        glDisable(GL_CLIP_PLANE0 + i);
    }
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glStencilFunc(GL_NOTEQUAL, 0, 0xFF);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
    glDisable(GL_LIGHTING);
    glDisable(GL_TEXTURE_2D);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glEnable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(1.0F, 1.0F);

    const SbColor& rgb = color.getValue();
    glColor3f(rgb[0], rgb[1], rgb[2]);
    const SbVec3f a = onPlane - u - v;
    const SbVec3f b = onPlane + u - v;
    const SbVec3f c = onPlane + u + v;
    const SbVec3f d = onPlane - u + v;
    glBegin(GL_QUADS);
    glVertex3f(a[0], a[1], a[2]);
    glVertex3f(b[0], b[1], b[2]);
    glVertex3f(c[0], c[1], c[2]);
    glVertex3f(d[0], d[1], d[2]);
    glEnd();

    for (int i = 0; i < 6; ++i) {
        if (clipWasOn[i]) {
            glEnable(GL_CLIP_PLANE0 + i);
        }
    }
    glPopAttrib();
}

void SoSectionCap::GLRenderInPath(SoGLRenderAction*)
{
    // only drawn when the whole scene is rendered
}

void SoSectionCap::GLRenderOffPath(SoGLRenderAction*)
{}

// The model below this node is the same node as the one the scene shows: no other action may
// reach it through here.

void SoSectionCap::doAction(SoAction*)
{}

void SoSectionCap::callback(SoCallbackAction*)
{}

void SoSectionCap::getBoundingBox(SoGetBoundingBoxAction*)
{}

void SoSectionCap::getMatrix(SoGetMatrixAction*)
{}

void SoSectionCap::handleEvent(SoHandleEventAction*)
{}

void SoSectionCap::pick(SoPickAction*)
{}

// The cap is drawn opaque, so a click on it must not reach what lies behind it: the ray passes
// the clipped half, and the first face it meets on the kept side is the far wall of the solid,
// seen from inside, which would be picked silently. Where the cap is seen (the ray enters the
// kept half inside a solid: its first face beyond the plane faces away from it), this adds a hit
// on the plane. It is the nearest hit and belongs to no view provider, so nothing is picked.
void SoSectionCap::rayPick(SoRayPickAction* action)
{
    if (!on.getValue() || getNumChildren() != 2) {
        return;
    }
    SbVec3f n = normal.getValue();
    if (n.normalize() == 0.0F) {
        return;
    }

    action->setObjectSpace();
    const SbLine& line = action->getLine();
    SbVec3f dir = line.getDirection();
    const float along = dir.dot(n);
    if (along <= 0.0F) {
        return;  // the ray goes from the kept side to the cut one: the kept faces hide the cap
    }
    const SbVec3f start = line.getPosition();
    const float toPlane = n.dot(origin.getValue() - start) / along;
    if (toPlane < 0.0F) {
        return;  // the ray starts on the kept side
    }
    const SbVec3f onPlane = start + dir * toPlane;

    // the faces along the ray, the model alone (no clip plane), in world space
    const SbMatrix& toWorld = SoModelMatrixElement::get(action->getState());
    SbVec3f worldStart;
    SbVec3f worldDir;
    SbVec3f worldOnPlane;
    toWorld.multVecMatrix(start, worldStart);
    toWorld.multDirMatrix(dir, worldDir);
    toWorld.multVecMatrix(onPlane, worldOnPlane);
    if (worldDir.normalize() == 0.0F) {
        return;
    }
    const float worldToPlane = (worldOnPlane - worldStart).dot(worldDir);

    SoNode* model = static_cast<SoSeparator*>(getChild(0))->getChild(2);
    SoRayPickAction faces(action->getViewportRegion());
    faces.setRay(worldStart, worldDir);
    faces.setPickAll(true);
    faces.apply(model);
    const SoPickedPoint* firstBeyond = nullptr;  // the first face hit on the kept side
    const SoPickedPointList& hits = faces.getPickedPointList();
    for (int i = 0; i < hits.getLength() && !firstBeyond; ++i) {
        const SoDetail* detail = hits[i]->getDetail();
        if (detail && detail->isOfType(SoFaceDetail::getClassTypeId())
            && (hits[i]->getPoint() - worldStart).dot(worldDir) > worldToPlane) {
            firstBeyond = hits[i];
        }
    }
    if (!firstBeyond || firstBeyond->getNormal().dot(worldDir) <= 0.0F) {
        return;  // no face beyond the plane, or a front face: outside the solid at the plane
    }

    // a hair on the kept side, so the clip plane itself doesn't drop the hit
    const float hair = 1e-5F * (1.0F + onPlane.length());
    const SbVec3f capPoint = onPlane + n * hair;
    if (action->isBetweenPlanes(capPoint)) {
        if (SoPickedPoint* pp = action->addIntersection(capPoint)) {
            pp->setObjectNormal(-n);
        }
    }
}

void SoSectionCap::search(SoSearchAction* action)
{
    SoNode::search(action);
}

void SoSectionCap::write(SoWriteAction* action)
{
    SoNode::write(action);
}

void SoSectionCap::getPrimitiveCount(SoGetPrimitiveCountAction*)
{}

void SoSectionCap::audioRender(SoAudioRenderAction*)
{}
