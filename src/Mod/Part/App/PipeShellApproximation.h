// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <BRepOffsetAPI_MakePipeShell.hxx>

/** How finely MakePipeShell approximates a sweep's surface (FreeCAD-CH, ops#448).
 *
 * At OCCT's default caps the approximation along long spines is unstable: the same ten planar
 * waves (200 spans) came out within 8e-7 mm of the tube in XZ, but 1.9e-2 mm off with vertex
 * tolerances of 0.15 mm when the plane was turned 45 degrees about X, and failed to build ("command
 * not done") when the turn came from the spine object's placement, its matrix 1e-16 away from the
 * same rotation. A degree of 14 builds every such placement within 5e-7 of the tube and vertex
 * tolerances of 5e-5; degrees 10 and 12 stayed erratic. The segments let two and three tilted
 * waves of 40 and 60 spans build at all (ops#440), where the degree alone didn't. Sweeps that
 * needed neither keep their surface within the tolerance (vertex tolerance 4.8e-5 to 4.6e-5 on the
 * waves in XZ) and their time (0.35 to 0.39 s on 1000 spans).
 */
namespace Part::PipeShellApproximation
{

/// The surface's largest degree along the spine
constexpr int maxDegree = 14;
/// The surface's largest number of spans along the spine
constexpr int maxSegments = 1000;
/// Part::Sweep warns where its result has a larger tolerance (mm). OCCT puts its estimate of the
/// approximation's error on the pipe's vertices: 0.15 mm on the ten waves turned 45 degrees, at
/// the default caps, where the tube was 1.9e-2 off. It isn't a measure of the error itself: of 200
/// tilted spines of 1 to 10 waves, all built within 6e-6 of the tube at these caps, some had 0.02.
constexpr double warningTolerance = 0.1;

/// Sets \a pipe's caps; call before Build()
inline void set(BRepOffsetAPI_MakePipeShell& pipe)
{
    pipe.SetMaxDegree(maxDegree);
    pipe.SetMaxSegments(maxSegments);
}

}  // namespace Part::PipeShellApproximation
