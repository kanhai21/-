import os
import shutil
import glob
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QAbstractItemView,
    QFileDialog, QApplication, QDialog, QComboBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QAction


# ================= 新增：专属 BGM 库选择弹窗 =================
class BGMSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎵 批量导入 - 选择全局BGM")
        self.resize(450, 200)
        self.selected_bgm = ""

        # 自动创建 BGM 库文件夹
        self.bgm_dir = os.path.join(os.getcwd(), "资源", "BGM_库")
        os.makedirs(self.bgm_dir, exist_ok=True)

        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #e0e0e0; font-size: 14px; font-weight: bold; margin-bottom: 10px; }
            QComboBox { background: #333; color: white; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 13px; }
            QComboBox QAbstractItemView { background-color: #2b2b2b; color: #ffffff; selection-background-color: #1a73e8; }
            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 8px 15px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #1557b0; }
            QPushButton#btn_cancel { background-color: #555; }
            QPushButton#btn_cancel:hover { background-color: #666; }
            QPushButton#btn_browse { background-color: #2e7d32; }
            QPushButton#btn_browse:hover { background-color: #388e3c; }
        """)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("为即将创建的批量项目设置统一的背景音乐 (可选)："))

        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItem("🔇 无 (不设置BGM)", "")

        # 加载库中已有的 BGM
        for f in os.listdir(self.bgm_dir):
            if f.lower().endswith(('.mp3', '.wav', '.m4a', '.flac')):
                self.combo.addItem(f"🎵 {f}", os.path.join(self.bgm_dir, f))

        btn_browse = QPushButton("📂 导入新BGM")
        btn_browse.setObjectName("btn_browse")
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_bgm)

        row.addWidget(self.combo, 1)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        lbl_tip = QLabel("💡 提示：导入的新BGM会自动永久保存到【资源/BGM_库】中，方便下次直接使用。")
        lbl_tip.setStyleSheet("color: #888; font-size: 12px; font-weight: normal; margin-top: 10px;")
        layout.addWidget(lbl_tip)

        layout.addStretch()

        btns = QHBoxLayout()
        btn_ok = QPushButton("✅ 确定并继续")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept_selection)

        btn_cancel = QPushButton("跳过")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def browse_bgm(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择BGM文件", "", "Audio (*.mp3 *.wav *.m4a *.flac)")
        if f:
            try:
                filename = os.path.basename(f)
                dest = os.path.join(self.bgm_dir, filename)
                # 如果库里没有，就自动复制进去
                if not os.path.exists(dest):
                    shutil.copy2(f, dest)

                # 添加到下拉框并自动选中
                self.combo.addItem(f"🎵 {filename}", dest)
                self.combo.setCurrentIndex(self.combo.count() - 1)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入BGM失败: {e}")

    def accept_selection(self):
        self.selected_bgm = self.combo.currentData()
        self.accept()


# =========================================================


class HomePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window  # 这里的 main_window 是 NovelTweetApp 实例
        self.init_ui()
        self.load_recent_projects()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # 标题区域
        title = QLabel("AI 老虎推文软件 Pro")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: bold; color: #4fc3f7; margin-bottom: 10px;")
        layout.addWidget(title)

        subtitle = QLabel("全流程自动化小说推文创作平台")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 16px; color: #aaa; margin-bottom: 30px;")
        layout.addWidget(subtitle)

        # 核心操作按钮组
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)
        btn_layout.addStretch()

        # 标准新建
        btn_new = self.create_big_btn("✨ 新建项目", "#2e7d32", self.main_window.create_new_project_flow)

        # 批量新建 (极速版)
        btn_batch_new = self.create_big_btn("📚 批量创建", "#00796b", self.go_batch_import)

        # 打开项目
        btn_open = self.create_big_btn("📂 打开项目", "#1565c0", self.main_window.open_proj)

        btn_layout.addWidget(btn_new)
        btn_layout.addWidget(btn_batch_new)
        btn_layout.addWidget(btn_open)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 最近项目列表标题区域
        list_header_layout = QHBoxLayout()
        lbl_recent = QLabel("最近编辑的项目")
        lbl_recent.setStyleSheet("font-size: 18px; font-weight: bold; color: #eee;")

        # 批量删除按钮
        btn_del_multi = QPushButton("🗑️ 批量删除选中")
        btn_del_multi.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del_multi.clicked.connect(self.delete_selected_projects)
        btn_del_multi.setStyleSheet("""
            QPushButton {
                background-color: #c62828; 
                color: white; 
                border: 1px solid #ff5252; 
                border-radius: 4px; 
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #d32f2f; }
        """)

        list_header_layout.addWidget(lbl_recent)
        list_header_layout.addStretch()
        list_header_layout.addWidget(btn_del_multi)

        layout.addSpacing(20)
        layout.addLayout(list_header_layout)

        # 项目列表
        self.list_projects = QListWidget()
        # 开启多选模式 (ExtendedSelection: 按Ctrl多选, Shift连选)
        self.list_projects.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_projects.setStyleSheet("""
            QListWidget {
                background-color: #252526;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 10px;
                color: #fff;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 12px;
                margin-bottom: 5px;
                background-color: #2d2d2d;
                border-radius: 6px;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
                border: 1px solid #1a73e8;
            }
            QListWidget::item:selected {
                background-color: #37373d;
                border: 1px solid #4fc3f7;
            }
        """)
        self.list_projects.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_projects.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_projects.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.list_projects)

        # 底部提示
        lbl_hint = QLabel("💡 提示：按住 Ctrl 或 Shift 可选择多个项目进行批量删除")
        lbl_hint.setStyleSheet("color: #666; font-size: 12px;")
        lbl_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(lbl_hint)

    def create_big_btn(self, text, color, func):
        btn = QPushButton(text)
        btn.setFixedSize(160, 50)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(func)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 8px;
                border: 1px solid #ffffff30;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
                border: 1px solid #fff;
                margin-top: -2px; 
            }}
        """)
        return btn

    def load_recent_projects(self):
        self.list_projects.clear()
        projects_dir = os.path.join(os.getcwd(), "资源", "saved_projects")
        if not os.path.exists(projects_dir):
            os.makedirs(projects_dir)
            return

        ntp_files = glob.glob(os.path.join(projects_dir, "*", "*.ntp"))
        ntp_files.sort(key=os.path.getmtime, reverse=True)

        for p in ntp_files:
            name = os.path.basename(p).replace(".ntp", "")
            item = QListWidgetItem(f"📄 {name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list_projects.addItem(item)

    def on_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self.main_window.load_project_file(path)
        else:
            QMessageBox.warning(self, "错误", "项目文件不存在")
            self.load_recent_projects()

    def go_batch_import(self):
        """直接弹出多选音频框，根据音频名自动创建项目，并支持统一设置BGM"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频 (支持多选批量创建)", "", "Audio (*.mp3 *.wav *.m4a)")

        if not files:
            return

        # 核心新增：在开始创建前，询问是否配置全局 BGM
        bgm_dlg = BGMSelectionDialog(self)
        selected_bgm = ""
        if bgm_dlg.exec() == QDialog.DialogCode.Accepted:
            selected_bgm = bgm_dlg.selected_bgm

        count = 0
        total = len(files)

        # 防止数量过大卡死
        open_strategy = True
        if total > 5:
            reply = QMessageBox.question(self, "批量操作确认",
                                         f"您选择了 {total} 个文件。\n全部打开可能会导致软件卡顿。\n\n是否开启【后台极速模式】？\n(即：只创建项目文件，不打开所有标签页)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                open_strategy = False

        for i, f in enumerate(files):
            base_name = os.path.splitext(os.path.basename(f))[0]
            dir_path = os.path.dirname(f)

            # 自动查找同级目录的同名字幕
            srt_path = ""
            potential_srt = os.path.join(dir_path, base_name + ".srt")
            potential_lrc = os.path.join(dir_path, base_name + ".lrc")

            if os.path.exists(potential_srt):
                srt_path = potential_srt
            elif os.path.exists(potential_lrc):
                srt_path = potential_lrc

            # 确定是否打开此标签页
            should_open = open_strategy or (i == total - 1)

            try:
                # 这里的 self.main_window 就是 NovelTweetApp 主程序实例
                self.main_window.create_project_auto(base_name, f, srt_path, open_now=should_open)

                # ================= 核心新增：自动将选择的BGM注入到项目中 =================
                if selected_bgm:
                    if should_open:
                        # 已经被打开并在界面中显示，直接修改对象属性
                        current_editor = self.main_window.tab_widget.currentWidget()
                        if current_editor and hasattr(current_editor, 'data'):
                            if 'export_settings' not in current_editor.data:
                                current_editor.data['export_settings'] = {}
                            current_editor.data['export_settings']['bgm_path'] = selected_bgm
                            # 同步更新UI
                            if hasattr(current_editor, 'import_page'):
                                current_editor.import_page.e_bgm.setText(selected_bgm)
                            current_editor.save_proj(silent=True)
                    else:
                        # 未被打开，直接修改生成的 ntp json文件，安全高效
                        projects_dir = os.path.join(os.getcwd(), "资源", "saved_projects")
                        ntp_path = os.path.join(projects_dir, base_name, f"{base_name}.ntp")
                        if os.path.exists(ntp_path):
                            with open(ntp_path, 'r', encoding='utf-8') as ntp_f:
                                proj_data = json.load(ntp_f)
                            if 'export_settings' not in proj_data:
                                proj_data['export_settings'] = {}
                            proj_data['export_settings']['bgm_path'] = selected_bgm
                            with open(ntp_path, 'w', encoding='utf-8') as ntp_f:
                                json.dump(proj_data, ntp_f, indent=2, ensure_ascii=False)
                # =========================================================================

                count += 1
                QApplication.processEvents()  # 防止界面冻死
            except Exception as e:
                print(f"创建项目 {base_name} 失败: {e}")

        if count > 0:
            msg = f"已批量创建 {count} 个项目！\n(字幕已自动匹配)"
            if selected_bgm:
                msg += f"\n(已为所有项目成功注入背景音乐)"
            if not open_strategy:
                msg += "\n\n(已启用极速模式，仅在后台创建，界面只打开了最后一个。请刷新主页列表查看。)"
            QMessageBox.information(self, "批量创建完成", msg)

    def show_context_menu(self, pos):
        # 兼容多选：如果选了多个，右键菜单显示批量删除
        selected_items = self.list_projects.selectedItems()
        if not selected_items: return

        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #1a73e8; }")

        if len(selected_items) == 1:
            item = selected_items[0]
            action_open = QAction("📂 打开", self)
            action_open.triggered.connect(lambda: self.on_item_double_clicked(item))
            menu.addAction(action_open)

        action_del = QAction(f"🗑️ 删除选中 ({len(selected_items)})", self)
        action_del.triggered.connect(self.delete_selected_projects)
        menu.addAction(action_del)

        menu.exec(self.list_projects.mapToGlobal(pos))

    def delete_selected_projects(self):
        """批量删除逻辑"""
        selected_items = self.list_projects.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先在列表中选择要删除的项目")
            return

        count = len(selected_items)
        if QMessageBox.question(self, "批量删除确认",
                                f"确定要永久删除选中的 {count} 个项目吗？\n此操作不可恢复！",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        success_count = 0
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if not path: continue

            try:
                # 1. 检查是否打开，打开则关闭
                for i in range(self.main_window.tab_widget.count()):
                    widget = self.main_window.tab_widget.widget(i)
                    if hasattr(widget, 'curr_path') and widget.curr_path == path:
                        self.main_window.tab_widget.removeTab(i)
                        break

                # 2. 删除文件夹
                project_dir = os.path.dirname(path)
                if os.path.exists(project_dir):
                    shutil.rmtree(project_dir)
                success_count += 1
            except Exception as e:
                print(f"删除失败 {path}: {e}")

        self.load_recent_projects()
        QMessageBox.information(self, "完成", f"已成功删除 {success_count} 个项目")