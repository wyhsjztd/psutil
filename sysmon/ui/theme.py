"""配色与全局样式表。

整体参照 Windows 11 任务管理器「性能」页的深色视觉：
低饱和背景、卡片分层、单一强调色、细网格线。
"""
from __future__ import annotations


class C:
    """集中管理颜色，改主题只需动这里。"""

    BG = "#1e1e1e"
    SURFACE = "#272727"
    SURFACE_ALT = "#2d2d2d"
    HOVER = "#323232"
    SELECTED = "#3a3a3a"
    BORDER = "#3a3a3a"

    TEXT = "#f2f2f2"
    TEXT_DIM = "#a0a0a0"
    TEXT_FAINT = "#6e6e6e"

    ACCENT = "#4cc2ff"
    ACCENT_DEEP = "#2b8fc0"

    CPU = "#4cc2ff"
    MEM = "#b180f0"
    DISK = "#f0a35e"
    NET_DOWN = "#4cc2ff"
    NET_UP = "#7ee0a3"
    IO_READ = "#4cc2ff"
    IO_WRITE = "#f0a35e"

    WARN = "#f2b23e"
    DANGER = "#ef5b5b"


QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
}}

QMainWindow {{
    background-color: {C.BG};
}}

QWidget#Root {{
    background-color: {C.BG};
}}

QStackedWidget {{
    background: transparent;
}}

QLabel {{
    color: {C.TEXT};
    background: transparent;
}}

QLabel[role="pageTitle"] {{
    font-size: 22px;
    font-weight: 600;
    color: {C.TEXT};
}}

QLabel[role="subtitle"] {{
    font-size: 12px;
    color: {C.TEXT_DIM};
}}

QLabel[role="statLabel"] {{
    font-size: 12px;
    color: {C.TEXT_DIM};
}}

QLabel[role="statValue"] {{
    font-size: 13px;
    color: {C.TEXT};
}}

QLabel[role="bigValue"] {{
    font-size: 44px;
    font-weight: 600;
    color: {C.TEXT};
}}

QLabel[role="hugeValue"] {{
    font-size: 34px;
    font-weight: 600;
    color: {C.TEXT};
}}

QFrame#Card {{
    background-color: {C.SURFACE};
    border-radius: 8px;
}}

QFrame#ChartCard {{
    background-color: {C.SURFACE};
    border-radius: 8px;
}}

QFrame#TopBar {{
    background-color: {C.BG};
    border-bottom: 1px solid {C.BORDER};
}}

QFrame#NavPanel {{
    background-color: {C.BG};
}}

QFrame#NavCard {{
    background-color: transparent;
    border-radius: 8px;
}}

QFrame#NavCard:hover {{
    background-color: {C.HOVER};
}}

QFrame#NavCard[selected="true"] {{
    background-color: {C.SELECTED};
}}

QFrame#NavBar {{
    background-color: transparent;
    border-radius: 2px;
}}

QFrame#NavBar[active="true"] {{
    background-color: {C.ACCENT};
}}

QPushButton {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {C.HOVER};
}}

QPushButton:pressed {{
    background-color: {C.SELECTED};
}}

QPushButton:checked {{
    background-color: {C.ACCENT_DEEP};
    color: #ffffff;
}}

QComboBox {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    min-width: 72px;
}}

QComboBox:hover {{
    background-color: {C.HOVER};
}}

QComboBox QAbstractItemView {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    selection-background-color: {C.SELECTED};
    outline: none;
}}

QTableWidget, QTableView {{
    background-color: {C.SURFACE};
    alternate-background-color: {C.SURFACE};
    color: {C.TEXT};
    border: none;
    border-radius: 8px;
    gridline-color: transparent;
    font-size: 12px;
    selection-background-color: {C.SELECTED};
    selection-color: {C.TEXT};
}}

QTableWidget::item, QTableView::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {C.SURFACE_ALT};
}}

QLineEdit {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    selection-background-color: {C.ACCENT_DEEP};
}}

QLineEdit:focus {{
    border: 1px solid {C.ACCENT_DEEP};
    background-color: {C.HOVER};
}}

QMenu {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {C.SELECTED};
}}

QHeaderView::section {{
    background-color: {C.SURFACE};
    color: {C.TEXT_DIM};
    border: none;
    border-bottom: 1px solid {C.BORDER};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 500;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: #4a4a4a;
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: #5c5c5c;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QStatusBar {{
    background-color: {C.BG};
    color: {C.TEXT_FAINT};
    font-size: 11px;
}}

QToolTip {{
    background-color: {C.SURFACE_ALT};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 4px 8px;
}}

QProgressBar {{
    background-color: #3a3a3a;
    border: none;
    border-radius: 3px;
}}

QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: 3px;
}}
"""
