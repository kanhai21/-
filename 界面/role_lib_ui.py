import json
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QTextEdit, QLineEdit, QLabel, QMessageBox, QFileDialog, QGroupBox,
    QFormLayout, QSplitter, QSizePolicy, QAbstractItemView
)
from PyQt6.QtCore import Qt

ROLE_LIB_FILE = os.path.join(os.getcwd(), "资源", "global_roles.json")


class RoleLibraryDialog(QDialog):
    """全局角色库管理对话框（模态）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📚 全局角色库管理")
        self.resize(1000, 700)
        # 确保对话框是模态的（QDialog 默认模态）
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.roles = {}
        self.init_ui()
        self.load_roles()

    def init_ui(self):
        # 深色高对比度主题，增强层次感
        self.setStyleSheet("""
            QDialog { 
                background-color: #1e1e1e; 
                color: #ffffff; 
                font-family: "Microsoft YaHei"; 
                border: 1px solid #333;
            }
            QLabel { 
                font-size: 14px; 
                font-weight: bold; 
                color: #e0e0e0; 
            }

            /* 列表样式 */
            QListWidget { 
                background: #252526; 
                border: 1px solid #444; 
                color: #fff; 
                font-size: 14px; 
                border-radius: 6px; 
                outline: none; 
                padding: 4px;
            }
            QListWidget::item { 
                padding: 8px; 
                border-bottom: 1px solid #333; 
                border-radius: 4px;
            }
            QListWidget::item:selected { 
                background-color: #1a73e8; 
                color: white; 
                border-left: 4px solid #4fc3f7;
            }
            QListWidget::item:hover { 
                background-color: #333; 
            }

            /* 输入框 */
            QLineEdit, QTextEdit { 
                background: #333; 
                border: 1px solid #555; 
                color: #fff; 
                padding: 8px; 
                border-radius: 4px; 
                font-size: 13px;
            }
            QLineEdit:focus, QTextEdit:focus { 
                border: 1px solid #1a73e8; 
                background: #2d2d2d;
            }

            /* 按钮统一样式 */
            QPushButton { 
                background: #3a3a3a; 
                color: white; 
                border: 1px solid #555; 
                padding: 8px 15px; 
                border-radius: 4px; 
                font-size: 13px;
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
            QPushButton:disabled { 
                background: #2a2a2a; 
                color: #666; 
                border-color: #444;
            }

            /* 分组框 */
            QGroupBox { 
                border: 2px solid #444; 
                border-radius: 8px; 
                margin-top: 15px; 
                padding-top: 15px; 
                font-weight: bold; 
                color: #4fc3f7; 
                font-size: 14px;
                background-color: #252526;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                left: 10px; 
                padding: 0 8px; 
                background: #252526; 
            }

            /* 分割线 */
            QSplitter::handle {
                background: #444;
                width: 2px;
            }
            QSplitter::handle:hover {
                background: #1a73e8;
            }
        """)

        # 主布局：垂直，包含一个分割器
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # 创建水平分割器，允许用户调整左右区域宽度
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setChildrenCollapsible(False)  # 防止子窗口完全折叠

        # === 左侧：角色列表与操作（层次分明） ===
        left_group = QGroupBox("角色列表")
        left_layout = QVBoxLayout(left_group)
        left_layout.setSpacing(10)

        self.list_roles = QListWidget()
        self.list_roles.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.list_roles.currentItemChanged.connect(self.on_role_selected)
        left_layout.addWidget(self.list_roles)

        # 按钮行1：新增/删除
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ 新增角色")
        btn_add.clicked.connect(self.add_role)
        btn_add.setStyleSheet("background-color: #2e7d32; font-weight: bold;")

        btn_del = QPushButton("❌ 删除选中")
        btn_del.clicked.connect(self.delete_role)
        btn_del.setStyleSheet("background-color: #c62828; font-weight: bold;")

        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_del)
        left_layout.addLayout(btn_layout)

        # 按钮行2：导入/导出
        io_layout = QHBoxLayout()
        btn_import = QPushButton("📥 导入 (JSON/TXT)")
        btn_import.clicked.connect(self.import_roles)
        btn_export = QPushButton("📤 导出 (JSON/TXT)")
        btn_export.clicked.connect(self.export_roles)
        io_layout.addWidget(btn_import)
        io_layout.addWidget(btn_export)
        left_layout.addLayout(io_layout)

        splitter.addWidget(left_group)

        # === 右侧：角色详情编辑（层次分明） ===
        right_group = QGroupBox("角色详情编辑")
        right_layout = QFormLayout(right_group)
        right_layout.setSpacing(15)
        right_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("例如：林萧")
        self.edit_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.edit_desc = QTextEdit()
        self.edit_desc.setPlaceholderText("在此输入角色的详细外貌描写，例如：\n黑发，红眼，穿着黑色西装，冷酷气质...")
        self.edit_desc.setMinimumHeight(150)
        self.edit_desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        btn_save = QPushButton("💾 保存修改")
        btn_save.setStyleSheet("background-color: #1565c0; font-weight: bold; padding: 10px;")
        btn_save.clicked.connect(self.save_current_role)

        right_layout.addRow("角色名称:", self.edit_name)
        right_layout.addRow("外貌描述:", self.edit_desc)
        right_layout.addRow("", btn_save)

        # 底部提示
        lbl_hint = QLabel("💡 提示：在此处保存的角色，可以在所有作品的“角色卡片”中直接选择使用。\n"
                          "系统已自动优化文件编码（UTF-8-SIG），解决第一行无法删除的问题。")
        lbl_hint.setStyleSheet("color: #aaa; font-size: 12px; margin-top: 10px;")
        lbl_hint.setWordWrap(True)
        right_layout.addRow(lbl_hint)

        splitter.addWidget(right_group)

        # 设置初始大小比例：左侧占1份，右侧占2份
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter)

    def load_roles(self):
        """从文件加载角色数据，关键修复：使用 utf-8-sig 处理 BOM"""
        self.roles = {}
        if os.path.exists(ROLE_LIB_FILE):
            try:
                # 修复点：使用 utf-8-sig 读取
                with open(ROLE_LIB_FILE, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    # 再次清洗 key，去除首尾空白
                    for k, v in data.items():
                        self.roles[k.strip()] = v
            except Exception as e:
                print(f"加载角色库失败或文件为空: {e}")
                self.roles = {}
        self.refresh_list()

    def refresh_list(self):
        """刷新左侧列表"""
        current_text = None
        if self.list_roles.currentItem():
            current_text = self.list_roles.currentItem().text()

        self.list_roles.clear()
        for name in sorted(self.roles.keys()):
            self.list_roles.addItem(name)

        # 尝试恢复选中状态
        if current_text:
            items = self.list_roles.findItems(current_text, Qt.MatchFlag.MatchExactly)
            if items:
                self.list_roles.setCurrentItem(items[0])

    def save_roles_to_disk(self):
        """保存角色数据到文件，统一使用 utf-8"""
        os.makedirs(os.path.dirname(ROLE_LIB_FILE), exist_ok=True)
        try:
            with open(ROLE_LIB_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.roles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存角色库失败: {e}")

    def on_role_selected(self, current, previous):
        """选中角色时加载详情"""
        if not current:
            return
        name = current.text()
        # 容错处理：如果列表有但字典没有（极端情况）
        desc = self.roles.get(name, "")
        self.edit_name.setText(name)
        self.edit_desc.setPlainText(desc)

    def add_role(self):
        """添加新角色"""
        base_name = "新角色"
        cnt = 1
        name = f"{base_name}_{cnt}"
        while name in self.roles:
            cnt += 1
            name = f"{base_name}_{cnt}"

        self.roles[name] = ""
        self.refresh_list()
        self.save_roles_to_disk()

        items = self.list_roles.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.list_roles.setCurrentItem(items[0])
            self.edit_name.setFocus()
            self.edit_name.selectAll()

    def delete_role(self):
        """删除选中的角色"""
        item = self.list_roles.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择要删除的角色！")
            return

        name = item.text()

        # 修复：提供明确的确认提示，捕获用户操作
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要从库中删除预设角色【{name}】吗？\n(注：不会影响已在作品中使用的角色)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # 修复点：增加容错判断，确保即便有空格也能精准删除
            deleted = False
            if name in self.roles:
                del self.roles[name]
                deleted = True
            elif name.strip() in self.roles:
                del self.roles[name.strip()]
                deleted = True

            if deleted:
                self.save_roles_to_disk()
                self.refresh_list()
                self.edit_name.clear()
                self.edit_desc.clear()
            else:
                QMessageBox.warning(self, "错误", "字典中未找到该角色，可能是编码问题，已重新加载数据，请重试。")
                self.load_roles()  # 重新加载以修复内存状态

    def save_current_role(self):
        """保存当前编辑的角色"""
        current_item = self.list_roles.currentItem()
        new_name = self.edit_name.text().strip()
        new_desc = self.edit_desc.toPlainText().strip()

        if not new_name:
            QMessageBox.warning(self, "错误", "角色名称不能为空")
            return

        # 如果没选中任何项（比如直接打字新增）
        if not current_item:
            # 修复：发现角色已存在时，弹出替换确认框，而不是直接拦截报错
            if new_name in self.roles:
                reply = QMessageBox.question(self, "确认覆盖",
                                             f"预设角色【{new_name}】已存在，是否覆盖替换其预设内容？",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return

            self.roles[new_name] = new_desc
            self.save_roles_to_disk()
            self.refresh_list()
            QMessageBox.information(self, "成功", "角色保存成功！")
            return

        old_name = current_item.text()

        # 修改名字的情况
        if old_name != new_name:
            # 修复：修改名字如果和库里的重复，也弹出是否覆盖的确认框
            if new_name in self.roles:
                reply = QMessageBox.question(self, "确认覆盖",
                                             f"预设角色【{new_name}】已存在，是否将其覆盖替换？",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # 删除旧名
            if old_name in self.roles:
                del self.roles[old_name]

        self.roles[new_name] = new_desc
        self.save_roles_to_disk()
        self.refresh_list()

        # 重新选中（因为名字可能变了）
        items = self.list_roles.findItems(new_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.list_roles.setCurrentItem(items[0])

        QMessageBox.information(self, "成功", "角色修改保存成功！")

    def import_roles(self):
        """导入角色数据（支持 JSON 或 TXT），修复编码问题"""
        path, _ = QFileDialog.getOpenFileName(self, "导入角色库", "",
                                              "角色库文件 (*.json *.txt);;JSON 文件 (*.json);;文本文件 (*.txt)")
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.json':
                self._import_json(path)
            elif ext == '.txt':
                self._import_txt(path)
            else:
                QMessageBox.warning(self, "错误", "不支持的文件格式")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _import_json(self, path):
        """导入 JSON 格式，使用 utf-8-sig"""
        with open(path, 'r', encoding='utf-8-sig') as f:
            new_roles = json.load(f)

        if isinstance(new_roles, dict):
            for k, v in new_roles.items():
                self.roles[k.strip()] = v
        elif isinstance(new_roles, list):
            for item in new_roles:
                if isinstance(item, dict) and 'name' in item:
                    name = item['name'].strip()
                    desc = item.get('desc', '')
                    self.roles[name] = desc
        else:
            raise Exception("JSON 格式不支持，应为字典或列表")

        self.save_roles_to_disk()
        self.refresh_list()
        QMessageBox.information(self, "成功", f"已导入 {len(new_roles)} 个角色（JSON）")

    def _import_txt(self, path):
        """导入 TXT 格式，使用 utf-8-sig"""
        count = 0
        with open(path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # 支持中文冒号和英文冒号
                colon_pos = -1
                for colon in [':', '：']:
                    pos = line.find(colon)
                    if pos != -1:
                        colon_pos = pos
                        break

                if colon_pos == -1:
                    name = line
                    desc = ""
                else:
                    name = line[:colon_pos].strip()
                    desc = line[colon_pos + 1:].strip()

                if name:
                    self.roles[name] = desc
                    count += 1

        self.save_roles_to_disk()
        self.refresh_list()
        QMessageBox.information(self, "成功", f"已导入 {count} 个角色（TXT）")

    def export_roles(self):
        """导出角色数据（支持 JSON 或 TXT）"""
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出角色库", "global_roles_backup",
            "JSON 文件 (*.json);;文本文件 (*.txt)"
        )
        if not path:
            return

        if '.' not in os.path.basename(path):
            if "JSON" in selected_filter:
                path += '.json'
            elif "文本" in selected_filter:
                path += '.txt'

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.json':
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.roles, f, indent=2, ensure_ascii=False)
            elif ext == '.txt':
                with open(path, 'w', encoding='utf-8') as f:
                    for name, desc in self.roles.items():
                        f.write(f"{name}: {desc}\n")
            else:
                QMessageBox.warning(self, "错误", "不支持的文件扩展名，请使用 .json 或 .txt")
                return
            QMessageBox.information(self, "成功", f"导出成功到：{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))