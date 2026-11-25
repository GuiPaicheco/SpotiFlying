"""Tray, dialogs and local desktop actions."""
import json
import platform
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QSystemTrayIcon

from . import __version__
from .platform import STORE_EDITION
from .settings import PRESETS

REPOSITORY = "https://github.com/GuiPaicheco/SpotiFlying"


class Desktop:
    def intro(self):
        self.data["intro_seen"] = True
        self.save_later()
        box = QMessageBox(self.settings_ui)
        box.setWindowTitle("Bem-vindo ao SpotiFlying")
        box.setText("Abra o Spotify Desktop e toque uma música ou explore o visual na demo offline.")
        box.setInformativeText("Ctrl+Alt+L alterna as sobreposições. Ctrl+Alt+I ativa a interação do cartão.")
        demo = box.addButton("Experimentar demo", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == demo:
            self.set_demo(True)

    def open_settings(self, category=None):
        if category:
            self.settings_ui.pick(category)
        self.settings_ui.showNormal()
        self.settings_ui.raise_()
        self.settings_ui.activateWindow()
        self.update_preview()

    def tray_activation(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def make_menu(self):
        self.menu.clear()
        self.menu.addAction("Configurações", self.open_settings)
        for key, label in (("lyrics_visible", "Mostrar letras"), ("card_visible", "Mostrar cartão")):
            action = self.menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.data[key])
            action.toggled.connect(lambda value, key=key: self.change(key, value, False))
        self.menu.addAction("Voltar ao modo passivo" if self.interaction else "Interagir com o cartão",
                            self.toggle_interaction)
        if self.editing:
            self.menu.addAction("Confirmar posição", self.confirm_position)
            self.menu.addAction("Cancelar edição", self.cancel_mode)
        else:
            self.menu.addAction("Editar posição", self.edit_position)
        presets = self.menu.addMenu("Preset")
        for preset in PRESETS:
            action = presets.addAction(preset)
            action.setCheckable(True)
            action.setChecked(preset == self.data["preset"])
            action.triggered.connect(lambda checked=False, preset=preset: self.change("preset", preset, False))
        source = self.menu.addMenu("Fonte · " + ("Demo offline" if self.demo else "Spotify Desktop"))
        source.addAction("Spotify Desktop", lambda: self.set_demo(False))
        source.addAction("Demo offline", lambda: self.set_demo(True))
        self.menu.addSeparator()
        self.menu.addAction("Personalizar", lambda: self.open_settings("Aparência"))
        self.menu.addAction("Atalhos", lambda: self.open_settings("Atalhos"))
        if not STORE_EDITION:
            startup_action = self.menu.addAction("Iniciar com o Windows")
            startup_action.setCheckable(True)
            startup_action.setChecked(self.data["startup"])
            startup_action.toggled.connect(lambda value: self.change("startup", value, False))
        self.menu.addAction("Verificar atualizações", self.updates)
        self.menu.addAction("Exportar diagnóstico", self.export_diagnostic)
        self.menu.addAction("Sair", self.qt.quit)

    def notify(self, message):
        self.settings_ui.status.setText(message)
        if not self.settings_ui.isVisible() and not (self.options.smoke or self.options.probe):
            self.tray.showMessage("SpotiFlying", message, QSystemTrayIcon.MessageIcon.Information, 4500)

    def profile(self, export):
        method = QFileDialog.getSaveFileName if export else QFileDialog.getOpenFileName
        name, _ = method(self.settings_ui, "Exportar perfil" if export else "Importar perfil", "", "JSON (*.json)")
        if not name:
            return
        try:
            if export:
                self.store.export_profile(Path(name))
            else:
                self.store.import_profile(Path(name))
                self.save_later()
                self.sync_ui()
            self.notify("Perfil salvo." if export else "Perfil carregado.")
        except (ValueError, OSError):
            self.notify("Não foi possível processar o perfil JSON.")

    def view_history(self):
        box = QMessageBox(self.settings_ui)
        box.setWindowTitle("Histórico local")
        box.setText("Consulte as faixas registradas neste dispositivo.")
        box.setDetailedText("\n".join(self.data["history"]) or "Histórico vazio.")
        box.exec()

    def clear_history(self):
        self.data["history"].clear()
        self.save_later()
        self.notify("Histórico local limpo.")

    def show_full_text(self):
        box = QMessageBox(self.settings_ui)
        box.setWindowTitle("Letra completa")
        box.setText("Use Mostrar detalhes para ler o texto da faixa atual.")
        box.setDetailedText(self.lyrics.text or "Letra indisponível.")
        box.exec()

    def export_diagnostic(self):
        name, _ = QFileDialog.getSaveFileName(self.settings_ui, "Exportar diagnóstico", "SpotiFlying-diagnostico.txt",
                                             "Texto (*.txt)")
        if name:
            try:
                report = {"version": __version__, "os": platform.version(), "arch": platform.machine(),
                          "source": "demo" if self.demo else "local", "session": bool(self.snapshot),
                          "position": self.playhead.position() is not None, "lyrics": self.lyrics.status,
                          "screens": [screen.devicePixelRatio() for screen in self.qt.screens()]}
                Path(name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                self.notify("Diagnóstico exportado.")
            except OSError:
                self.notify("Não foi possível gravar o diagnóstico.")

    def open_data(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    def updates(self):
        if STORE_EDITION:
            self.notify("Esta edição recebe atualizações pela Microsoft Store.")
            return
        self.notify("Consultando a Release no GitHub…")
        self.executor.submit(self.fetch_update)

    def fetch_update(self):
        req = Request("https://api.github.com/repos/GuiPaicheco/SpotiFlying/releases/latest",
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "SpotiFlying"})
        try:
            with urlopen(req, timeout=6) as reply:
                data = json.loads(reply.read(512_001))
            version = data["tag_name"].removeprefix("v")
            if len(version.split(".")) != 3 or not all(x.isdecimal() for x in version.split(".")):
                raise ValueError("version")
            assets = {item["name"] for item in data["assets"]}
            self.release_checked.emit((version, assets))
        except (OSError, ValueError, TypeError, KeyError):
            self.release_checked.emit(None)

    def show_update_result(self, release):
        if release is None:
            self.notify("Nenhuma Release disponível ou o GitHub está inacessível.")
        elif tuple(map(int, release[0].split("."))) <= tuple(map(int, __version__.split("."))):
            self.notify("Você está usando a versão mais recente.")
        else:
            portable = (Path(sys.executable).parent / "portable.flag").exists()
            package = "SpotiFlying-Portable-x64.zip" if portable else "SpotiFlying-Setup-x64.exe"
            question = f"A versão {release[0]} está disponível. Abrir a página de download?"
            if package in release[1]:
                question += f"\nPacote recomendado: {package}"
            if QMessageBox.question(self.settings_ui, "Atualização", question) == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(REPOSITORY + "/releases/tag/v" + release[0]))
