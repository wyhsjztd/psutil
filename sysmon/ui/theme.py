"""配色与全局样式表。

设计原则：
- 三层表面（窗口 < 卡片 < 浮起/悬停），靠明度和一条更亮的顶边制造"有厚度"的观感，
  不做真实模糊（Qt Widgets 没有 backdrop-filter，假玻璃在 1Hz 刷新下必然滞后）
- 强调色收敛：主蓝承担绝大多数指标，紫色只给内存，绿色只给上行，
  黄/红仅用于状态告警，避免六个色相同时争夺注意力
- 表格去掉逐行分隔线，改用极淡的斑马纹，减少 300 行数据带来的视觉噪声
"""
from __future__ import annotations


class C:
    """集中管理颜色，改主题只需动这里。

    仅使用 #RRGGBB 形式，保证这些常量既能进 QSS，也能直接构造 QColor。
    """

    # 表面层级
    BG = "#111317"
    SURFACE = "#181B20"
    SURFACE_RAISED = "#1F232A"
    HOVER = "#232830"
    SELECTED = "#2A3039"
    BORDER = "#262B33"
    BORDER_TOP = "#3A414D"
    CARD_BASE = "#181B20"

    # 文本
    TEXT = "#E6E8EB"
    TEXT_DIM = "#9BA1A9"
    TEXT_FAINT = "#6B7280"

    # 强调色
    ACCENT = "#4C9AFF"
    ACCENT_DEEP = "#2F6FD0"
    ACCENT_SOFT = "#2B4C7E"

    # 指标色：主蓝为主，紫色只给内存，绿色只给上行
    CPU = "#4C9AFF"
    MEM = "#A371F7"
    DISK = "#4C9AFF"
    NET_DOWN = "#4C9AFF"
    NET_UP = "#3FB950"
    IO_READ = "#4C9AFF"
    IO_WRITE = "#D29922"

    # 状态色，仅用于告警
    WARN = "#D29922"
    DANGER = "#F85149"


QSS = f"""
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

QLabel#Chevron {{
    color: {C.TEXT_FAINT};
    font-size: 15px;
}}

/* 卡片：上亮下暗的渐变 + 更亮的顶边，模拟受光面 */
QFrame#Card, QFrame#ChartCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1C2026, stop:1 #16191E);
    border: 1px solid {C.BORDER};
    border-top: 1px solid {C.BORDER_TOP};
    border-radius: 10px;
}}

QFrame#TopBar {{
    background-color: {C.BG};
    border-bottom: 1px solid {C.BORDER};
}}

QFrame#NavPanel {{
    background-color: {C.BG};
}}

QPushButton {{
    background-color: {C.SURFACE_RAISED};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {C.HOVER};
    border-top: 1px solid {C.BORDER_TOP};
}}

QPushButton:pressed {{
    background-color: {C.SELECTED};
}}

QPushButton:checked {{
    background-color: {C.ACCENT_DEEP};
    color: #ffffff;
}}

QComboBox {{
    background-color: {C.SURFACE_RAISED};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    min-width: 72px;
}}

QComboBox:hover {{
    background-color: {C.HOVER};
}}

QComboBox QAbstractItemView {{
    background-color: {C.SURFACE_RAISED};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    selection-background-color: {C.SELECTED};
    outline: none;
}}

/* 表格：无逐行分隔线，用极淡斑马纹区分行 */
QTableWidget, QTableView {{
    background-color: transparent;
    alternate-background-color: #1B1F25;
    color: {C.TEXT};
    border: none;
    gridline-color: transparent;
    font-size: 12px;
    selection-background-color: {C.SELECTED};
    selection-color: {C.TEXT};
}}

QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}

QHeaderView {{
    background-color: transparent;
}}

QHeaderView::section {{
    background-color: #1B1F25;
    color: {C.TEXT_DIM};
    border: none;
    border-bottom: 1px solid {C.BORDER};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 500;
}}

QTableCornerButton::section {{
    background-color: #1B1F25;
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background: #343A44;
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: #454D59;
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
    border-top: 1px solid {C.BORDER};
}}

QToolTip {{
    background-color: {C.SURFACE_RAISED};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 4px 8px;
}}

QProgressBar {{
    background-color: #2A2F37;
    border: none;
    border-radius: 3px;
}}

QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: 3px;
}}

QLineEdit {{
    background-color: {C.SURFACE_RAISED};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
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
    background-color: {C.SURFACE_RAISED};
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
"""