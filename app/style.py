"""앱 전역 스타일 (다크)."""

QSS = """
QMainWindow, QDialog { background: #25252a; }
QWidget { color: #e4e4e8; font-size: 12px; }
QLabel#panelTitle { font-size: 13px; font-weight: bold; color: #cfd8dc; padding: 2px 0; }
QLabel#hint { color: #7d848c; font-size: 11px; padding-left: 4px; }
QLabel#statusChip { color: #9aa0a6; padding: 0 8px; }

QMenuBar { background: #1f1f23; }
QMenuBar::item:selected { background: #35353d; }
QMenu { background: #2a2a30; border: 1px solid #44444c; }
QMenu::item:selected { background: #42a5f5; color: #0a0a0a; }
QMenu::item:disabled { color: #777; }

QListWidget, QTableWidget, QPlainTextEdit, QTextBrowser {
  background: #1c1c20; border: 1px solid #38383f; border-radius: 4px; }
QListWidget::item { padding: 5px 6px; }
QListWidget::item:selected { background: #42a5f5; color: #0a0a0a; border-radius: 3px; }
QTableWidget { gridline-color: #2e2e34; selection-background-color: #2f4a66; selection-color: #fff; }
QHeaderView::section { background: #2a2a30; color: #cfd8dc; padding: 4px; border: none; border-bottom: 1px solid #44444c; }
QPlainTextEdit#log { font-size: 11px; font-family: Consolas, monospace; }

QPushButton {
  background: #35353d; border: 1px solid #4a4a54; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover { background: #41414b; }
QPushButton:pressed { background: #2c2c33; }
QPushButton:disabled { color: #777; background: #2c2c31; border-color: #3a3a40; }
QPushButton:checked { background: #42a5f5; color: #0a0a0a; border-color: #42a5f5; }
QPushButton#cutBtn { background: #e53935; color: #fff; font-weight: bold; padding: 6px 16px; border-color: #e53935; }
QPushButton#cutBtn:hover { background: #ef5350; }
QPushButton#exportBtn { background: #42a5f5; color: #0a0a0a; font-weight: bold; border-color: #42a5f5; }
QPushButton#exportBtn:hover { background: #64b5f6; }
QPushButton#exportBtn:disabled { background: #2c3e50; color: #778; }

QPushButton#updateBtn { background: #2e7d32; color: #fff; border-color: #2e7d32; padding: 2px 10px; font-weight: bold; }
QPushButton#updateBtn:hover { background: #43a047; }

QToolButton { padding: 4px 6px; font-size: 13px; border-radius: 4px; }
QToolButton:hover { background: #3a3a44; }
QToolButton#playBtn { font-size: 18px; min-width: 40px; background: #35353d; border: 1px solid #4a4a54; }
QToolButton:checked { background: #42a5f5; color: #0a0a0a; }

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
  background: #1c1c20; border: 1px solid #44444c; border-radius: 4px; padding: 4px 6px; }
QLineEdit:focus, QComboBox:focus { border-color: #42a5f5; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #2a2a30; selection-background-color: #42a5f5; selection-color: #0a0a0a; }

QGroupBox { border: 1px solid #38383f; border-radius: 6px; margin-top: 10px; padding-top: 8px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #cfd8dc; }

QProgressBar { background: #1c1c20; border: 1px solid #38383f; border-radius: 4px; text-align: center; height: 18px; }
QProgressBar::chunk { background: #42a5f5; border-radius: 3px; }

QSlider::groove:horizontal { height: 4px; background: #44444c; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #cfd8dc; border-radius: 6px; }
QSlider::sub-page:horizontal { background: #42a5f5; border-radius: 2px; }

QScrollBar:horizontal { background: #1c1c20; height: 12px; }
QScrollBar::handle:horizontal { background: #4a4a54; border-radius: 5px; min-width: 24px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: #5a5a66; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar:vertical { background: #1c1c20; width: 12px; }
QScrollBar::handle:vertical { background: #4a4a54; border-radius: 5px; min-height: 24px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QSplitter::handle { background: #1f1f23; }
QSplitter::handle:horizontal { width: 4px; }
QStatusBar { background: #1f1f23; color: #9aa0a6; }
QToolTip { background: #111; color: #eee; border: 1px solid #555; padding: 4px; }
QTabWidget::pane { border: 1px solid #38383f; }
QTabBar::tab { background: #2a2a30; padding: 6px 12px; border: 1px solid #38383f; border-bottom: none; }
QTabBar::tab:selected { background: #35353d; color: #7cc4ff; }
QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px; }
"""
