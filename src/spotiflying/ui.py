"""Settings, keyboard-accessible controls, and full-text preview."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .settings import CHOICES, RANGES


def style(theme):
    dark = theme == "Escuro" or (theme == "Sistema" and QApplication.palette().color(
        QPalette.ColorRole.Window).lightness() < 120)
    canvas, panel, text, minor, line, accent, button = (
        "#121d1b", "#1b2926", "#edf8f5", "#a9c1ba", "#35524b", "#79e2cc", "#29483f"
    ) if dark else ("#f1f6f3", "#ffffff", "#172d27", "#4d6a62", "#ccded7", "#186c5a", "#e0f1eb")
    return f"""
        QMainWindow, QWidget#root, QWidget#formBody {{background:{canvas};color:{text};}}
        QWidget {{color:{text};font-size:13px;}}
        QFrame#side, QFrame#preview {{background:{panel};border:1px solid {line};border-radius:13px;}}
        QLabel#brand {{font-size:23px;font-weight:750;color:{text};}}
        QLabel#section {{font-size:25px;font-weight:750;color:{text};}}
        QLabel#muted {{color:{minor};}}
        QLabel#accent {{color:{accent};font-weight:700;}}
        QScrollArea {{border:0;background:transparent;}}
        QScrollBar:vertical {{background:{canvas};width:11px;}}
        QScrollBar::handle:vertical {{background:{line};border-radius:5px;min-height:35px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:{canvas};}}
        QListWidget, QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit {{
            background:{panel};border:1px solid {line};border-radius:7px;padding:5px;
            selection-background-color:{button};
        }}
        QListWidget#nav {{border:0;padding:1px;outline:0;}}
        QListWidget::item {{min-height:27px;padding-left:6px;border-radius:5px;}}
        QListWidget::item:selected {{background:{button};color:{text};}}
        QPushButton {{background:{button};border:1px solid {line};border-radius:7px;
                      padding:7px 10px;color:{text};font-weight:600;}}
        QPushButton:disabled {{color:{minor};}}
        QLineEdit:focus, QPushButton:focus, QListWidget:focus, QComboBox:focus, QAbstractSpinBox:focus {{
            border:1px solid {accent};
        }}
    """


class SettingsWindow(QMainWindow):
    def __init__(self, app, icon):
        super().__init__()
        self.app = app
        self.fields = {}
        self.rows = []
        self.sections = []
        self.setWindowIcon(icon)
        self.setWindowTitle("SpotiFlying · Configurações")
        self.resize(1050, 710)
        self.setMinimumSize(595, 475)
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(13)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon.pixmap(42, 42))
        header.addWidget(mark)
        header.addWidget(QLabel("SpotiFlying", objectName="brand"))
        header.addStretch()
        self.demo = QPushButton("Demo offline")
        self.demo.setCheckable(True)
        self.demo.clicked.connect(self.app.set_demo)
        header.addWidget(self.demo)
        outer.addLayout(header)

        workspace = QHBoxLayout()
        workspace.setSpacing(12)
        outer.addLayout(workspace, 1)
        sidebar = QFrame(objectName="side")
        sidebar.setFixedWidth(173)
        side = QVBoxLayout(sidebar)
        self.search = QLineEdit(placeholderText="Buscar ajustes…")
        self.search.setAccessibleName("Buscar ajustes")
        self.search.textChanged.connect(self.filter)
        side.addWidget(self.search)
        self.nav = QListWidget(objectName="nav")
        self.nav.setAccessibleName("Categorias")
        side.addWidget(self.nav, 1)
        workspace.addWidget(sidebar)
        self.stack = QStackedWidget()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        workspace.addWidget(self.stack, 3)

        self.preview = QFrame(objectName="preview")
        preview = QVBoxLayout(self.preview)
        preview.addWidget(QLabel("PRÉVIA AO VIVO", objectName="accent"))
        self.preview_status = QLabel(wordWrap=True, objectName="muted")
        self.preview_status.setTextFormat(Qt.TextFormat.PlainText)
        preview.addWidget(self.preview_status)
        self.full_text = QTextEdit(readOnly=True)
        self.full_text.setAccessibleName("Letra completa")
        preview.addWidget(self.full_text, 1)
        workspace.addWidget(self.preview, 2)
        self.status = QLabel(objectName="muted")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        self.appearance()
        self.lyrics()
        self.card()
        self.playback()
        self.position()
        self.integrations()
        self.hotkeys()
        self.performance()
        self.privacy()
        self.about()
        self.nav.setCurrentRow(0)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self.preview.setVisible(event.size().width() >= 850)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def page(self, name, summary):
        self.nav.addItem(name)
        scroll = QScrollArea(widgetResizable=True)
        self.stack.addWidget(scroll)
        body = QWidget(objectName="formBody")
        scroll.setWidget(body)
        scroll.viewport().setObjectName("formBody")
        layout = QVBoxLayout(body)
        layout.addWidget(QLabel(name, objectName="section"))
        label = QLabel(summary, wordWrap=True, objectName="muted")
        layout.addWidget(label)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)
        layout.addStretch()
        self.sections.append(name)
        return self.form

    def row(self, label, widget):
        if label:
            caption = QLabel(label)
            caption.setBuddy(widget)
            self.form.addRow(caption, widget)
        else:
            caption = None
            self.form.addRow(widget)
        self.rows.append((len(self.sections) - 1, label or getattr(widget, "text", lambda: "")(),
                          caption, widget))
        return widget

    def button(self, label, callback):
        widget = QPushButton(label)
        widget.clicked.connect(callback)
        return self.row("", widget)

    def option(self, key, label, visual=True, limits=None):
        data = self.app.data["visual"] if visual else self.app.data
        value = data[key]
        if key == "font":
            widget = QFontComboBox()
            signal = widget.currentFontChanged
            def convert(font):
                return font.family()
            def assign(v):
                return widget.setCurrentFont(QFont(v))
        elif key in CHOICES:
            widget = QComboBox()
            widget.addItems(CHOICES[key])
            signal, assign, convert = widget.currentTextChanged, widget.setCurrentText, str
        elif isinstance(value, bool):
            widget = QCheckBox()
            signal, assign, convert = widget.toggled, widget.setChecked, bool
        elif isinstance(value, (int, float)):
            widget = QDoubleSpinBox() if isinstance(value, float) else QSpinBox()
            widget.setRange(*(limits or RANGES[key]))
            if key == "offset":
                widget.setSingleStep(50)
                widget.setSuffix(" ms")
            if key == "emphasis":
                widget.setSingleStep(.05)
            signal, assign, convert = widget.valueChanged, widget.setValue, type(value)
        else:
            widget = QLineEdit()
            signal, assign, convert = widget.editingFinished, widget.setText, lambda: widget.text().strip()
        signal.connect(lambda *args: self.app.change(key, convert(*args), visual))
        self.fields[(visual, key)] = widget, assign
        return self.row(label, widget)

    def color(self, key, label):
        widget = QPushButton()
        widget.clicked.connect(lambda: self.choose_color(key))
        self.fields[(True, key)] = widget, widget.setText
        self.row(label, widget)

    def choose_color(self, key):
        from PySide6.QtGui import QColor

        color = QColorDialog.getColor(QColor(self.app.data["visual"][key]), self)
        if color.isValid():
            self.app.change(key, color.name(), True)

    def appearance(self):
        self.page("Aparência", "Escolha um preset e ajuste a tipografia e a superfície das letras.")
        self.option("preset", "Preset", False)
        self.option("theme", "Tema da central", False)
        for key, label in (
            ("font", "Fonte"), ("size", "Tamanho (DIP)"), ("weight", "Peso"), ("italic", "Itálico"),
            ("uppercase", "Caixa alta"), ("tracking", "Espaço entre letras"), ("spacing", "Entrelinhas"),
            ("emphasis", "Escala da ênfase"), ("opacity", "Opacidade (%)"), ("gradient", "Gradiente"),
            ("art_tint", "Tonalidade da capa"), ("shadow", "Sombra curta"), ("outline", "Contorno do texto"),
            ("background_alpha", "Opacidade do fundo (%)"), ("border", "Borda"), ("padding", "Padding"),
        ):
            self.option(key, label)
        for key, label in (("color", "Cor atual"), ("secondary", "Cor secundária"), ("background", "Cor do fundo")):
            self.color(key, label)
        self.button("Restaurar visual da referência", self.app.restore_reference)
        self.button("Redefinir aparência do preset", self.app.reset_preset)

    def lyrics(self):
        self.page("Letras", "Ajustes positivos adiantam a letra. Você pode importar LRC ou TXT em UTF-8.")
        for key, label in (
            ("lines", "Linhas temporizadas"), ("previous", "Linhas anteriores"), ("mode", "Modo de leitura"),
            ("wrap", "Quebra de palavras"), ("scroll", "Rolagem opcional"), ("phrase_progress", "Progresso da frase"),
        ):
            self.option(key, label)
        self.option("offset", "Ajuste global", False)
        self.button("−50 ms", lambda: self.app.nudge(-50))
        self.button("+50 ms", lambda: self.app.nudge(50))
        self.button("Zerar ajuste global", lambda: self.app.change("offset", 0, False))
        self.button("Ajuste desta faixa", self.app.track_adjustment)
        self.button("Editar ênfase da faixa", self.app.edit_emphasis)
        self.button("Vincular arquivo LRC ou TXT", self.app.import_lyrics)
        self.button("Desvincular letra local", self.app.unlink_lyrics)
        self.button("Escolher versão do catálogo", self.app.choose_candidate)
        self.button("Ver letra completa", self.app.show_full_text)
        self.button("Redefinir opções de letras", lambda: self.app.reset_section(
            True, "lines", "previous", "mode", "wrap", "scroll", "phrase_progress"))

    def card(self):
        self.page("Cartão", "Ative os itens com Espaço. As setas abaixo movem o item selecionado.")
        for key, label in (
            ("card_width", "Largura (DIP)"), ("card_height", "Altura (DIP)"), ("cover", "Capa (DIP)"),
            ("card_opacity", "Opacidade (%)"), ("card_radius", "Raio"), ("card_padding", "Padding"),
            ("card_spacing", "Espaçamento"), ("card_border", "Borda"), ("card_shadow", "Sombra"),
            ("card_align", "Alinhamento"), ("card_layout", "Layout"), ("autohide", "Ocultação automática"),
            ("card_interactive_controls", "Mostrar controles ao interagir"),
        ):
            self.option(key, label)
        self.option("persistent", "Interação persistente", False)
        self.option("interaction_seconds", "Inatividade (segundos)", False)
        self.items = QListWidget()
        self.items.setMinimumHeight(200)
        self.items.itemChanged.connect(self.card_items)
        self.row("Itens do cartão", self.items)
        self.button("↑ Mover item para cima", lambda: self.move_item(-1))
        self.button("↓ Mover item para baixo", lambda: self.move_item(1))
        self.button("Redefinir cartão", lambda: self.app.reset_section(
            True, *(key for key in self.app.data["visual"] if key.startswith("card_")), "cover", "item_order",
            "autohide"))
        self.button("Ativar interação do cartão", self.app.toggle_interaction)

    def playback(self):
        self.page("Reprodução", "Use a sessão de mídia do Spotify Desktop ou alterne para a demo fictícia.")
        self.button("Usar Spotify Desktop", lambda: self.app.set_demo(False))
        self.button("Iniciar demo offline", lambda: self.app.set_demo(True))
        for mark, name in (("Anterior", "previous"), ("Reproduzir / pausar", "toggle"), ("Próxima", "next")):
            self.button(mark, lambda checked=False, name=name: self.app.command(name))
        self.option("startup", "Iniciar com o Windows", False)

    def position(self):
        self.page("Posicionamento", "Mova as caixas pela área de edição e redimensione pelo canto.")
        self.monitors = QComboBox()
        self.monitors.currentIndexChanged.connect(
            lambda index: self.app.change("monitor", self.monitors.itemData(index) or "", False))
        self.row("Monitor", self.monitors)
        self.anchors = {}
        for kind, label in (("lyrics", "Âncora das letras"), ("card", "Âncora do cartão")):
            combo = QComboBox()
            for text, value in (("Superior esquerda", "tl"), ("Centro", "center"), ("Inferior direita", "br")):
                combo.addItem(text, value)
            combo.currentIndexChanged.connect(lambda _, kind=kind, combo=combo: self.app.set_anchor(
                kind, combo.currentData()))
            self.anchors[kind] = self.row(label, combo)
        for key, label in (("lyrics_visible", "Mostrar letras"), ("card_visible", "Mostrar cartão"),
                           ("topmost", "Sempre no topo"), ("group", "Mover em grupo")):
            self.option(key, label, False)
        for key, label in (("units", "Unidade das letras"), ("width", "Largura"), ("height", "Altura"),
                           ("x_align", "Alinhamento horizontal"), ("y_align", "Alinhamento vertical")):
            self.option(key, label)
        self.button("Editar posição", self.app.edit_position)
        self.button("Centralizar overlays", self.app.center)
        self.button("Restaurar visual da referência", self.app.restore_reference)

    def integrations(self):
        self.page("Integrações", "O LRCLIB recebe título, artista, álbum e duração, quando disponíveis. "
                  "A consulta é opcional. A sessão local funciona sem conta de desenvolvedor.")
        self.option("catalog", "Consultar LRCLIB", False)
        self.button("Tentar consulta novamente", self.app.reload_lyrics)
        self.row("", QLabel("Spotify Web API indisponível nesta versão.", wordWrap=True, objectName="muted"))

    def hotkeys(self):
        self.page("Atalhos", "Edite uma combinação e confirme com Enter. Um campo vazio desativa o atalho.")
        self.option("toggle_hotkey", "Mostrar ou ocultar", False)
        self.option("interact_hotkey", "Interação do cartão", False)
        self.button("Redefinir atalhos", lambda: self.app.reset_section(False, "toggle_hotkey", "interact_hotkey"))

    def performance(self):
        self.page("Desempenho", "A economia reduz a taxa de atualização e desativa transições.")
        for key, label in (("animation", "Transição"), ("motion_ms", "Duração (ms)"),
                           ("intensity", "Intensidade"), ("easing", "Curva")):
            self.option(key, label)
        self.option("fps", "Limite de FPS", False)
        self.option("economy", "Modo economia", False)
        self.option("reduced_motion", "Reduzir movimento", False)
        self.button("Redefinir desempenho", lambda: self.app.reset_section(False, "fps", "economy", "reduced_motion"))

    def privacy(self):
        self.page("Privacidade", "Configurações e histórico opcional são locais. As letras remotas ficam na memória.")
        self.option("history_enabled", "Guardar histórico local", False)
        self.button("Ver histórico", self.app.view_history)
        self.button("Limpar histórico", self.app.clear_history)
        self.button("Limpar letras da sessão", self.app.clear_cache)
        self.button("Exportar diagnóstico", self.app.export_diagnostic)
        self.button("Exportar perfil", lambda: self.app.profile(True))
        self.button("Importar perfil", lambda: self.app.profile(False))

    def about(self):
        self.page("Sobre", "Aplicativo independente para Windows. A demonstração usa faixas fictícias.")
        self.location = QLabel(wordWrap=True, objectName="muted")
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.row("", self.location)
        self.button("Abrir pasta de dados", self.app.open_data)
        self.button("Verificar atualizações", self.app.updates)
        self.button("Redefinir todas as configurações", self.app.reset_all)

    def pick(self, name):
        self.search.clear()
        self.nav.setCurrentRow(self.sections.index(name))

    def filter(self, query):
        query = query.strip().casefold()
        matches = set()
        for number, label, caption, widget in self.rows:
            visible = not query or query in label.casefold() or query in self.sections[number].casefold()
            widget.setVisible(visible)
            if caption:
                caption.setVisible(visible)
            if visible:
                matches.add(number)
        for i in range(self.nav.count()):
            self.nav.item(i).setHidden(i not in matches)
        if matches and self.nav.currentRow() not in matches:
            self.nav.setCurrentRow(min(matches))
        self.stack.setVisible(bool(matches))

    def card_items(self):
        order = [self.items.item(i).text() for i in range(self.items.count())]
        active = [self.items.item(i).text() for i in range(self.items.count())
                  if self.items.item(i).checkState() == Qt.CheckState.Checked]
        self.app.change_card_items(order, active)

    def move_item(self, increment):
        row = self.items.currentRow()
        target = row + increment
        if row < 0 or not 0 <= target < self.items.count():
            return
        self.items.insertItem(target, self.items.takeItem(row))
        self.items.setCurrentRow(target)
        self.card_items()

    def refresh(self, items=True):
        data, visual = self.app.data, self.app.data["visual"]
        self.setStyleSheet(style(data["theme"]))
        self.demo.setChecked(self.app.demo)
        self.refresh_monitors()
        for kind, widget in self.anchors.items():
            with QSignalBlocker(widget):
                default = "tl" if kind == "lyrics" else "br"
                widget.setCurrentIndex(widget.findData(data[kind + "_position"].get("anchor", default)))
        self.location.setText(f"Dados locais\n{self.app.store.root}"
                              + ("\nO diretório portátil estava inacessível." if self.app.store.fallback else ""))
        for (is_visual, key), (widget, assign) in self.fields.items():
            with QSignalBlocker(widget):
                if key in ("height", "width"):
                    widget.setMaximum(100 if visual["units"] == "Percentual" else RANGES[key][1])
                assign((visual if is_visual else data)[key])
        if items:
            selected = self.items.currentRow()
            with QSignalBlocker(self.items):
                self.items.clear()
                for name in visual["item_order"]:
                    item = QListWidgetItem(name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if name in visual["card_items"]
                                       else Qt.CheckState.Unchecked)
                    self.items.addItem(item)
                if selected >= 0:
                    self.items.setCurrentRow(selected)

    def refresh_monitors(self):
        with QSignalBlocker(self.monitors):
            selected = self.app.data["monitor"]
            self.monitors.clear()
            self.monitors.addItem("Monitor de início", "")
            for screen in self.app.qt.screens():
                self.monitors.addItem(screen.name(), screen.name())
            if selected and self.monitors.findData(selected) < 0:
                self.monitors.addItem("Monitor desconectado", selected)
            self.monitors.setCurrentIndex(max(0, self.monitors.findData(selected)))

    def show_preview(self, caption, text, cue=""):
        self.preview_status.setText(caption)
        if self.full_text.toPlainText() != text:
            self.full_text.setPlainText(text)
        if cue and self.isVisible() and cue != getattr(self, "last_preview_cue", ""):
            self.last_preview_cue = cue
            self.full_text.moveCursor(self.full_text.textCursor().MoveOperation.Start)
            self.full_text.find(cue)
