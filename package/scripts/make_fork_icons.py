# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH: put a "CH" badge on FreeCAD's stock application icon.

So that FreeCAD-CH and official FreeCAD can be told apart in the taskbar, the Dock and the
Start menu. Run from the top of the source tree with the pixi environment's Python
(PySide6 and Pillow), e.g.

    QT_QPA_PLATFORM=offscreen .pixi/envs/default/python package/scripts/make_fork_icons.py

It adds the badge to src/Gui/Icons/freecad.svg (once) and renders, from that SVG:
    src/Main/icon.ico                                   the executables' icon (Windows)
    package/WindowsInstaller/icons/FreeCAD.ico          the installer's icon
    package/rattler-build/osx/resources/freecad.icns    the app bundle's icon (macOS)
"""

import io
import os
import sys

from PIL import Image
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SVG = "src/Gui/Icons/freecad.svg"
ICO_OUTPUTS = ["src/Main/icon.ico", "package/WindowsInstaller/icons/FreeCAD.ico"]
ICNS_OUTPUT = "package/rattler-build/osx/resources/freecad.icns"

# Drawn in the stock icon's 48x48 user space, bottom right: a red tag with "CH" in white
# strokes (paths, not text, so it looks the same without any font).
BADGE_ID = "fork-badge"
BADGE = f"""<g
     id="{BADGE_ID}"><rect
       x="22.5" y="29.5" width="25" height="18" rx="4" ry="4"
       style="fill:#c8102e;stroke:#ffffff;stroke-width:1.5" /><path
       d="M 33.9 35.2 A 4.6 4.6 0 1 0 33.9 41.8 M 38 34 V 43 M 44 34 V 43 M 38 38.5 H 44"
       style="fill:none;stroke:#ffffff;stroke-width:2.4;stroke-linecap:round" /></g>"""


def add_badge(svg_path):
    with open(svg_path, encoding="utf-8", newline="") as f:
        svg = f.read()
    if BADGE_ID in svg:
        return svg
    end = svg.rindex("</svg>")
    svg = svg[:end] + BADGE + svg[end:]
    with open(svg_path, "w", encoding="utf-8", newline="") as f:
        f.write(svg)
    return svg


def render(renderer, size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 (needed for painting)
    svg = add_badge(SVG)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError(f"{SVG}: not a valid SVG")

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    big = render(renderer, 256)
    images = {s: render(renderer, s) for s in ico_sizes}
    for path in ICO_OUTPUTS:
        # each size rendered from the SVG, not scaled down from the largest
        big.save(path, format="ICO", sizes=[(s, s) for s in ico_sizes],
                 append_images=[images[s] for s in ico_sizes if s != 256])
        print("wrote", path)

    icns = render(renderer, 1024)
    icns.save(ICNS_OUTPUT, format="ICNS")
    print("wrote", ICNS_OUTPUT)


if __name__ == "__main__":
    main()
