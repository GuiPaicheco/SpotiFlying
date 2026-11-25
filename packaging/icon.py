"""Rebuild the ICO from the editable SVG using Qt."""
import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication([])
root = Path(__file__).resolve().parents[1] / "src" / "spotiflying" / "assets"
svg = QSvgRenderer(str(root / "spotiflying.svg"))
sizes = (16, 20, 24, 32, 48, 256)
header = struct.pack("<HHH", 0, 1, len(sizes))
directory_size = len(header) + struct.calcsize("<BBBBHHII") * len(sizes)
entries, images = [], []
for size in sizes:
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
                               directory_size + sum(map(len, images))))
    images.append(bytes(data))

(root / "spotiflying.ico").write_bytes(header + b"".join(entries + images))
