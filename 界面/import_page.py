import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QGroupBox, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt


class ImportPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        # 这里的 main_window 实际上是 ProjectEditor 实例
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(20)

        # 1. 语音音频导入
        g_aud = QGroupBox("1. 语音音频导入 (支持批量)")
        g_aud.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 15px; }")
        al = QHBoxLayout(g_aud)
        self.e_aud = QLineEdit()
        self.e_aud.setPlaceholderText("选择单个音频，或按住Ctrl选择多个音频以批量创建项目")
        b_aud = QPushButton("选择音频")
        b_aud.clicked.connect(self.select_audio)
        b_aud.setStyleSheet("background-color: #1a73e8; color: white; font-weight: bold;")
        al.addWidget(self.e_aud)
        al.addWidget(b_aud)
        left_layout.addWidget(g_aud)

        # 2. 背景音乐导入
        g_bgm = QGroupBox("2. 背景音乐导入 (可选)")
        g_bgm.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 15px; }")
        bgm_layout = QHBoxLayout(g_bgm)
        self.e_bgm = QLineEdit()
        self.e_bgm.setPlaceholderText("请选择背景音乐文件 (.mp3/ .wav)")
        b_bgm = QPushButton("选择BGM")
        b_bgm.clicked.connect(self.select_bgm)
        bgm_layout.addWidget(self.e_bgm)
        bgm_layout.addWidget(b_bgm)
        left_layout.addWidget(g_bgm)

        # 3. 字幕文件导入
        g_srt = QGroupBox("3. 字幕文件导入 (自动匹配)")
        g_srt.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #64b5f6; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 15px; }")
        sl = QHBoxLayout(g_srt)
        self.e_srt = QLineEdit()
        self.e_srt.setPlaceholderText("单文件模式手动选择，批量模式下会自动识别同名字幕")
        b_srt = QPushButton("选择字幕")
        b_srt.clicked.connect(self.select_srt)
        sl.addWidget(self.e_srt)
        sl.addWidget(b_srt)
        left_layout.addWidget(g_srt)

        left_layout.addStretch()

        # 下一步按钮
        self.btn_next = QPushButton("🚀 导入完成，去分镜规划")
        self.btn_next.setMinimumHeight(60)
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #388e3c; }
        """)
        self.btn_next.clicked.connect(self.main_window.go_sb)
        left_layout.addWidget(self.btn_next)

        # 右侧说明
        right_panel = QWidget()
        right_panel.setFixedWidth(350)
        right_layout = QVBoxLayout(right_panel)

        lbl_info = QLabel("📝 批量操作说明")
        lbl_info.setStyleSheet("font-size: 16px; font-weight: bold; color: #4fc3f7; margin-bottom: 10px;")
        right_layout.addWidget(lbl_info)

        info_text = QLabel(
            "1. **批量创建**：在“选择音频”时，按住 Ctrl 或 Shift 选择多个文件。\n\n"
            "2. **字幕匹配**：批量模式下，系统会自动查找音频同级目录下的同名 SRT/LRC 字幕文件。\n"
            "   例如：\n"
            "   - audio1.mp3\n"
            "   - audio1.srt (自动加载)\n\n"
            "3. **极速模式**：若选择文件超过 5 个，将只在后台创建项目，不自动打开所有窗口，防止软件卡死。"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #ccc; font-size: 14px; line-height: 1.5;")
        info_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(info_text)
        right_layout.addStretch()

        main_layout.addWidget(left_panel, stretch=1)
        main_layout.addWidget(right_panel)

    def select_audio(self):
        # 使用 getOpenFileNames 支持多选
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频 (支持多选批量创建)", "", "Audio (*.mp3 *.wav *.m4a)")

        if not files:
            return

        # === 单文件模式 ===
        if len(files) == 1:
            f = files[0]
            self.e_aud.setText(f)
            self.main_window.data['audio_path'] = f
            # 自动找字幕
            base = os.path.splitext(f)[0]
            self._try_find_subtitle(base, set_ui=True)
            self.main_window.save_proj(silent=True)

        # === 批量模式 ===
        else:
            self.handle_batch_import(files)

    def handle_batch_import(self, files):
        count = 0
        total = len(files)

        # 性能策略：超过5个不全部打开
        open_strategy = True
        if total > 5:
            reply = QMessageBox.question(self, "批量操作确认",
                                         f"您选择了 {total} 个文件。\n全部打开可能会导致软件卡顿。\n\n是否开启【后台极速模式】？\n(即：只创建项目文件，不打开所有标签页)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                open_strategy = False

        # 获取主程序引用 (ProjectEditor -> NovelTweetApp)
        main_app = getattr(self.main_window, 'main_app', None)
        if not main_app:
            QMessageBox.critical(self, "错误", "无法获取主程序实例，请重启软件重试。")
            return

        for i, f in enumerate(files):
            base_name = os.path.splitext(os.path.basename(f))[0]
            dir_path = os.path.dirname(f)

            # 自动查找同名字幕
            srt_path = ""
            potential_srt = os.path.join(dir_path, base_name + ".srt")
            potential_lrc = os.path.join(dir_path, base_name + ".lrc")

            if os.path.exists(potential_srt):
                srt_path = potential_srt
            elif os.path.exists(potential_lrc):
                srt_path = potential_lrc

            # 决定是否打开
            # 最后一个项目总是打开，方便用户查看
            should_open = open_strategy or (i == total - 1)

            try:
                # 调用主程序的 create_project_auto
                main_app.create_project_auto(base_name, f, srt_path, open_now=should_open)
                count += 1
                QApplication.processEvents()  # 防止界面冻结
            except Exception as e:
                print(f"创建项目 {base_name} 失败: {e}")

        if count > 0:
            msg = f"已批量处理 {count} 个项目！\n(字幕已自动匹配)"
            if not open_strategy:
                msg += "\n\n(已启用极速模式，项目已生成，仅打开了最后一个)"
            QMessageBox.information(self, "批量导入完成", msg)

    def _try_find_subtitle(self, base_path_no_ext, set_ui=False):
        """辅助函数：查找字幕"""
        found_path = ""
        if os.path.exists(base_path_no_ext + ".srt"):
            found_path = base_path_no_ext + ".srt"
        elif os.path.exists(base_path_no_ext + ".lrc"):
            found_path = base_path_no_ext + ".lrc"

        if found_path:
            self.main_window.data['srt_path'] = found_path
            if set_ui:
                self.e_srt.setText(found_path)
        return found_path

    def select_bgm(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择背景音乐", "", "Audio (*.mp3 *.wav *.m4a *.flac)")
        if f:
            self.e_bgm.setText(f)
            if 'export_settings' not in self.main_window.data:
                self.main_window.data['export_settings'] = {}
            self.main_window.data['export_settings']['bgm_path'] = f
            self.main_window.save_proj(silent=True)

    def select_srt(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择字幕", "", "Subtitle (*.srt *.lrc)")
        if f:
            self.e_srt.setText(f)
            self.main_window.data['srt_path'] = f
            self.main_window.save_proj(silent=True)