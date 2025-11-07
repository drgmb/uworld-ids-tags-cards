
# SPDX-License-Identifier: MIT
# -*- coding: utf-8 -*-
# UWorld IDs → tags → cards (minimal UI, whole collection, progress indicator, open-in-browser + auto-close)
# Qt5/Qt6 • theme-friendly • persistent version (V12/V11) • configurable global shortcut • Anki 25.x Future callback

from __future__ import annotations

import sys, re
from typing import Dict, Any, List, Set, Optional

from aqt import mw, gui_hooks, dialogs
from aqt.qt import (
    QAction, QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, QSizePolicy, QFont,
    QShortcut, QKeySequence, QProgressBar
)
from aqt.utils import showInfo, tooltip

# -----------------------------
# Resolve Add-on ID (config persistence)
# -----------------------------
def _addon_id() -> str:
    try:
        return mw.addonManager.addonFromModule(__name__) or __name__
    except Exception:
        return __name__

ADDON_ID = _addon_id()

# -----------------------------
# Qt5/Qt6 shims
# -----------------------------
try:
    SP_EXPANDING = QSizePolicy.Policy.Expanding
    SP_FIXED = QSizePolicy.Policy.Fixed
except AttributeError:  # Qt5
    SP_EXPANDING = QSizePolicy.Expanding
    SP_FIXED = QSizePolicy.Fixed

def QtAlign_Left():
    try:
        from aqt.qt import Qt
        return Qt.AlignmentFlag.AlignLeft  # Qt6
    except Exception:
        from aqt.qt import Qt
        return Qt.AlignLeft  # Qt5

def make_mono_font() -> QFont:
    f = QFont()
    families = ["Menlo", "Consolas", "Monaco", "Courier New", "Noto Sans Mono", "DejaVu Sans Mono", "monospace"]
    try:
        f.setFamilies(families)  # Qt ≥5.13/Qt6
    except Exception:
        for fam in families:
            try:
                f.setFamily(fam); break
            except Exception:
                continue
    try:
        from aqt.qt import QFont as _QF
        f.setStyleHint(_QF.StyleHint.Monospace)  # Qt6
    except Exception:
        for hint_name in ("Monospace", "TypeWriter"):
            try:
                f.setStyleHint(getattr(QFont, hint_name)); break
            except Exception:
                continue
    return f

# -----------------------------
# Defaults & Config helpers
# -----------------------------
VERSION_LABELS = ["V12", "V11"]
VERSION_VALUE: Dict[str, str] = {"V12": "AK_Step1_v12", "V11": "AK_Step1_v11"}
DEFAULT_VERSION_LABEL = "V12"
UWORLD_SEGMENT = "::#UWorld::Step::"

def _platform_default_shortcut() -> str:
    return "Meta+Alt+U" if sys.platform == "darwin" else "Ctrl+Alt+U"

DEFAULT_CONFIG: Dict[str, Any] = {
    "deck_version_label": DEFAULT_VERSION_LABEL,
    "shortcut": "",  # vazio => preenchido com padrão
}

def _get_config() -> Dict[str, Any]:
    cfg = mw.addonManager.getConfig(ADDON_ID) or {}
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    if cfg.get("deck_version_label") not in VERSION_LABELS:
        cfg["deck_version_label"] = DEFAULT_VERSION_LABEL
    if not cfg.get("shortcut"):
        cfg["shortcut"] = _platform_default_shortcut()
        _write_config(cfg)
    return cfg

def _write_config(cfg: Dict[str, Any]) -> None:
    try:
        mw.addonManager.writeConfig(ADDON_ID, cfg)
    except Exception:
        mw.addonManager.setConfig(ADDON_ID, cfg)

# -----------------------------
# Core search helpers (no deck filter)
# -----------------------------
def _normalize_version_prefix(deck_version_value: str) -> str:
    s = (deck_version_value or "").strip()
    if not s:
        s = VERSION_VALUE[DEFAULT_VERSION_LABEL]
    return s if s.startswith("#") else f"#{s}"

def _extract_unique_int_strings(raw: str) -> List[str]:
    ids = [m.group(0) for m in re.finditer(r"\d+", raw or "")]
    seen, out = set(), []
    for x in ids:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _esc(s: str) -> str:
    return s.replace('"', r'\"')

# --- NOVO: prefixo de tag com a regra pedida ---
def _tag_prefix(deck_version_value: str) -> str:
    """
    Regra especial:
    - Se a versão escolhida for V11, a sintaxe deve usar '#AK_Step1_v12::#UWorld::<ID>'
      (ou seja, força o prefixo de V12 e remove 'Step::').
    - Caso contrário (V12), mantém o padrão '#AK_Step1_v12::#UWorld::Step::<ID>'.
    """
    if deck_version_value == VERSION_VALUE["V11"]:
        base = _normalize_version_prefix(VERSION_VALUE["V12"])
        return base + "::#UWorld::"
    return _normalize_version_prefix(deck_version_value) + UWORLD_SEGMENT

def build_tag_or_query(ids: List[str], deck_version_value: str) -> str:
    prefix = _tag_prefix(deck_version_value)
    if not ids:
        return ""
    parts = [f'tag:"{_esc(prefix + i)}"' for i in ids]
    return "(" + " OR ".join(parts) + ")"

def compute_ids_summary(deck_version_value: str, ids_questions: str) -> Dict[str, Any]:
    """
    Busca em TODA a coleção (sem filtro de deck).
    Retorna:
      total_ids_input, total_cards, total_ids_without_cards,
      ids_syntax, ids_without_cards
    """
    ids = _extract_unique_int_strings(ids_questions)
    ids_syntax = build_tag_or_query(ids, deck_version_value)

    result: Dict[str, Any] = {
        "total_ids_input": len(ids),
        "total_cards": 0,
        "total_ids_without_cards": 0,
        "ids_syntax": ids_syntax,
        "ids_without_cards": [],
    }
    if not ids or not ids_syntax:
        return result

    # Busca principal: exatamente a OR syntax (coleção inteira)
    cids_all: Set[int] = set(mw.col.find_cards(ids_syntax))

    # IDs sem cards: verificação por tag individual (coleção inteira)
    prefix = _tag_prefix(deck_version_value)
    ids_without: List[str] = []
    for id_s in ids:
        q_tag = f'tag:"{_esc(prefix + id_s)}"'
        cids = set(mw.col.find_cards(q_tag))
        if not cids:
            ids_without.append(id_s)

    result["total_cards"] = len(cids_all)
    result["total_ids_without_cards"] = len(ids_without)
    result["ids_without_cards"] = ids_without
    return result

# -----------------------------
# UI - Main Dialog (IDs first, then version) + Progress + Open Browser (auto-close)
# -----------------------------
class UWorldIdsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UWorld IDs → tags → cards")
        self.setMinimumWidth(760)

        mono = make_mono_font()
        self._cfg = _get_config()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(QtAlign_Left())
        form.setSpacing(6)

        # 1) IDs primeiro (foco ao abrir)
        self.txtIds = JText = QTextEdit()
        self.txtIds.setPlaceholderText("Paste integer IDs separated by comma… e.g. 1,3213,342435,2312")
        self.txtIds.setFixedHeight(90)
        form.addRow(QLabel("ids_questions:"), self.txtIds)

        # 2) Versão (dropdown V12/V11 persistente)
        self.cmbVersion = QComboBox()
        self.cmbVersion.addItems(VERSION_LABELS)
        saved_label = self._cfg.get("deck_version_label") or DEFAULT_VERSION_LABEL
        if saved_label in VERSION_LABELS:
            self.cmbVersion.setCurrentIndex(VERSION_LABELS.index(saved_label))
        form.addRow(QLabel("deck_version:"), self.cmbVersion)

        root.addLayout(form)

        # Botões + status/progresso
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        self.btnRun = QPushButton("Run")
        self.btnCopySyntax = QPushButton('Copy “IDs (search syntax)”')
        self.btnCopySyntax.setEnabled(False)
        self.btnOpenBrowser = QPushButton("Open in Browser")
        self.btnOpenBrowser.setEnabled(False)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)

        self.lblStatus = QLabel("")

        btn_row.addWidget(self.btnRun)
        btn_row.addWidget(self.btnCopySyntax)
        btn_row.addWidget(self.btnOpenBrowser)
        btn_row.addStretch(1)
        btn_row.addWidget(self.lblStatus)
        btn_row.addWidget(self.progress)
        root.addLayout(btn_row)

        # Saída
        self.outSummary = QTextEdit()
        self.outSummary.setReadOnly(True)
        self.outSummary.setFont(mono)
        self.outSummary.setFixedHeight(180)
        self.outSummary.setPlaceholderText(
            "Outputs will appear here…\n"
            "• Total IDs\n"
            "• Total cards\n"
            "• Total IDs without cards\n"
            "• IDs (search syntax)\n"
            "• IDs without cards"
        )
        root.addWidget(self.outSummary)

        # Persistência ao trocar versão
        self.cmbVersion.currentTextChanged.connect(self._persist_version_now)

        # Ações
        self.btnRun.clicked.connect(self.run_query)
        self.btnCopySyntax.clicked.connect(self.copy_syntax)
        self.btnOpenBrowser.clicked.connect(self.open_in_browser)

        # Foco inicial no campo de IDs
        self.txtIds.setFocus()

        self._last_summary: Dict[str, Any] = {}

    # ---------- persistência / leitura versão ----------
    def _persist_version_now(self):
        cfg = _get_config()
        label = self.cmbVersion.currentText()
        if label not in VERSION_LABELS:
            label = DEFAULT_VERSION_LABEL
        cfg["deck_version_label"] = label
        _write_config(cfg)

    def _current_version_value(self) -> str:
        label = self.cmbVersion.currentText()
        if label not in VERSION_LABELS:
            label = DEFAULT_VERSION_LABEL
        return VERSION_VALUE[label]

    # ---------- feedback visual ----------
    def _set_busy(self, busy: bool):
        if busy:
            self.lblStatus.setText("Searching…")
            self.progress.setRange(0, 0)  # indeterminate
            self.progress.setVisible(True)
            self.btnRun.setEnabled(False)
            self.btnCopySyntax.setEnabled(False)
            self.btnOpenBrowser.setEnabled(False)
            self.lblStatus.repaint(); self.progress.repaint()
            QApplication.processEvents()
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setVisible(False)
            self.lblStatus.setText("Done ✓")
            self.btnRun.setEnabled(True)
            enable = bool(self._last_summary.get("ids_syntax"))
            self.btnCopySyntax.setEnabled(enable)
            self.btnOpenBrowser.setEnabled(enable)
            self.lblStatus.repaint()
            QApplication.processEvents()

    # ---------- execução (em background) ----------
    def run_query(self):
        deck_version_value = self._current_version_value()
        ids_questions = self.txtIds.toPlainText()

        # persiste também ao rodar
        self._persist_version_now()

        # status → Searching…
        self._set_busy(True)

        # aceita assinatura com progress param (compat futura)
        def work(_progress=None):
            return compute_ids_summary(deck_version_value, ids_questions)

        # Anki 25.x: callback recebe um Future
        def on_done(fut):
            try:
                summary = fut.result()
            except Exception as e:
                summary = {}
                showInfo(f"Search failed:\n{e}")

            try:
                self._last_summary = summary or {}
                lines = [
                    f'Total IDs: {self._last_summary.get("total_ids_input", 0)}',
                    f'Total cards: {self._last_summary.get("total_cards", 0)}',
                    f'Total IDs without cards: {self._last_summary.get("total_ids_without_cards", 0)}',
                    f'IDs (search syntax): {self._last_summary.get("ids_syntax", "")}',
                    f'IDs without cards: {", ".join(self._last_summary.get("ids_without_cards", []))}',
                ]
                self.outSummary.setPlainText("\n".join(lines))
                tooltip("Query finished.", parent=self)
            finally:
                # status → Done ✓
                self._set_busy(False)

        mw.taskman.run_in_background(work, on_done)

    # ---------- ações auxiliares ----------
    def copy_syntax(self):
        syntax = self._last_summary.get("ids_syntax") or ""
        if not syntax:
            tooltip("No search syntax to copy.", parent=self); return
        QApplication.clipboard().setText(syntax)
        tooltip('Search syntax copied to clipboard.', parent=self)

    def open_in_browser(self):
        """Abre o Browser com a search syntax atual e fecha este diálogo ao concluir com sucesso."""
        syntax = self._last_summary.get("ids_syntax") or ""
        if not syntax:
            tooltip("No search syntax to open.", parent=self); return
        try:
            brw = dialogs.open("Browser", mw)
        except Exception as e:
            showInfo(f"Could not open Browser:\n{e}")
            return

        # Tenta API moderna; se falhar, usa fallback
        try:
            brw.search_for(syntax)  # Anki recentes
        except Exception:
            try:
                se = brw.form.searchEdit
                try:
                    se.setText(syntax)              # Qt6
                except Exception:
                    se.lineEdit().setText(syntax)   # Qt5
                brw.onSearchActivated()
            except Exception as e:
                showInfo(f"Could not run search in Browser:\n{e}")
                return

        # Dar foco ao Browser
        try:
            brw.activateWindow()
            brw.raise_()
        except Exception:
            pass

        tooltip("Opened in Browser.", parent=self)
        # ✅ Fecha o diálogo do add-on após abrir o Browser e executar a busca
        self.accept()

# -----------------------------
# Config Dialog (Add-ons → Configurar) — atalho global
# -----------------------------
class ShortcutConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UWorld IDs → tags → cards — Settings")
        self.setMinimumWidth(480)

        self._cfg = _get_config()

        root = QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)

        frm = QFormLayout(); frm.setLabelAlignment(QtAlign_Left()); frm.setSpacing(6)

        self.txtShortcut = QLineEdit()
        self.txtShortcut.setPlaceholderText(_platform_default_shortcut())
        self.txtShortcut.setText(self._cfg.get("shortcut") or _platform_default_shortcut())
        frm.addRow(QLabel("Global shortcut (e.g., Ctrl+Alt+U / Meta+Alt+U):"), self.txtShortcut)

        root.addLayout(frm)

        btns = QHBoxLayout()
        self.btnRestore = QPushButton("Restore default")
        self.btnSave = QPushButton("Save")
        self.btnCancel = QPushButton("Cancel")
        btns.addWidget(self.btnRestore); btns.addStretch(1); self.btnCancel.setDefault(True)
        btns.addWidget(self.btnCancel); btns.addWidget(self.btnSave)
        root.addLayout(btns)

        self.btnRestore.clicked.connect(self.restore_default)
        self.btnSave.clicked.connect(self.save)
        self.btnCancel.clicked.connect(self.reject)

    def restore_default(self):
        self.txtShortcut.setText(_platform_default_shortcut())
        tooltip("Default shortcut restored.", parent=self)

    def save(self):
        new_shortcut = (self.txtShortcut.text() or "").strip() or _platform_default_shortcut()
        if QKeySequence(new_shortcut).toString() == "":
            showInfo("Invalid shortcut. Example: Ctrl+Alt+U (Win/Linux) or Meta+Alt+U (macOS)."); return
        cfg = _get_config(); cfg["shortcut"] = new_shortcut; _write_config(cfg)
        _apply_shortcut_from_config()
        tooltip("Settings saved.", parent=self); self.accept()

# -----------------------------
# Menu / Hook + Global Shortcut
# -----------------------------
_menu_action: Optional[QAction] = None
_global_shortcut: Optional[QShortcut] = None

def open_dialog():
    dlg = UWorldIdsDialog(mw)
    dlg.exec()

def open_config_dialog():
    dlg = ShortcutConfigDialog(mw)
    dlg.exec()

def _apply_shortcut_from_config():
    global _menu_action, _global_shortcut
    cfg = _get_config()
    sc = cfg.get("shortcut") or _platform_default_shortcut()

    if _menu_action is not None:
        _menu_action.setShortcut(QKeySequence(sc))

    if _global_shortcut is not None:
        try:
            _global_shortcut.setParent(None)
        except Exception:
            pass
        _global_shortcut = None

    _global_shortcut = QShortcut(QKeySequence(sc), mw)
    _global_shortcut.activated.connect(open_dialog)

def on_profile_open():
    global _menu_action
    try:
        mw.addonManager.setConfigAction(ADDON_ID, open_config_dialog)
    except Exception:
        try:
            mw.addonManager.setConfigAction(__name__, open_config_dialog)
        except Exception:
            pass

    menu_root = getattr(mw.form, "menuTools", None)
    if not menu_root:
        showInfo("Tools menu not found."); return

    _menu_action = QAction("UWorld IDs → tags → cards", mw)
    _menu_action.triggered.connect(open_dialog)
    menu_root.addAction(_menu_action)

    _apply_shortcut_from_config()

gui_hooks.profile_did_open.append(on_profile_open)
