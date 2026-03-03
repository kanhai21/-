import json
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea,
    QWidget, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from 界面.role_card import RoleCard


class ProjectRoleDialog(QDialog):
    """项目角色管理对话框（模态）"""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window  # ProjectEditor 实例
        self.setWindowTitle("🎭 项目角色设定")
        self.resize(1000, 800)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.init_ui()
        # 连接角色管理器的信号，当角色更新时自动刷新列表
        self.main_window.role_manager.roles_updated.connect(self.load_roles)
        self.load_roles()

    def init_ui(self):
        # 深色主题
        self.setStyleSheet("""
            QDialog { 
                background-color: #1e1e1e; 
                color: #ffffff; 
                font-family: "Microsoft YaHei";
            }
            QPushButton { 
                background: #3a3a3a; 
                color: white; 
                border: 1px solid #555; 
                padding: 6px 12px; 
                border-radius: 4px; 
                font-weight: bold;
            }
            QPushButton:hover { 
                background: #4a4a4a; 
                border-color: #1a73e8; 
            }
            QPushButton:pressed { 
                background: #1a73e8; 
                border-color: #1a73e8; 
            }
            QScrollArea { 
                background-color: #1e1e1e; 
                border: none; 
            }
            QScrollArea > QWidget > QWidget { 
                background-color: #1e1e1e; 
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 顶部按钮栏
        btn_layout = QHBoxLayout()
        btn_extract = QPushButton("🤖 AI 提取角色")
        btn_extract.clicked.connect(self.on_extract_clicked)
        btn_add = QPushButton("➕ 手动添加")
        btn_add.clicked.connect(self.add_empty_role)
        btn_import = QPushButton("📥 导入")
        btn_import.clicked.connect(self.import_roles)
        # 清空角色按钮
        btn_clear = QPushButton("🗑️ 清空角色")
        btn_clear.setStyleSheet("background-color: #c62828; font-weight: bold;")
        btn_clear.clicked.connect(self.clear_roles)
        btn_layout.addWidget(btn_extract)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_import)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 角色卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #1e1e1e;")
        self.card_layout = QVBoxLayout(self.container)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_layout.setSpacing(10)
        scroll.setWidget(self.container)
        layout.addWidget(scroll)

    def load_roles(self):
        """从主窗口数据加载角色卡片"""
        # 稳妥清空现有卡片，防止内存泄漏和重影
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        roles = self.main_window.data.get('role_cards', [])
        for idx, role in enumerate(roles):
            card = RoleCard(idx, role, self.main_window)
            # 自定义删除行为：从数据中删除并刷新
            def new_delete_self(card_obj=card, i=idx):
                # 再次获取最新列表，防止索引越界
                current_roles = self.main_window.data.get('role_cards', [])
                if 0 <= i < len(current_roles):
                    current_roles.pop(i)
                    self.main_window.mark_modified()
                    self.main_window.save_proj(silent=True)
                    self.load_roles()
            card.delete_self = new_delete_self
            self.card_layout.addWidget(card)

    def on_extract_clicked(self):
        """点击 AI 提取角色"""
        self.main_window.run_extract()
        # 提取完成后会通过 roles_updated 信号自动刷新，无需额外操作

    def add_empty_role(self):
        """添加空角色卡片"""
        self.main_window.add_empty_role_card()
        # add_empty_role_card 会通过 roles_updated 信号触发 load_roles

    def import_roles(self):
        """导入角色"""
        self.main_window.import_roles_from_file()
        # 导入后会自动通过 roles_updated 信号刷新

    def clear_roles(self):
        """清空所有角色"""
        if QMessageBox.question(self, "确认清空", "确定要清空当前项目的所有角色吗？此操作不可撤销。",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.main_window.role_manager.clear_roles()
            # clear_roles 会发射 roles_updated 信号，自动刷新