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
    families = [
        "Menlo", "Consolas", "Monaco", "Courier New",
        "Noto Sans Mono", "DejaVu Sans Mono", "monospace"
    ]
    try:
        f.setFamilies(families)  # Qt ≥5.13/Qt6
    except Exception:
        for fam in families:
            try:
                f.setFamily(fam)
                break
            except Exception:
                continue
    try:
        from aqt.qt import QFont as _QF
        f.setStyleHint(_QF.StyleHint.Monospace)  # Qt6
    except Exception:
        for hint_name in ("Monospace", "TypeWriter"):
            try:
                f.setStyleHint(getattr(QFont, hint_name))
                break
            except Exception:
                continue
    return f

# -----------------------------
# Defaults & Config helpers
# -----------------------------
VERSION_LABELS = ["V12", "V11"]
VERSION_VALUE: Dict[str, str] = {"V12": "AK_Step1_v12", "V11": "AK_Step1_v11"}
DEFAULT_VERSION_LABEL = "V12"

STEP_LABELS = ["Step 1", "Step 2", "Step 3"]
DEFAULT_STEP_LABEL = "Step 1"

UWORLD_SEGMENT_V12 = "::#UWorld::Step::"
UWORLD_SEGMENT_V11 = "::#UWorld::"

def _platform_default_shortcut() -> str:
    return "Meta+Alt+U" if sys.platform == "darwin" else "Ctrl+Alt+U"

DEFAULT_CONFIG: Dict[str, Any] = {
    "deck_version_label": DEFAULT_VERSION_LABEL,
    "step_label": DEFAULT_STEP_LABEL,
    "shortcut": "",
}

def _get_config() -> Dict[str, Any]:
    cfg = mw.addonManager.getConfig(ADDON_ID) or {}
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)

    if cfg.get("deck_version_label") not in VERSION_LABELS:
        cfg["deck_version_label"] = DEFAULT_VERSION_LABEL

    if cfg.get("step_label") not in STEP_LABELS:
        cfg["step_label"] = DEFAULT_STEP_LABEL

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
            seen.add(x)
            out.append(x)
    return out

def _esc(s: str) -> str:
    return s.replace('"', r'\"')

def _tag_prefix(deck_version_value: str) -> str:
    base = _normalize_version_prefix(deck_version_value)

    # Step3 V12 ainda usa tags no formato "V11-style":
    #   #AK_Step3_v12::#UWorld::...::...::12345
    # então precisa usar UWORLD_SEGMENT_V11.
    if deck_version_value.endswith("_v11") or deck_version_value == "AK_Step3_v12":
        return base + UWORLD_SEGMENT_V11

    # Demais casos V12 mantêm o formato novo:
    #   #AK_Step1_v12::#UWorld::Step::12345
    #   #AK_Step2_v12::#UWorld::Step::12345
    return base + UWORLD_SEGMENT_V12

def build_tag_or_query(ids: List[str], deck_version_value: str) -> str:
    prefix = _tag_prefix(deck_version_value)
    ids = [i.strip() for i in ids if i and i.strip()]
    if not ids:
        return ""
    parts = [f'tag:"{_esc(prefix + i)}"' for i in ids]
    return "(" + " OR ".join(parts) + ")"

def _compute_ids_summary_v11(deck_version_value: str, ids: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "total_ids_input": len(ids),
        "total_cards": 0,
        "total_ids_without_cards": 0,
        "ids_syntax": "",
        "ids_without_cards": [],
    }

    if not ids:
        return result

    prefix_base = _tag_prefix(deck_version_value)

    all_cids: Set[int] = set()
    ids_without: List[str] = []

    for id_s in ids:
        q_tag = f'tag:"{_esc(prefix_base)}*::{_esc(id_s)}"'
        cids = set(mw.col.find_cards(q_tag))
        if not cids:
            ids_without.append(id_s)
        all_cids.update(cids)

    if ids:
        parts = [
            f'tag:"{_esc(prefix_base)}*::{_esc(i)}"'
            for i in ids
        ]
        ids_syntax = "(" + " OR ".join(parts) + ")"
    else:
        ids_syntax = ""

    result["total_cards"] = len(all_cids)
    result["total_ids_without_cards"] = len(ids_without)
    result["ids_without_cards"] = ids_without
    result["ids_syntax"] = ids_syntax

    return result

def compute_ids_summary(deck_version_value: str, ids_questions: str) -> Dict[str, Any]:
    ids = _extract_unique_int_strings(ids_questions)

    result: Dict[str, Any] = {
        "total_ids_input": len(ids),
        "total_cards": 0,
        "total_ids_without_cards": 0,
        "ids_syntax": "",
        "ids_without_cards": [],
    }

    if not ids:
        return result

    # Step3 V12 deve usar exatamente a mesma lógica de busca do V11,
    # apenas trocando o prefixo para AK_Step3_v12.
    is_v11_style = deck_version_value.endswith("_v11") or deck_version_value == "AK_Step3_v12"

    if is_v11_style:
        return _compute_ids_summary_v11(deck_version_value, ids)

    # V12 "puro" (Step1, Step2 já no formato novo)
    ids_syntax = build_tag_or_query(ids, deck_version_value)
    result["ids_syntax"] = ids_syntax

    if not ids_syntax:
        return result

    cids_all: Set[int] = set(mw.col.find_cards(ids_syntax))

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
# UI - Main Dialog
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

        self.txtIds = QTextEdit()
        self.txtIds.setPlaceholderText(
            "Paste integer IDs separated by comma… e.g. 1,3213,342435,2312"
        )
        self.txtIds.setFixedHeight(90)
        form.addRow(QLabel("ids_questions:"), self.txtIds)

        self.cmbVersion = QComboBox()
        self.cmbVersion.addItems(VERSION_LABELS)
        saved_label = self._cfg.get("deck_version_label") or DEFAULT_VERSION_LABEL
        if saved_label in VERSION_LABELS:
            self.cmbVersion.setCurrentIndex(VERSION_LABELS.index(saved_label))

        self.cmbStep = QComboBox()
        self.cmbStep.addItems(STEP_LABELS)
        saved_step_label = self._cfg.get("step_label") or DEFAULT_STEP_LABEL
        if saved_step_label in STEP_LABELS:
            self.cmbStep.setCurrentIndex(STEP_LABELS.index(saved_step_label))

        version_step_row = QHBoxLayout()
        version_step_row.addWidget(self.cmbVersion)
        version_step_row.addWidget(self.cmbStep)

        form.addRow(QLabel("deck_version:"), version_step_row)

        root.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btnRun = QPushButton("Run")
        self.btnCopySyntax = QPushButton('Copy "IDs (search syntax)"')
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

        self.cmbVersion.currentTextChanged.connect(self._persist_version_now)
        self.cmbStep.currentTextChanged.connect(self._persist_version_now)

        self.btnRun.clicked.connect(self.run_query)
        self.btnCopySyntax.clicked.connect(self.copy_syntax)
        self.btnOpenBrowser.clicked.connect(self.open_in_browser)

        self.txtIds.setFocus()

        self._last_summary: Dict[str, Any] = {}

    def _persist_version_now(self):
        cfg = _get_config()

        label = self.cmbVersion.currentText()
        if label not in VERSION_LABELS:
            label = DEFAULT_VERSION_LABEL
        cfg["deck_version_label"] = label

        step_label = self.cmbStep.currentText()
        if step_label not in STEP_LABELS:
            step_label = DEFAULT_STEP_LABEL
        cfg["step_label"] = step_label

        _write_config(cfg)

    def _current_version_value(self) -> str:
        label = self.cmbVersion.currentText()
        if label not in VERSION_LABELS:
            label = DEFAULT_VERSION_LABEL

        step_label = self.cmbStep.currentText()
        if step_label not in STEP_LABELS:
            step_label = DEFAULT_STEP_LABEL

        try:
            idx = STEP_LABELS.index(step_label) + 1
        except ValueError:
            idx = 1
        step_num = str(idx)

        if label == "V11":
            return f"AK_Step{step_num}_v11"
        else:
            return f"AK_Step{step_num}_v12"

    def _set_busy(self, busy: bool):
        if busy:
            self.lblStatus.setText("Searching…")
            self.progress.setRange(0, 0)
            self.progress.setVisible(True)
            self.btnRun.setEnabled(False)
            self.btnCopySyntax.setEnabled(False)
            self.btnOpenBrowser.setEnabled(False)
            self.lblStatus.repaint()
            self.progress.repaint()
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

    def run_query(self):
        deck_version_value = self._current_version_value()
        ids_questions = self.txtIds.toPlainText()

        self._persist_version_now()
        self._set_busy(True)

        def work(_progress=None):
            return compute_ids_summary(deck_version_value, ids_questions)

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
                self._set_busy(False)

        mw.taskman.run_in_background(work, on_done)

    def copy_syntax(self):
        syntax = self._last_summary.get("ids_syntax") or ""
        if not syntax:
            tooltip("No search syntax to copy.", parent=self)
            return
        QApplication.clipboard().setText(syntax)
        tooltip("Search syntax copied to clipboard.", parent=self)

    def open_in_browser(self):
        syntax = self._last_summary.get("ids_syntax") or ""
        if not syntax:
            tooltip("No search syntax to open.", parent=self)
            return
        try:
            brw = dialogs.open("Browser", mw)
        except Exception as e:
            showInfo(f"Could not open Browser:\n{e}")
            return

        try:
            brw.search_for(syntax)
        except Exception:
            try:
                se = brw.form.searchEdit
                try:
                    se.setText(syntax)
                except Exception:
                    se.lineEdit().setText(syntax)
                brw.onSearchActivated()
            except Exception as e:
                showInfo(f"Could not run search in Browser:\n{e}")
                return

        try:
            brw.activateWindow()
            brw.raise_()
        except Exception:
            pass

        tooltip("Opened in Browser.", parent=self)
        self.accept()

# -----------------------------
# Config Dialog
# -----------------------------
class ShortcutConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UWorld IDs → tags → cards — Settings")
        self.setMinimumWidth(480)

        self._cfg = _get_config()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        frm = QFormLayout()
        frm.setLabelAlignment(QtAlign_Left())
        frm.setSpacing(6)

        self.txtShortcut = QLineEdit()
        self.txtShortcut.setPlaceholderText(_platform_default_shortcut())
        self.txtShortcut.setText(
            self._cfg.get("shortcut") or _platform_default_shortcut()
        )
        frm.addRow(
            QLabel("Global shortcut (e.g., Ctrl+Alt+U / Meta+Alt+U):"),
            self.txtShortcut,
        )

        root.addLayout(frm)

        btns = QHBoxLayout()
        self.btnRestore = QPushButton("Restore default")
        self.btnSave = QPushButton("Save")
        self.btnCancel = QPushButton("Cancel")
        btns.addWidget(self.btnRestore)
        btns.addStretch(1)
        self.btnCancel.setDefault(True)
        btns.addWidget(self.btnCancel)
        btns.addWidget(self.btnSave)
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
            showInfo(
                "Invalid shortcut. Example: Ctrl+Alt+U (Win/Linux) or Meta+Alt+U (macOS)."
            )
            return
        cfg = _get_config()
        cfg["shortcut"] = new_shortcut
        _write_config(cfg)
        _apply_shortcut_from_config()
        tooltip("Settings saved.", parent=self)
        self.accept()

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
    if menu_root:
        _menu_action = QAction("UWorld IDs → tags → cards", mw)
        _menu_action.triggered.connect(open_dialog)
        menu_root.addAction(_menu_action)

    _apply_shortcut_from_config()

gui_hooks.profile_did_open.append(on_profile_open)

# -----------------------------
# Top toolbar button (MANTIDO - área superior direita)
# -----------------------------
def on_top_toolbar_redraw(toolbar):
    """
    Adiciona um botão na área superior direita (ao lado dos outros add-ons).
    """
    toolbar.link_handlers["uworld_ids"] = open_dialog

    js = r"""
    (function() {
        var btnId = 'uworld-ids-btn';
        if (document.getElementById(btnId)) {
            return;
        }

        var topRight = document.querySelector('.top-right') || 
                       document.querySelector('.topbuts') ||
                       document.querySelector('.tdright');
        
        if (!topRight) {
            var allDivs = document.querySelectorAll('div');
            for (var i = 0; i < allDivs.length; i++) {
                if (allDivs[i].style.float === 'right' || 
                    allDivs[i].align === 'right' ||
                    allDivs[i].className.includes('right')) {
                    topRight = allDivs[i];
                    break;
                }
            }
        }

        if (!topRight) {
            console.log('UWorld IDs: Could not find top-right container');
            return;
        }

        var btn = document.createElement('button');
        btn.id = btnId;
        btn.textContent = 'UWIds→Cards';
        btn.title = 'UWorld IDs → tags → cards';
        btn.style.cssText = `
            background: transparent;
            border: 1px solid rgba(255,255,255,0.3);
            color: var(--fg);
            padding: 4px 8px;
            margin: 0 4px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            font-weight: bold;
            transition: all 0.2s;
        `;
        
        btn.onmouseover = function() {
            this.style.background = 'rgba(255,255,255,0.1)';
            this.style.borderColor = 'rgba(255,255,255,0.5)';
        };
        
        btn.onmouseout = function() {
            this.style.background = 'transparent';
            this.style.borderColor = 'rgba(255,255,255,0.3)';
        };
        
        btn.onclick = function(e) {
            e.preventDefault();
            pycmd('uworld_ids');
            return false;
        };

        topRight.insertBefore(btn, topRight.firstChild);
    })();
    """
    toolbar.web.eval(js)

gui_hooks.top_toolbar_did_redraw.append(on_top_toolbar_redraw)

# -----------------------------
# Browser: adiciona botão E item no menu
# -----------------------------
def add_browser_menu(browser):
    """Adiciona item 'UWorld IDs → tags → cards' no menu Edit do Browser."""
    try:
        if hasattr(browser.form, 'menuEdit'):
            action = QAction("UWorld IDs → tags → cards", browser)
            action.triggered.connect(lambda: open_dialog())
            browser.form.menuEdit.addSeparator()
            browser.form.menuEdit.addAction(action)
            print("UWorld IDs: ✓ Item adicionado ao menu Edit do Browser!")
    except Exception as e:
        print(f"UWorld IDs: Erro ao adicionar ao menu Edit - {e}")

def add_browser_toolbar_button(browser):
    """Adiciona botão visual na área do Browser."""
    # Evita duplicação
    if getattr(browser, '_uworld_btn_added', False):
        return
    
    try:
        # Método 1: Tenta adicionar um botão na toolbar do browser
        if hasattr(browser, 'form'):
            # Procura por uma toolbar ou área de botões
            toolbar = None
            
            # Tenta encontrar toolbar
            if hasattr(browser.form, 'toolBar'):
                toolbar = browser.form.toolBar
            elif hasattr(browser.form, 'toolbar'):
                toolbar = browser.form.toolbar
            
            if toolbar:
                btn = QPushButton("📋 UWIds→Cards")
                btn.setToolTip("Open UWorld IDs → tags → cards dialog")
                btn.setStyleSheet("""
                    QPushButton {
                        background: #667eea;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 6px 12px;
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: #7c8ef5;
                    }
                """)
                btn.clicked.connect(lambda: open_dialog())
                toolbar.addWidget(btn)
                browser._uworld_btn_added = True
                print("UWorld IDs: ✓ Botão adicionado à toolbar do Browser!")
                return
        
        # Método 2: Injeta HTML no webview do browser (se disponível)
        if hasattr(browser, 'web') and browser.web:
            js = """
            (function() {
                if (document.getElementById('uworld-browser-btn')) return;
                
                var style = document.createElement('style');
                style.textContent = `
                    #uworld-browser-btn-container {
                        position: fixed;
                        top: 10px;
                        right: 10px;
                        z-index: 9999;
                    }
                    #uworld-browser-btn {
                        background: #667eea;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 8px 16px;
                        font-size: 13px;
                        font-weight: bold;
                        cursor: pointer;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                    }
                    #uworld-browser-btn:hover {
                        background: #7c8ef5;
                    }
                `;
                document.head.appendChild(style);
                
                var container = document.createElement('div');
                container.id = 'uworld-browser-btn-container';
                
                var btn = document.createElement('button');
                btn.id = 'uworld-browser-btn';
                btn.textContent = '📋 UWIds→Cards';
                btn.onclick = function() {
                    pycmd('uworld_browser_open');
                };
                
                container.appendChild(btn);
                document.body.appendChild(container);
            })();
            """
            browser.web.eval(js)
            browser._uworld_btn_added = True
            print("UWorld IDs: ✓ Botão HTML injetado no Browser!")
            return
            
    except Exception as e:
        print(f"UWorld IDs: Erro ao adicionar botão ao Browser - {e}")

def handle_browser_pycmd(handled, message, context):
    """Handler para comandos do botão HTML no Browser."""
    if message == "uworld_browser_open":
        open_dialog()
        return True
    return handled

def on_browser_will_show(browser):
    """Chamado quando o Browser vai ser exibido."""
    from aqt.qt import QTimer
    # Delay para garantir que a UI está montada
    QTimer.singleShot(200, lambda: add_browser_toolbar_button(browser))

gui_hooks.browser_menus_did_init.append(add_browser_menu)
gui_hooks.browser_will_show.append(on_browser_will_show)
gui_hooks.webview_did_receive_js_message.append(handle_browser_pycmd)