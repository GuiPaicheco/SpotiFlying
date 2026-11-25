"""Package the prepared Windows distribution for Microsoft Store submission."""
import argparse
import subprocess
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile

import pefile
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "src" / "spotiflying" / "assets" / "spotiflying.svg"


def package_version(executable):
    with pefile.PE(str(executable)) as image:
        if image.FILE_HEADER.Machine != pefile.MACHINE_TYPE["IMAGE_FILE_MACHINE_AMD64"]:
            raise ValueError("O pacote da Store deve usar o executável x64.")
        info = image.VS_FIXEDFILEINFO[0]
        return f"{info.FileVersionMS >> 16}.{info.FileVersionMS & 0xffff}.{info.FileVersionLS >> 16}.0"


def render_icons(directory):
    directory.mkdir()
    qt = QGuiApplication(["SpotiFlying MSIX", "-platform", "offscreen"])
    svg = QSvgRenderer(str(LOGO))
    if not svg.isValid():
        raise ValueError(f"Logo SVG inválida: {LOGO}")
    for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        svg.render(painter, QRectF(0, 0, size, size))
        painter.end()
        if not image.save(str(directory / f"{name}.png")):
            raise OSError(f"Não foi possível gerar {name}.png.")
    qt.quit()


def manifest(options, version):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap rescap">
  <Identity Name={quoteattr(options.identity_name)} Publisher={quoteattr(options.publisher)}
            Version="{version}" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>SpotiFlying</DisplayName>
    <PublisherDisplayName>{escape(options.publisher_display_name)}</PublisherDisplayName>
    <Description>Letras sincronizadas e miniplayer sobre a área de trabalho.</Description>
    <Logo>StoreAssets/StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="pt-BR" />
  </Resources>
  <Applications>
    <Application Id="SpotiFlying" Executable="SpotiFlying.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="SpotiFlying" Description="Letras sincronizadas e miniplayer"
                          BackgroundColor="transparent" Square150x150Logo="StoreAssets/Square150x150Logo.png"
                          Square44x44Logo="StoreAssets/Square44x44Logo.png" />
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makeappx", required=True, type=Path)
    parser.add_argument("--identity-name", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--publisher-display-name", required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "SpotiFlying")
    parser.add_argument("--output", type=Path, default=ROOT / "release" / "SpotiFlying-x64.msixupload")
    options = parser.parse_args()
    dist = options.dist.resolve()
    if not (dist / "SpotiFlying.exe").is_file() or not (dist / "licenses").is_dir():
        parser.error("Use a distribuição Windows x64 preparada pelo script de build do projeto.")
    if (dist / "portable.flag").exists():
        parser.error("Use a pasta dist/SpotiFlying da compilação, sem o marcador da versão portátil.")
    version = package_version(dist / "SpotiFlying.exe")

    output = options.output.resolve()
    if output.suffix.lower() != ".msixupload":
        parser.error("O arquivo de envio deve ter a extensão .msixupload.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="spotiflying-msix-", dir=output.parent) as temporary:
        workspace = Path(temporary)
        staged = workspace / "app"
        copytree(dist, staged)
        (staged / "store.flag").touch()
        render_icons(staged / "StoreAssets")
        (staged / "AppxManifest.xml").write_text(manifest(options, version), encoding="utf-8")
        package = workspace / "SpotiFlying-x64.msix"
        subprocess.run(
            [str(options.makeappx.resolve()), "pack", "/d", str(staged), "/p", str(package), "/o"],
            check=True,
        )
        upload = workspace / output.name
        with ZipFile(upload, "w") as archive:
            archive.write(package, package.name)
        upload.replace(output)
    print(output)


if __name__ == "__main__":
    main()
