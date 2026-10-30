"""程序入口。"""
import os
import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from sysmon.ui.main_window import MainWindow


def resource_path(relative: str) -> str:
    """兼容源码运行与 PyInstaller 单文件打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("系统监视器")
    app.setOrganizationName("sysmon")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    icon_path = resource_path(os.path.join("assets", "icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()