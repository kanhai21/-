import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGroupBox
)
from PyQt6.QtCore import Qt


class ExportOptionsDialog(QDialog):
    def __init__(self, current_settings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出参数设置")
        # 调整窗口大小以容纳新增的提示信息
        self.resize(600, 520)
        self.settings = current_settings if current_settings else {}

        # 标志位：用户点击的是"导出"(True)还是"仅保存"(False)
        self.should_export = False

        # 内置热门花字预设 (名称: effect_id)
        self.preset_effects = {
            "默认 (黑底白字)": "",
            "综艺-黄蓝撞色": "2168393",
            "综艺-清新渐变": "2168394",
            "红色描边-醒目": "2168395",
            "黄色粗体-解说常用": "2168396",
            "蓝色发光-科技感": "2168397",
            "粉色少女-可爱": "2168398"
        }

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # ---------------- 1. 视频画幅 ----------------
        gb_video = QGroupBox("🎬 视频画幅")
        gb_video.setStyleSheet("""
            QGroupBox { border: 1px solid #444; margin-top: 10px; font-weight: bold; color: #4fc3f7; border-radius: 4px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #252526; }
        """)
        v_layout = QVBoxLayout(gb_video)

        h_ratio = QHBoxLayout()
        h_ratio.addWidget(QLabel("比例选择:"))
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItems(
            ["16:9 (横屏 - 1920x1080)", "9:16 (竖屏 - 1080x1920)", "1:1 (方形 - 1080x1080)", "4:3 (老电视)",
             "2.35:1 (宽银幕)"])

        # 恢复上次的选择
        current_ratio = self.settings.get('resolution_mode', '4:3')
        for i in range(self.combo_ratio.count()):
            if current_ratio in self.combo_ratio.itemText(i):
                self.combo_ratio.setCurrentIndex(i)
                break

        self.combo_ratio.setStyleSheet(
            "background: #333; color: white; padding: 6px; border: 1px solid #555; border-radius: 4px;")
        h_ratio.addWidget(self.combo_ratio, 1)
        v_layout.addLayout(h_ratio)
        layout.addWidget(gb_video)

        # ---------------- 2. 音频设置 ----------------
        gb_audio = QGroupBox("🎵 背景音乐 (BGM)")
        gb_audio.setStyleSheet("""
            QGroupBox { border: 1px solid #444; margin-top: 10px; font-weight: bold; color: #81c784; border-radius: 4px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #252526; }
        """)
        a_layout = QVBoxLayout(gb_audio)

        # 提示信息
        lbl_bgm_hint = QLabel("💡 提示：若【文件路径】留空，则自动使用全局设置中的 BGM。")
        lbl_bgm_hint.setStyleSheet("color: #888; font-size: 12px; font-style: italic;")
        a_layout.addWidget(lbl_bgm_hint)

        h_bgm = QHBoxLayout()
        h_bgm.addWidget(QLabel("文件路径:"))
        self.e_bgm = QLineEdit(self.settings.get('bgm_path', ''))
        self.e_bgm.setPlaceholderText("留空 = 使用全局默认BGM")
        self.e_bgm.setStyleSheet(
            "background: #222; color: #ddd; border: 1px solid #555; padding: 6px; border-radius: 4px;")

        btn_clear_bgm = QPushButton("❌")
        btn_clear_bgm.setFixedSize(30, 30)
        btn_clear_bgm.setToolTip("清空 (使用全局设置)")
        btn_clear_bgm.clicked.connect(lambda: self.e_bgm.setText(""))
        btn_clear_bgm.setStyleSheet("background: #444; color: #aaa; border-radius: 4px;")

        btn_bgm = QPushButton("📂")
        btn_bgm.setFixedSize(40, 30)
        btn_bgm.clicked.connect(self.select_bgm)
        btn_bgm.setStyleSheet("background: #444; color: white; border-radius: 4px;")

        h_bgm.addWidget(self.e_bgm)
        h_bgm.addWidget(btn_clear_bgm)
        h_bgm.addWidget(btn_bgm)
        a_layout.addLayout(h_bgm)

        h_vol = QHBoxLayout()
        h_vol.addWidget(QLabel("BGM音量:"))
        self.spin_vol = QDoubleSpinBox()
        self.spin_vol.setRange(0.0, 1.0)
        self.spin_vol.setSingleStep(0.1)
        self.spin_vol.setValue(float(self.settings.get('bgm_volume', 0.2)))
        self.spin_vol.setFixedWidth(100)
        self.spin_vol.setStyleSheet(
            "background: #222; color: white; border: 1px solid #555; border-radius: 4px; padding: 2px;")

        lbl_vol_hint = QLabel("(0.0 ~ 1.0，独立设置时生效)")
        lbl_vol_hint.setStyleSheet("color: #777; font-size: 12px; margin-left: 10px;")

        h_vol.addWidget(self.spin_vol)
        h_vol.addWidget(lbl_vol_hint)
        h_vol.addStretch()
        a_layout.addLayout(h_vol)
        layout.addWidget(gb_audio)

        # ---------------- 3. 字幕样式 ----------------
        gb_sub = QGroupBox("📝 字幕样式")
        gb_sub.setStyleSheet("""
            QGroupBox { border: 1px solid #444; margin-top: 10px; font-weight: bold; color: #ffb74d; border-radius: 4px; } 
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #252526; }
        """)
        s_layout = QVBoxLayout(gb_sub)

        # 提示信息
        lbl_sub_hint = QLabel("💡 提示：若【特效 ID】留空，则自动使用全局设置中的花字样式。")
        lbl_sub_hint.setStyleSheet("color: #888; font-size: 12px; font-style: italic;")
        s_layout.addWidget(lbl_sub_hint)

        h_preset = QHBoxLayout()
        h_preset.addWidget(QLabel("热门预设:"))
        self.combo_effect = QComboBox()
        self.combo_effect.addItems(list(self.preset_effects.keys()))
        self.combo_effect.currentIndexChanged.connect(self.on_preset_changed)
        self.combo_effect.setStyleSheet(
            "background: #333; color: white; padding: 6px; border: 1px solid #555; border-radius: 4px;")
        h_preset.addWidget(self.combo_effect, 1)
        s_layout.addLayout(h_preset)

        h_effect_id = QHBoxLayout()
        h_effect_id.addWidget(QLabel("特效 ID:"))
        self.e_effect_id = QLineEdit(self.settings.get('subtitle_effect_id', ''))
        self.e_effect_id.setPlaceholderText("留空 = 使用全局默认样式")
        self.e_effect_id.setStyleSheet(
            "background: #222; color: #ddd; border: 1px solid #555; padding: 6px; border-radius: 4px;")

        btn_clear_effect = QPushButton("❌")
        btn_clear_effect.setFixedSize(30, 30)
        btn_clear_effect.setToolTip("清空 (使用全局设置)")
        btn_clear_effect.clicked.connect(lambda: self.e_effect_id.setText(""))
        btn_clear_effect.setStyleSheet("background: #444; color: #aaa; border-radius: 4px;")

        h_effect_id.addWidget(self.e_effect_id)
        h_effect_id.addWidget(btn_clear_effect)
        s_layout.addLayout(h_effect_id)

        # 尝试匹配当前ID到预设
        current_id = self.settings.get('subtitle_effect_id', '')
        for i, (name, eid) in enumerate(self.preset_effects.items()):
            if eid == current_id:
                self.combo_effect.setCurrentIndex(i)
                break

        layout.addWidget(gb_sub)

        layout.addStretch()

        # ---------------- 底部按钮 ----------------
        btn_box = QHBoxLayout()
        btn_box.setSpacing(15)

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_cancel.setStyleSheet("background: #444; color: white; padding: 10px; border: none; border-radius: 4px;")

        btn_save = QPushButton("💾 仅保存参数")
        btn_save.clicked.connect(self.on_click_save)
        btn_save.setStyleSheet("""
            QPushButton { background: #00796b; color: white; font-weight: bold; padding: 10px 20px; border: none; border-radius: 4px; }
            QPushButton:hover { background: #00897b; }
        """)

        btn_export = QPushButton("🚀 立即导出")
        btn_export.clicked.connect(self.on_click_export)
        btn_export.setStyleSheet("""
            QPushButton { background: #1a73e8; color: white; font-weight: bold; padding: 10px 20px; border: none; border-radius: 4px; }
            QPushButton:hover { background: #1565c0; }
        """)

        btn_box.addWidget(btn_cancel)
        btn_box.addStretch()
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_export)
        layout.addLayout(btn_box)

        # 设置整体样式
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; color: #eee; font-size: 14px; } QLabel { color: #ccc; font-weight: bold; }")

    def select_bgm(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择背景音乐", "", "Audio (*.mp3 *.wav *.m4a *.flac)")
        if f:
            self.e_bgm.setText(f)

    def on_preset_changed(self):
        name = self.combo_effect.currentText()
        eid = self.preset_effects.get(name, "")
        self.e_effect_id.setText(eid)

    def on_click_save(self):
        """点击仅保存"""
        self.should_export = False
        self.accept()

    def on_click_export(self):
        """点击立即导出"""
        self.should_export = True
        self.accept()

    def get_settings(self):
        # 提取画幅字符串中的比例部分 (例如 "16:9 (横屏...)" -> "16:9")
        raw_ratio = self.combo_ratio.currentText().split(' ')[0]

        return {
            "resolution_mode": raw_ratio,
            "bgm_path": self.e_bgm.text().strip(),
            "bgm_volume": self.spin_vol.value(),
            "subtitle_effect_id": self.e_effect_id.text().strip()
        }