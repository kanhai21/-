import os
import glob
import json
import shutil
import configparser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox, QComboBox, QLineEdit, QSplitter,
    QProgressBar, QTextEdit, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer
from 配置.app_config import CONFIG_FILE

# 指定项目的保存根目录
PROJECTS_ROOT_DIR = os.path.join(os.getcwd(), "资源", "saved_projects")


class BatchExportPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.current_drafts_root = ""
        # 🌟 核心升级：初始化时扫描所有剪映本地草稿作为模板库
        self.templates_list = self.get_jianying_templates()
        self.init_ui()
        self.load_projects()

        # 🌟 状态监控定时器：用于自动重置中止按钮的状态
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._check_batch_status)
        self.status_timer.start(1000)

    def get_jianying_templates(self):
        """自动扫描剪映本地草稿目录，提取可用模板"""
        drafts_root = ""

        # 1. 优先尝试从软件全局配置读取剪映路径
        try:
            cfg = configparser.ConfigParser()
            for enc in ['utf-8', 'utf-8-sig', 'gbk']:
                try:
                    with open(CONFIG_FILE, 'r', encoding=enc) as f:
                        cfg.read_file(f)
                    break
                except:
                    continue
            if 'DEFAULT' in cfg and cfg['DEFAULT'].get('jianying_path'):
                drafts_root = cfg['DEFAULT']['jianying_path'].strip().strip('"').strip("'")
        except Exception:
            pass

        # 2. 如果配置里没有，则智能穷举常见路径
        if not drafts_root or not os.path.exists(drafts_root):
            paths_to_try = [
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "JianyingPro", "User Data", "Projects",
                             "com.lveditor.draft"),
                os.path.join(os.path.expanduser("~"), "Documents", "JianyingPro Drafts"),
                r"D:\APP\剪映\JianyingPro Drafts",
                r"E:\JianyingPro Drafts"
            ]
            for p in paths_to_try:
                if os.path.exists(p):
                    drafts_root = p
                    break

        self.current_drafts_root = drafts_root

        templates = []
        if drafts_root and os.path.exists(drafts_root):
            try:
                for d in os.listdir(drafts_root):
                    full_path = os.path.join(drafts_root, d)
                    if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, "draft_content.json")):
                        templates.append((d, full_path))
            except Exception:
                pass

        # 按修改时间排序，刚在剪映里做好的模板排在最前面
        templates.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
        return templates

    def change_draft_path(self):
        """手动更改剪映草稿目录，并保存到配置"""
        folder = QFileDialog.getExistingDirectory(self, "请选择您的【剪映草稿总目录】", self.current_drafts_root or "")
        if folder:
            self.current_drafts_root = folder
            if hasattr(self, 'lbl_draft_path'):
                self.lbl_draft_path.setText(f"草稿目录: {folder}")

            # 保存回配置文件
            try:
                cfg = configparser.ConfigParser()
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg.read_file(f)
                if 'DEFAULT' not in cfg:
                    cfg['DEFAULT'] = {}
                cfg['DEFAULT']['jianying_path'] = folder
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    cfg.write(f)
            except Exception as e:
                print(f"保存剪映路径配置失败: {e}")

            # 重新加载列表和下拉框
            self.load_projects()
            QMessageBox.information(self, "成功", "已成功绑定剪映草稿目录，模板已更新！")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("📤 批量导出草稿 (后台静默模式)")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #4fc3f7; margin-bottom: 10px;")
        main_layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #444; width: 2px; }")

        # ================= 左侧：项目高级表格面板 =================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)

        header_layout = QHBoxLayout()
        lbl_list = QLabel("📦 选择要导出的项目与专属配置")
        lbl_list.setStyleSheet("font-weight: bold; font-size: 14px; color: #ddd;")

        # 刷新数据按钮
        btn_refresh = QPushButton("🔄 刷新列表")
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.clicked.connect(self.load_projects)
        btn_refresh.setStyleSheet("""
            QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 4px 10px; border-radius: 4px; }
            QPushButton:hover { background-color: #444; border-color: #1a73e8; }
        """)

        header_layout.addWidget(lbl_list)
        header_layout.addStretch()
        header_layout.addWidget(btn_refresh)
        left_layout.addLayout(header_layout)

        # 核心升级：将普通列表改为高级表格，增加【套用模板】列
        self.table = QTableWidget()
        self.table.setColumnCount(4)  # 🌟 改为 4 列
        self.table.setHorizontalHeaderLabels(["选择", "项目名称", "套用剪映模板 (默认无)", "专属 BGM (留空无)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 180)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(45)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #252526; color: white; border: 1px solid #444; border-radius: 6px; font-size: 13px; }
            QTableWidget::item { border-bottom: 1px solid #333; }
            QHeaderView::section { background-color: #333; color: white; font-weight: bold; padding: 8px; border: none; }
            QTableWidget::indicator { width: 18px; height: 18px; border: 1px solid #666; border-radius: 3px; background: #1e1e1e; margin-left: 5px;}
            QTableWidget::indicator:checked { background: #1a73e8; border: 1px solid #1a73e8; }
        """)
        left_layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_sel_all = QPushButton("☑️ 全选")
        btn_sel_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sel_all.clicked.connect(self.select_all)

        btn_unsel = QPushButton("🔲 反选")
        btn_unsel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_unsel.clicked.connect(self.unselect_all)

        for btn in [btn_sel_all, btn_unsel]:
            btn.setStyleSheet(
                "QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 6px; border-radius: 4px; } QPushButton:hover { background-color: #444; border-color: #1a73e8;}")

        btn_box.addWidget(btn_sel_all)
        btn_box.addWidget(btn_unsel)
        left_layout.addLayout(btn_box)

        # ================= 右侧：全局参数设置与监控大屏 =================
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)

        lbl_settings = QLabel("⚙️ 全局导出覆盖与控制台")
        lbl_settings.setStyleSheet("font-weight: bold; font-size: 14px; color: #ddd;")
        right_layout.addWidget(lbl_settings)

        combo_style = """
            QComboBox { 
                background: #333; color: white; border: 1px solid #555; padding: 6px; border-radius: 4px; min-width: 150px; 
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b; color: #ffffff; selection-background-color: #1a73e8; selection-color: #ffffff; outline: none; border: 1px solid #555;
            }
        """

        # 🌟 0. 批量剪映模板覆盖 (新增核心功能)
        grp_tpl = QGroupBox("🎬 批量模板覆盖")
        grp_tpl.setStyleSheet("""
            QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 15px; padding-top: 20px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }
        """)
        lyt_tpl = QVBoxLayout(grp_tpl)

        # --- 新增：智能路径显示与修改按钮 ---
        row_path = QHBoxLayout()
        self.lbl_draft_path = QLabel(f"草稿目录: {self.current_drafts_root or '未找到目录，请手动指定'}")
        self.lbl_draft_path.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        self.lbl_draft_path.setWordWrap(True)
        btn_change_path = QPushButton("⚙️ 定位草稿目录")
        btn_change_path.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_change_path.setStyleSheet(
            "QPushButton { background-color: #333; color: white; padding: 4px 8px; border-radius: 4px; border: 1px solid #555; } QPushButton:hover { background-color: #444; border-color: #1a73e8; }")
        btn_change_path.clicked.connect(self.change_draft_path)
        row_path.addWidget(self.lbl_draft_path, stretch=1)
        row_path.addWidget(btn_change_path)
        lyt_tpl.addLayout(row_path)
        # -----------------------------------

        self.combo_global_tpl = QComboBox()
        self.combo_global_tpl.setStyleSheet(combo_style)
        self.combo_global_tpl.addItem("🚫 不使用模板 (默认原生导出)", "")
        for name, path in self.templates_list:
            self.combo_global_tpl.addItem(f"📄 {name}", path)

        btn_apply_tpl = QPushButton("⬇️ 将此模板一键覆盖到左侧选中的项目")
        btn_apply_tpl.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_tpl.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; font-weight: bold; padding: 8px; border-radius: 4px; border: none; } QPushButton:hover { background-color: #1976d2; }")
        btn_apply_tpl.clicked.connect(self.apply_global_template)

        lyt_tpl.addWidget(self.combo_global_tpl)
        lyt_tpl.addWidget(btn_apply_tpl)
        right_layout.addWidget(grp_tpl)

        # 1. 批量 BGM 覆盖设置
        grp_bgm = QGroupBox("🎵 批量 BGM 覆盖")
        grp_bgm.setStyleSheet("""
            QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 15px; padding-top: 20px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }
        """)
        lyt_bgm = QVBoxLayout(grp_bgm)

        row1_bgm = QHBoxLayout()
        self.combo_global_bgm = QComboBox()
        self.combo_global_bgm.addItem("🔇 留空 (清空BGM)", "")
        self.combo_global_bgm.setStyleSheet(combo_style)

        # 自动加载 BGM_库
        self.bgm_dir = os.path.join(os.getcwd(), "资源", "BGM_库")
        os.makedirs(self.bgm_dir, exist_ok=True)
        for f in os.listdir(self.bgm_dir):
            if f.lower().endswith(('.mp3', '.wav', '.m4a', '.flac')):
                self.combo_global_bgm.addItem(f"🎵 {f}", os.path.join(self.bgm_dir, f))

        btn_global_browse = QPushButton("📂 导入新库")
        btn_global_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_global_browse.setStyleSheet(
            "QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 6px 10px; border-radius: 4px; } QPushButton:hover { background-color: #444; border-color: #1a73e8; }")
        btn_global_browse.clicked.connect(self.browse_global_bgm)

        row1_bgm.addWidget(self.combo_global_bgm, 1)
        row1_bgm.addWidget(btn_global_browse)

        btn_apply_bgm = QPushButton("⬇️ 将此 BGM 一键覆盖到左侧选中的项目")
        btn_apply_bgm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_bgm.setStyleSheet(
            "QPushButton { background-color: #e65100; color: white; font-weight: bold; padding: 8px; border-radius: 4px; border: none; } QPushButton:hover { background-color: #ef6c00; }")
        btn_apply_bgm.clicked.connect(self.apply_global_bgm)

        lyt_bgm.addLayout(row1_bgm)
        lyt_bgm.addWidget(btn_apply_bgm)
        right_layout.addWidget(grp_bgm)

        # 2. 视频画幅设置
        grp_ratio = QGroupBox("🎬 视频画幅")
        grp_ratio.setStyleSheet("""
            QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 15px; padding-top: 20px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }
        """)
        lyt_ratio = QHBoxLayout(grp_ratio)
        lyt_ratio.addWidget(QLabel("比例选择:"))
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItems(["16:9 (横屏)", "9:16 (竖屏)", "4:3 (老电视)", "1:1 (正方形)"])
        self.combo_ratio.setStyleSheet(combo_style)
        lyt_ratio.addWidget(self.combo_ratio)
        lyt_ratio.addStretch()
        right_layout.addWidget(grp_ratio)

        # 3. 字幕样式设置
        grp_sub = QGroupBox("📝 字幕样式")
        grp_sub.setStyleSheet("""
            QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 15px; padding-top: 20px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }
        """)
        lyt_sub = QVBoxLayout(grp_sub)

        lbl_sub_hint = QLabel("💡 提示：若【特效 ID】留空，则自动使用默认的基础花字样式。")
        lbl_sub_hint.setStyleSheet("color: #888; font-style: italic; font-size: 12px; margin-bottom: 5px;")
        lyt_sub.addWidget(lbl_sub_hint)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("热门预设:"))
        self.combo_sub_preset = QComboBox()
        self.combo_sub_preset.setStyleSheet(combo_style)

        # 预设字典：映射名称和对应的剪映内部特效ID
        self.presets = {
            "默认 (黑底白字)": "",
            "综艺-黄蓝撞色": "742111",
            "综艺-清新渐变": "742112",
            "红色描边-醒目": "742113",
            "黄色粗体-解说常用": "742114",
            "蓝色发光-科技感": "742115",
            "粉色少女-可爱": "742116"
        }
        self.combo_sub_preset.addItems(self.presets.keys())
        self.combo_sub_preset.currentIndexChanged.connect(self.on_preset_changed)
        row1.addWidget(self.combo_sub_preset)
        row1.addStretch()
        lyt_sub.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("特效 ID:  "))
        self.edit_sub_id = QLineEdit()
        self.edit_sub_id.setStyleSheet(
            "QLineEdit { background: #1e1e1e; border: 1px solid #555; color: #fff; padding: 6px; border-radius: 4px; } QLineEdit:focus { border: 1px solid #1a73e8; }")
        self.edit_sub_id.setPlaceholderText("选择预设自动填入，或手动输入剪映花字ID")
        row2.addWidget(self.edit_sub_id)
        lyt_sub.addLayout(row2)

        right_layout.addWidget(grp_sub)

        # ====== 全局进度条与实时输出控制台 ======
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("等待启动...")
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; color: white; font-weight: bold; background-color: #252526; min-height: 22px; margin-top: 15px;}
            QProgressBar::chunk { background-color: #1a73e8; border-radius: 3px; }
        """)
        right_layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("""
            QTextEdit { background-color: #1e1e1e; color: #ccc; border: 1px solid #555; border-radius: 4px; font-family: Consolas; font-size: 13px; margin-top: 5px;}
        """)
        right_layout.addWidget(self.log_view)
        # ============================================

        # 🌟 核心升级：增加排队干预双按钮结构
        btn_action_layout = QHBoxLayout()

        self.btn_run = QPushButton("🚀 启动后台批量导出")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setFixedHeight(50)
        self.btn_run.setStyleSheet("""
            QPushButton { background-color: #2e7d32; color: white; font-size: 16px; font-weight: bold; border-radius: 8px; border: 1px solid #1b5e20; margin-top: 10px;} 
            QPushButton:hover { background-color: #388e3c; }
            QPushButton:pressed { background-color: #1b5e20; }
            QPushButton:disabled { background-color: #555; color: #999; border: 1px solid #444; }
        """)
        self.btn_run.clicked.connect(self.run_batch_export)

        self.btn_stop = QPushButton("🛑 中止并清空队列")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setFixedHeight(50)
        self.btn_stop.setEnabled(False)  # 默认置灰，运行中才激活
        self.btn_stop.setStyleSheet("""
            QPushButton { background-color: #c62828; color: white; font-size: 14px; font-weight: bold; border-radius: 8px; border: 1px solid #b71c1c; margin-top: 10px;} 
            QPushButton:hover { background-color: #e53935; }
            QPushButton:pressed { background-color: #b71c1c; }
            QPushButton:disabled { background-color: #555; color: #999; border: 1px solid #444; }
        """)
        self.btn_stop.clicked.connect(self.stop_batch_export)

        btn_action_layout.addWidget(self.btn_run, stretch=7)
        btn_action_layout.addWidget(self.btn_stop, stretch=3)
        right_layout.addLayout(btn_action_layout)

        # 调整左右比例，左侧加宽以显示表格
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([850, 350])  # 加宽左侧区域以容纳新列

        main_layout.addWidget(splitter)

    def _check_batch_status(self):
        """实时监听底层队列状态，以重置按钮"""
        if hasattr(self, 'batch_manager'):
            if not self.batch_manager.is_batch_processing and self.btn_stop.isEnabled():
                # 说明队列已自然完成，重置UI
                self.btn_stop.setEnabled(False)

    # 🌟 核心新增：中途强制干预能力
    def stop_batch_export(self):
        if hasattr(self, 'batch_manager'):
            reply = QMessageBox.question(self, "确认中止",
                                         "确认要清空等待队列并停止批量导出吗？\n（当前正在导出的最后一个项目会继续完成，后续的将被丢弃）",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.batch_manager.batch_queue.clear()
                self.batch_manager.is_batch_processing = False
                self.append_log("🛑 队列已被用户手动清空，后续任务已取消！")
                self.btn_run.setEnabled(True)
                self.btn_run.setText("🚀 启动后台批量静默导出")
                self.btn_stop.setEnabled(False)
                self.progress_bar.setFormat("任务已中止")

    # 🌟 浏览单行专属模板一键覆盖
    def apply_global_template(self):
        tpl_path = self.combo_global_tpl.currentData()
        if tpl_path is None: tpl_path = ""

        count = 0
        for i in range(self.table.rowCount()):
            chk = self.table.item(i, 0)
            if chk.checkState() == Qt.CheckState.Checked:
                # 模板列是索引 2
                widget = self.table.cellWidget(i, 2)
                if widget:
                    combo = widget.findChild(QComboBox)
                    if combo:
                        idx = combo.findData(tpl_path)
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                            count += 1

        if count > 0:
            QMessageBox.information(self, "覆盖成功",
                                    f"✅ 已成功将该模板设定应用到左侧 {count} 个勾选的项目！")
        else:
            QMessageBox.warning(self, "提示", "请先在左侧列表中【勾选】需要应用模板的项目！")

    # 浏览单行专属BGM
    def browse_row_bgm(self, row, line_edit):
        f, _ = QFileDialog.getOpenFileName(self, "为该项目单独配置BGM", "", "Audio (*.mp3 *.wav *.m4a *.flac)")
        if f:
            dest = os.path.join(self.bgm_dir, os.path.basename(f))
            if not os.path.exists(dest):
                try:
                    shutil.copy2(f, dest)
                except:
                    pass
            line_edit.setText(dest)

    # 浏览全局BGM库
    def browse_global_bgm(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择并导入BGM到全局库", "", "Audio (*.mp3 *.wav *.m4a *.flac)")
        if f:
            dest = os.path.join(self.bgm_dir, os.path.basename(f))
            if not os.path.exists(dest):
                try:
                    shutil.copy2(f, dest)
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"导入失败: {e}")
                    return

            # 判断是否已经在列表中
            for i in range(self.combo_global_bgm.count()):
                if self.combo_global_bgm.itemData(i) == dest:
                    self.combo_global_bgm.setCurrentIndex(i)
                    return

            self.combo_global_bgm.addItem(f"🎵 {os.path.basename(f)}", dest)
            self.combo_global_bgm.setCurrentIndex(self.combo_global_bgm.count() - 1)

    # 一键覆盖 BGM 到左侧表格
    def apply_global_bgm(self):
        bgm_path = self.combo_global_bgm.currentData()
        if bgm_path is None: bgm_path = ""

        count = 0
        for i in range(self.table.rowCount()):
            chk = self.table.item(i, 0)
            if chk.checkState() == Qt.CheckState.Checked:
                # BGM列现在是索引 3
                widget = self.table.cellWidget(i, 3)
                if widget:
                    le = widget.findChild(QLineEdit)
                    if le:
                        le.setText(bgm_path)
                        count += 1

        if count > 0:
            QMessageBox.information(self, "覆盖成功",
                                    f"✅ 已成功将该 BGM 设定应用到左侧 {count} 个勾选的项目！\n(可在左侧表格中检查)")
        else:
            QMessageBox.warning(self, "提示", "请先在左侧列表中【勾选】需要应用 BGM 的项目！")

    # 日志输出与滚动条自动追踪
    def append_log(self, text):
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if "❌" in text or "失败" in text:
            color = "#ff5555"
        elif "✅" in text or "成功" in text:
            color = "#55ff55"
        elif "⚠️" in text:
            color = "#ffaa00"
        elif "🚀" in text or "➡️" in text:
            color = "#4fc3f7"
        else:
            color = "#dddddd"
        self.log_view.append(
            f"<span style='color:#888;'>[{timestamp}]</span> <span style='color:{color};'>{text}</span>")
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # 更新进度条
    def update_progress(self, current, total):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"总进度: {current} / {total} 项 ({pct}%)")
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("等待启动...")

    def load_projects(self):
        """加载本地的 .ntp 项目文件列表，并构建交互表格"""
        self.table.setRowCount(0)
        # 刷新模板列表
        self.templates_list = self.get_jianying_templates()

        # 同步刷新右侧全局模板下拉框
        if hasattr(self, 'combo_global_tpl'):
            self.combo_global_tpl.clear()
            self.combo_global_tpl.addItem("🚫 不使用模板 (默认原生导出)", "")
            for t_name, t_path in self.templates_list:
                self.combo_global_tpl.addItem(f"📄 {t_name}", t_path)
            if hasattr(self, 'lbl_draft_path'):
                self.lbl_draft_path.setText(f"草稿目录: {self.current_drafts_root or '未找到目录，请手动指定'}")

        if os.path.exists(PROJECTS_ROOT_DIR):
            ntp_files = glob.glob(os.path.join(PROJECTS_ROOT_DIR, "*", "*.ntp"))
            ntp_files.sort(key=os.path.getmtime, reverse=True)
            self.table.setRowCount(len(ntp_files))

            for i, p in enumerate(ntp_files):
                # 尝试读取项目原本保存的数据
                current_bgm = ""
                current_tpl = ""
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    current_bgm = data.get('export_settings', {}).get('bgm_path', '')
                    current_tpl = data.get('export_settings', {}).get('template_path', '')
                except:
                    pass

                # 0. Checkbox
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(Qt.CheckState.Unchecked)
                chk.setData(Qt.ItemDataRole.UserRole, p)
                self.table.setItem(i, 0, chk)

                # 1. Name
                name = os.path.basename(p).replace(".ntp", "")
                name_item = QTableWidgetItem(f"📄 {name}")
                name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 1, name_item)

                # 🌟 2. 专属套用模板选择框
                tpl_widget = QWidget()
                tpl_layout = QHBoxLayout(tpl_widget)
                tpl_layout.setContentsMargins(5, 2, 5, 2)
                combo_tpl = QComboBox()
                combo_tpl.setStyleSheet(
                    "QComboBox { background: #1e1e1e; border: 1px solid #555; color: #fff; padding: 4px; border-radius: 4px; font-size: 12px;}"
                )
                combo_tpl.addItem("🚫 不使用模板", "")

                # 填入本地扫描到的模板
                for t_name, t_path in self.templates_list:
                    combo_tpl.addItem(f"📄 {t_name}", t_path)

                # 恢复之前保存的模板选择
                if current_tpl:
                    idx = combo_tpl.findData(current_tpl)
                    if idx >= 0:
                        combo_tpl.setCurrentIndex(idx)

                tpl_layout.addWidget(combo_tpl)
                self.table.setCellWidget(i, 2, tpl_widget)

                # 3. 专属 BGM 输入框与浏览按钮
                bgm_widget = QWidget()
                bgm_layout = QHBoxLayout(bgm_widget)
                bgm_layout.setContentsMargins(5, 2, 5, 2)

                le_bgm = QLineEdit()
                le_bgm.setPlaceholderText("留空则无背景音乐")
                le_bgm.setStyleSheet(
                    "QLineEdit { background: #1e1e1e; border: 1px solid #555; color: #fff; padding: 4px; border-radius: 4px; font-size: 12px;}")
                le_bgm.setText(current_bgm)

                btn_browse = QPushButton("📂")
                btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_browse.setFixedSize(30, 24)
                btn_browse.setStyleSheet(
                    "QPushButton { background: #2e7d32; color: white; border: none; border-radius: 4px; } QPushButton:hover { background: #388e3c; }")
                btn_browse.clicked.connect(lambda checked, row=i, le=le_bgm: self.browse_row_bgm(row, le))

                bgm_layout.addWidget(le_bgm)
                bgm_layout.addWidget(btn_browse)
                self.table.setCellWidget(i, 3, bgm_widget)

    def select_all(self):
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(Qt.CheckState.Checked)

    def unselect_all(self):
        for i in range(self.table.rowCount()):
            state = self.table.item(i, 0).checkState()
            self.table.item(i, 0).setCheckState(
                Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def on_preset_changed(self):
        preset_name = self.combo_sub_preset.currentText()
        self.edit_sub_id.setText(self.presets.get(preset_name, ""))

    def run_batch_export(self):
        # 1. 收集表格中勾选的任务及专属配置 (BGM + 模板)
        tasks = []
        for i in range(self.table.rowCount()):
            chk = self.table.item(i, 0)
            if chk.checkState() == Qt.CheckState.Checked:
                path = chk.data(Qt.ItemDataRole.UserRole)

                # 获取模板路径
                widget_tpl = self.table.cellWidget(i, 2)
                combo = widget_tpl.findChild(QComboBox) if widget_tpl else None
                tpl_path = combo.currentData() if combo else ""

                # 获取 BGM 路径
                widget_bgm = self.table.cellWidget(i, 3)
                le = widget_bgm.findChild(QLineEdit) if widget_bgm else None
                bgm_path = le.text().strip() if le else ""

                tasks.append((path, bgm_path, tpl_path))

        if not tasks:
            QMessageBox.warning(self, "提示", "请至少在左侧列表中勾选一个需要导出的项目！")
            return

        ratio = self.combo_ratio.currentText().split()[0]
        sub_id = self.edit_sub_id.text().strip()

        paths_to_export = []

        # 2. 将修改直接覆盖写入底层项目配置文件 (不经过前台页面加载)
        for p, bgm, tpl in tasks:
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 🌟 核心修复：批量导出前，全自动重定位修复图片路径
                project_dir = os.path.dirname(os.path.abspath(p))
                assets_dir = os.path.join(project_dir, "assets")

                for scene in data.get('scenes', []):
                    if 'images' in scene and isinstance(scene['images'], list):
                        fixed_images = []
                        for img_p in scene['images']:
                            if not img_p:
                                continue
                            if not os.path.exists(img_p):
                                # 如果绝对路径失效，去项目自身的 assets 文件夹里找
                                base_name = os.path.basename(img_p)
                                new_p = os.path.join(assets_dir, base_name)
                                if os.path.exists(new_p):
                                    fixed_images.append(new_p)
                            else:
                                fixed_images.append(img_p)
                        scene['images'] = fixed_images
                # -------------------------------------------------------------

                if 'export_settings' not in data:
                    data['export_settings'] = {}

                data['export_settings']['resolution_mode'] = ratio
                data['export_settings']['subtitle_effect_id'] = sub_id
                data['export_settings']['bgm_path'] = bgm

                # 🌟 核心：保存用户选择的专属模板路径
                data['export_settings']['template_path'] = tpl

                # 将修复后的正确路径和最新参数直接静默写回硬盘
                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                paths_to_export.append(p)
            except Exception as e:
                self.append_log(f"⚠️ 更新参数失败，跳过 {os.path.basename(p)}: {e}")

        # 3. 调用全新的、独立于主窗口的无头后台导出管理器
        from 逻辑.export_manager import BatchExportManager
        if not hasattr(self, 'batch_manager'):
            self.batch_manager = BatchExportManager(self)

        # 🌟 初始化 UI 状态
        self.log_view.clear()
        self.update_progress(0, len(paths_to_export))

        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ 正在后台全速拼接草稿...")
        self.btn_stop.setEnabled(True)  # 激活停止按钮

        # 启动任务
        self.batch_manager.run_batch_export(paths_to_export)