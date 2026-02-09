"""
Rule management dialog: importing / updating rules from a GitHub repository.
"""
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QMessageBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox,
)

from gui.constants import APP_NAME, APP_VERSION, logger
from gui.versioning import read_stored_hash
from gui.workers import RuleFetchWorker
from version import GITHUB_OWNER, GITHUB_REPO


class RuleImportDialog(QMainWindow):
    """Dialog for browsing and importing rules from a GitHub repository."""

    rules_imported = pyqtSignal()

    def __init__(self, local_rules_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Rules")
        self.setMinimumSize(650, 480)
        self.resize(700, 520)
        self._local_rules_dir = local_rules_dir
        self._fetched_rules: List[dict] = []
        self._remote_hashes: dict = {}  # name -> remote sha256 string
        self._worker: Optional[RuleFetchWorker] = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Repository URL row
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Repository URL:"))

        default_api_url = (
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/rules?ref=main"
        )
        self.url_field = QLineEdit(default_api_url)
        self.url_field.setPlaceholderText("GitHub Contents API URL for a rules/ directory")
        url_layout.addWidget(self.url_field, stretch=1)

        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.setProperty("class", "action")
        self.fetch_btn.clicked.connect(self._on_fetch)
        url_layout.addWidget(self.fetch_btn)

        layout.addLayout(url_layout)

        info = QLabel(
            "Enter a GitHub Contents API URL pointing to a rules/ directory, then click Fetch.\n"
            "Select the rules you want to install and click Install Selected."
        )
        info.setObjectName("secondary_label")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Rule list table
        self.rule_table = QTableWidget(0, 3)
        self.rule_table.setHorizontalHeaderLabels(["Install", "Rule Name", "Status"])
        self.rule_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.rule_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rule_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.rule_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rule_table.verticalHeader().setVisible(False)
        layout.addWidget(self.rule_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("dialog_status")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self.deselect_all_btn)

        btn_layout.addStretch()

        self.install_btn = QPushButton("Install Selected")
        self.install_btn.setProperty("class", "primary")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._on_install)
        btn_layout.addWidget(self.install_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    # -- Status helper --
    def _set_status(self, text: str, state: str = ""):
        """Set status label text with themed state (info, success, warn, error, or empty)."""
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # -- Fetch --
    def _on_fetch(self):
        url = self.url_field.text().strip()
        if not url:
            self._set_status("Please enter a URL.", "warn")
            return

        self.fetch_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self._set_status("Fetching rule list...", "info")
        QApplication.processEvents()

        self._worker = RuleFetchWorker(url)
        self._worker.listing_ready.connect(self._on_listing_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker._mode = "list"
        self._worker.start()

    def _on_listing_ready(self, rules: list):
        self._fetched_rules = rules
        self.rule_table.setRowCount(0)

        for row_idx, rule in enumerate(rules):
            self.rule_table.insertRow(row_idx)

            cb = QCheckBox()
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.rule_table.setCellWidget(row_idx, 0, cb_widget)

            name_item = QTableWidgetItem(rule["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.rule_table.setItem(row_idx, 1, name_item)

            # Determine status
            status = self._compute_status(rule["name"])
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.rule_table.setItem(row_idx, 2, status_item)

        count = len(rules)
        if count:
            self._set_status(f"Found {count} rule(s).", "success")
        else:
            self._set_status("No rules found in this repository.", "warn")
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(count > 0)

    def _compute_status(self, rule_name: str) -> str:
        local_rule = self._local_rules_dir / rule_name / "rule.json"
        if not local_rule.exists():
            return "Not installed"

        local_hash = read_stored_hash(local_rule)
        if local_hash is None:
            return "Installed (modified)"

        # We don't have remote hashes at listing time; show "Installed"
        # The full hash comparison happens during install check
        return "Installed"

    def _on_fetch_error(self, message: str):
        self._set_status(f"Fetch failed: {message}", "error")
        self.fetch_btn.setEnabled(True)
        logger.error(f"Rule import: fetch error: {message}")

    # -- Selection helpers --
    def _select_all(self):
        for row in range(self.rule_table.rowCount()):
            widget = self.rule_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(True)

    def _deselect_all(self):
        for row in range(self.rule_table.rowCount()):
            widget = self.rule_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(False)

    def _get_selected_rules(self) -> List[dict]:
        selected = []
        for row in range(self.rule_table.rowCount()):
            widget = self.rule_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    selected.append(self._fetched_rules[row])
        return selected

    # -- Install --
    def _on_install(self):
        selected = self._get_selected_rules()
        if not selected:
            self._set_status("No rules selected.", "warn")
            return

        self.install_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self._set_status("Installing...", "info")
        QApplication.processEvents()

        self._worker = RuleFetchWorker(self.url_field.text().strip())
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.start_download(selected, self._local_rules_dir)

    def _on_download_progress(self, message: str):
        self._set_status(message, "info")
        QApplication.processEvents()

    def _on_download_finished(self, installed: list, errors: list):
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(True)

        if errors:
            error_text = "\n".join(errors)
            QMessageBox.warning(
                self, "Import Errors",
                f"Some rules failed to install:\n\n{error_text}"
            )

        if installed:
            self._refresh_status_column()
            names = ", ".join(installed)

            backup_files: List[str] = []
            for n in installed:
                rule_dir = self._local_rules_dir / n
                backups = sorted(rule_dir.glob("rule.json.bak.*"))
                if backups:
                    backup_files.append(f"  {n}/{backups[-1].name}")

            backup_note = ""
            if backup_files:
                backup_list = "\n".join(backup_files)
                backup_note = (
                    f"\n\nYour previous rule.json file(s) have been backed up:\n"
                    f"{backup_list}\n\n"
                    f"Please review any custom settings (e.g. command_paths) "
                    f"and re-apply them if needed."
                )

            msg = (
                f"Successfully installed: {names}\n\n"
                f"Please review the rules, especially command_paths, to ensure "
                f"they match your system.{backup_note}"
            )
            QMessageBox.information(self, "Rules Installed", msg)
            self.rules_imported.emit()

            self._set_status(f"Installed {len(installed)} rule(s)", "success")
            logger.info(f"Rule import: installed {installed}")
        else:
            self._set_status("No rules were installed.", "warn")

    def _refresh_status_column(self):
        for row in range(self.rule_table.rowCount()):
            name_item = self.rule_table.item(row, 1)
            if name_item:
                status = self._compute_status(name_item.text())
                status_item = self.rule_table.item(row, 2)
                if status_item:
                    status_item.setText(status)
