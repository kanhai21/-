import json
import os
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QMenu, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt

ROLE_LIB_FILE = os.path.join(os.getcwd(), "资源", "global_roles.json")


class RoleCard(QFrame):
    def __init__(self, index, data, parent_window):
        super().__init__()
        self.index = index
        self.data = data  # dict with 'name', 'desc', 'aliases'
        self.parent_window = parent_window  # ProjectEditor 实例

        self._is_loading = True  # 状态锁：防止在初始化数据时误触发保存

        self.init_ui()
        self.load_data()
        self.load_presets()

        self._is_loading = False

        # 修复：绑定输入框的内容变化信号，实现“实时编辑、实时保存”
        self.edit_name.textChanged.connect(self._auto_save)
        self.edit_aliases.textChanged.connect(self._auto_save)  # 🌟 绑定别名输入框的变动信号
        self.edit_desc.textChanged.connect(self._auto_save)

    def init_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            RoleCard { 
                background-color: #2d2d2d; 
                border: 1px solid #444; 
                border-radius: 8px; 
                margin-bottom: 10px;
            }
            QLabel { color: #bbb; font-weight: bold; }
            QLineEdit, QTextEdit { 
                background: #1e1e1e; 
                border: 1px solid #555; 
                color: #fff; 
                border-radius: 4px; 
                padding: 6px;
                font-size: 13px;
            }
            QLineEdit:focus, QTextEdit:focus { 
                border: 1px solid #1a73e8; 
                background: #000; 
            }
            QComboBox {
                background: #333;
                border: 1px solid #555;
                color: #4fc3f7;
                padding: 5px;
                border-radius: 4px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d;
                color: white;
                selection-background-color: #1a73e8;
                border: 1px solid #555;
            }
            QPushButton { 
                background-color: #3a3a3a; 
                color: #ddd; 
                border: 1px solid #555; 
                padding: 6px 12px; 
                border-radius: 4px; 
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: #4a4a4a; 
                border-color: #1a73e8; 
                color: white;
            }
            QPushButton:pressed { 
                background-color: #1a73e8; 
                border-color: #1a73e8; 
            }
            /* 删除按钮特殊样式 */
            QPushButton#deleteBtn {
                background-color: transparent;
                color: #f44336;
                border: 1px solid #f44336;
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
                min-width: 30px;
                min-height: 30px;
                border-radius: 15px;
            }
            QPushButton#deleteBtn:hover {
                background-color: #f44336;
                color: white;
                border-color: #f44336;
            }
            QPushButton#deleteBtn:pressed {
                background-color: #d32f2f;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 顶部：标题 + 删除按钮
        top_layout = QHBoxLayout()
        self.lbl_title = QLabel(f"角色 #{self.index + 1}")
        self.lbl_title.setStyleSheet("color: #4fc3f7; font-size: 14px;")

        btn_del = QPushButton("×")
        btn_del.setObjectName("deleteBtn")
        btn_del.setToolTip("删除此角色卡片")
        btn_del.clicked.connect(self.delete_self)

        top_layout.addWidget(self.lbl_title)
        top_layout.addStretch()
        top_layout.addWidget(btn_del)
        layout.addLayout(top_layout)

        # 预设选择下拉框
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("📚 绑定库角色:"))
        self.cb_presets = QComboBox()
        self.cb_presets.addItem("-- 选择预设 --", None)
        self.cb_presets.currentIndexChanged.connect(self.on_preset_changed)
        preset_layout.addWidget(self.cb_presets, 1)
        layout.addLayout(preset_layout)

        # 角色名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("名称:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("角色名")
        name_layout.addWidget(self.edit_name)
        layout.addLayout(name_layout)

        # 🌟 优化：新增角色别名/尊称输入框
        alias_layout = QHBoxLayout()
        alias_layout.addWidget(QLabel("别称/绑定词:"))
        self.edit_aliases = QLineEdit()
        self.edit_aliases.setPlaceholderText("多个称呼用逗号分隔，如：林总, 林少, 主人")
        alias_layout.addWidget(self.edit_aliases)
        layout.addLayout(alias_layout)

        # 外貌描述
        desc_layout = QVBoxLayout()
        desc_layout.setSpacing(4)
        desc_layout.addWidget(QLabel("外貌特征 (Prompt):"))
        self.edit_desc = QTextEdit()
        self.edit_desc.setPlaceholderText("在此输入详细的外貌描述...")
        self.edit_desc.setFixedHeight(80)
        desc_layout.addWidget(self.edit_desc)
        layout.addLayout(desc_layout)

        # 底部操作按钮
        btn_layout = QHBoxLayout()

        # 更多操作菜单
        btn_action = QPushButton("⚡ 操作...")
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #1a73e8; }")

        act_infer = menu.addAction("🔍 仅推理此角色")
        act_infer.triggered.connect(lambda: self.parent_window.handle_card_action("infer", self.index))

        act_gen = menu.addAction("🎨 仅生图此角色(相关镜头)")
        act_gen.triggered.connect(lambda: self.parent_window.handle_card_action("gen", self.index))

        btn_action.setMenu(menu)

        # 刷新库按钮
        btn_refresh = QPushButton("🔄")
        btn_refresh.setFixedSize(30, 28)
        btn_refresh.setToolTip("刷新角色库列表")
        btn_refresh.clicked.connect(self.load_presets)

        btn_layout.addWidget(btn_action)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_refresh)

        layout.addLayout(btn_layout)

    def load_data(self):
        self._is_loading = True
        self.edit_name.setText(self.data.get('name', ''))

        # 🌟 优化：加载别名数据，将其转换为逗号分隔的字符串
        aliases = self.data.get('aliases', [])
        if isinstance(aliases, list):
            self.edit_aliases.setText(", ".join(aliases))
        elif isinstance(aliases, str):
            self.edit_aliases.setText(aliases)

        self.edit_desc.setPlainText(self.data.get('desc', ''))
        self._is_loading = False

    def load_presets(self):
        current_text = self.cb_presets.currentText()
        self.cb_presets.blockSignals(True)
        self.cb_presets.clear()
        self.cb_presets.addItem("-- 选择预设 --", None)

        self.global_roles = {}
        if os.path.exists(ROLE_LIB_FILE):
            try:
                # 修复：统一使用 utf-8-sig 以防 BOM 导致的解析失败
                with open(ROLE_LIB_FILE, 'r', encoding='utf-8-sig') as f:
                    self.global_roles = json.load(f)
            except:
                pass

        for name in sorted(self.global_roles.keys()):
            self.cb_presets.addItem(name, name)

        idx = self.cb_presets.findText(current_text)
        if idx != -1:
            self.cb_presets.setCurrentIndex(idx)

        self.cb_presets.blockSignals(False)

    def on_preset_changed(self, index):
        if index <= 0: return

        role_name = self.cb_presets.currentText()
        role_desc = self.global_roles.get(role_name, "")

        if not role_desc: return

        if self.edit_name.text() and self.edit_name.text() != role_name:
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"是否使用库角色【{role_name}】的信息覆盖当前内容？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                self.cb_presets.setCurrentIndex(0)
                return

        # 调用 setText 会触发 textChanged 信号，进而自动触发 _auto_save 保存数据
        self.edit_name.setText(role_name)
        self.edit_desc.setPlainText(role_desc)
        # 从全局库导入暂时不覆盖别称，保留用户手动填写的别称

    def _auto_save(self, *args):
        """将界面的修改实时同步到数据并触发项目保存"""
        if self._is_loading:
            return

        self.data['name'] = self.edit_name.text().strip()

        # 🌟 优化：将用户填写的字符串用逗号切割后保存为列表形式
        aliases_text = self.edit_aliases.text().strip()
        if aliases_text:
            # 兼容中英文逗号
            aliases_text = aliases_text.replace('，', ',')
            self.data['aliases'] = [a.strip() for a in aliases_text.split(',') if a.strip()]
        else:
            self.data['aliases'] = []

        self.data['desc'] = self.edit_desc.toPlainText().strip()

        # 通知主窗口数据已修改并静默保存
        if hasattr(self.parent_window, 'mark_modified'):
            self.parent_window.mark_modified()
        if hasattr(self.parent_window, 'save_proj'):
            self.parent_window.save_proj(silent=True)

    def get_data(self):
        return {
            "name": self.edit_name.text().strip(),
            "aliases": self.data.get('aliases', []),  # 🌟 返回时携带别名
            "desc": self.edit_desc.toPlainText().strip()
        }

    def delete_self(self):
        if self.parent() and self.parent().layout():
            self.parent().layout().removeWidget(self)
            self.deleteLater()