"""Rebuild the ICO from the editable SVG using Qt."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication([])
root = Path(__file__).resolve().parents[1] / "src" / "spotiflying" / "assets"
svg = QSvgRenderer(str(root / "spotiflying.svg"))
entries, images = [], []
for size in (16, 32, 48, 256):
    import struct

    from PySide6.QtCore import QByteArray, QBuffer, QIODevice

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    svg.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, data.size(),
                               6 + 16 * 4 + sum(map(len, images))))
    images.append(bytes(data))

(root / "spotiflying.ico").write_bytes(b"\x00\x00\x01\x00\x04\x00" + b"".join(entries + images))
