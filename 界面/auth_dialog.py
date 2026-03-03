from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt
from 逻辑.auth_module import AuthManager


class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐 老虎小说推文软件 Pro - 软件授权激活")
        self.setFixedWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
            QLabel {
                font-size: 15px;
                color: #e0e0e0;
            }
            QLineEdit {
                background-color: #252526;
                color: #4fc3f7;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QLineEdit:focus {
                border: 1px solid #1a73e8;
                background-color: #121212;
            }
            QPushButton {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 6px;
                font-weight: bold;
                font-size: 15px;
                min-height: 40px;
                padding: 0px 15px;
            }
            QPushButton:hover { background-color: #444; border-color: #1a73e8; }
            QPushButton:pressed { background-color: #222; }
            #btn_activate {
                background-color: #1a73e8;
                border: none;
                font-size: 16px;
                min-width: 140px;
            }
            #btn_activate:hover { background-color: #1557b0; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(35, 35, 35, 35)
        layout.setSpacing(20)

        lbl_title = QLabel("欢迎使用 老虎小说推文软件 Pro")
        lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #4fc3f7;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_subtitle = QLabel("本软件为付费授权版本，请联系开发者获取激活卡密。")
        lbl_subtitle.setStyleSheet("color: #aaa; font-size: 14px;")
        lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_subtitle)

        layout.addSpacing(15)

        lbl_key = QLabel("🔑 请输入激活卡密：")
        layout.addWidget(lbl_key)

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("请在此粘贴由开发者提供的激活码...")
        layout.addWidget(self.edit_key)

        layout.addSpacing(15)

        btn_layout = QHBoxLayout()
        btn_quit = QPushButton("退出程序")
        btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quit.clicked.connect(self.reject)

        self.btn_activate = QPushButton("🚀 立即激活")
        self.btn_activate.setObjectName("btn_activate")
        self.btn_activate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_activate.clicked.connect(self.verify_and_activate)

        btn_layout.addWidget(btn_quit)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_activate)

        layout.addLayout(btn_layout)

    def verify_and_activate(self):
        key_input = self.edit_key.text().strip()
        if not key_input:
            QMessageBox.warning(self, "提示", "请输入卡密！")
            return

        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("验证中...")
        QApplication.processEvents()

        # 调用核心验证模块（此时底层会自动绑定本机的机器码）
        success, msg = AuthManager.activate_with_key(key_input)

        if success:
            QMessageBox.information(self, "🎉 激活成功", "授权验证通过，硬件已绑定，欢迎使用！")
            self.accept()
        else:
            QMessageBox.critical(self, "❌ 激活失败", msg)
            self.btn_activate.setEnabled(True)
            self.btn_activate.setText("🚀 立即激活")