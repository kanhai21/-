import os
if os.name == 'nt':
    import winsound
import json
import shutil
import configparser
import sys
import subprocess
import glob
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QStackedWidget, QFrame, QInputDialog, QTabWidget,
    QTabBar, QMenu, QToolButton, QComboBox, QDialog, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox, QGroupBox, QLineEdit, QApplication,
    QTextEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon
from 配置.app_config import APP_VERSION
from 配置 import config
from 配置.app_config import CONFIG_FILE, DEFAULT_RESOLUTION_MODE, get_global_style_settings
from 逻辑.srt_util import LocalSRTParser
# 🌟 修复 Bug 2: 引入防撞锁
from 逻辑.app_workers import TranslationThread, SmartSplitThread
from 逻辑.project_manager import ProjectManager
from 逻辑.role_manager import RoleManager
from 逻辑.inference_manager import InferenceManager
from 逻辑.image_gen_manager import ImageGenManager
from 逻辑.export_manager import ExportManager
from 配置.app_config import PROJECT_FILE_LOCK

from 界面.dialogs import SettingsDialog, KeyframeDialog, PromptTemplateDialog
from 界面.role_lib_ui import RoleLibraryDialog
from 界面.workspace import StudioPage
from 界面.home_page import HomePage
from 界面.import_page import ImportPage
from 界面.split_page import SplitPage
from 工具.audio_merger_module import AudioMergerWidget
from 工具.subtitle_merger_module import SubtitleMergerWidget

PROJECTS_ROOT_DIR = os.path.join(os.getcwd(), "资源", "saved_projects")
os.makedirs(PROJECTS_ROOT_DIR, exist_ok=True)
AUTO_SAVE_INTERVAL = 60000


# ================= 全局任务追踪器 =================
class GlobalTaskManager(QObject):
    all_finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_tasks = 0
        self.task_type = ""

    def start_batch(self, task_type):
        self.task_type = task_type
        self.active_tasks = 0

    def add_task(self):
        self.active_tasks += 1

    def on_task_finished(self):
        self.active_tasks -= 1
        if self.active_tasks <= 0:
            self.active_tasks = 0
            if self.task_type != "批量全局生图":
                self.all_finished.emit(self.task_type)


# ================= 全局画风与提示词设置弹窗 =================
class GlobalStyleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎭 全局画风与提示词设置")
        self.resize(700, 550)
        self.presets = {
            "不使用预设 (保持留白)": {"pos": "", "neg": ""},
            "日系动漫 (Anime)": {
                "pos": "(masterpiece, best quality, ultra-detailed), 2D illustration, anime style, colorful, cel shading",
                "neg": "(photorealistic:1.4), (realistic:1.4), 3D, CG, photo, real human, ugly, bad anatomy, bad hands, missing fingers"
            },
            "唯美古风 (Ancient Chinese)": {
                "pos": "(masterpiece, best quality), chinese ancient style, beautiful ink painting, elegant, floating clothes, soft lighting",
                "neg": "(photorealistic:1.4), modern, text, watermark, bad anatomy, mutated, extra limbs"
            },
            "写实摄影 (Realistic)": {
                "pos": "(masterpiece, best quality, ultra-detailed), photorealistic, 8k uhd, dslr, soft lighting, high quality photography, cinematic lighting",
                "neg": "(anime:1.3), 2d, illustration, painting, cartoon, sketch, ugly, deformed, text, watermark"
            },
            "3D/CG渲染 (3D Render)": {
                "pos": "(masterpiece, best quality), 3d render, octane render, unreal engine 5, highly detailed, dramatic lighting",
                "neg": "2d, flat, anime, sketch, drawing, painting, ugly, missing fingers, deformed body"
            }
        }
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #e0e0e0; font-size: 15px; font-weight: bold; }
            QComboBox { background-color: #252526; color: #fff; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 14px; }
            QComboBox:hover { border: 1px solid #1a73e8; }
            QComboBox::drop-down { border-left: 1px solid #555; }
            QTextEdit { background-color: #252526; color: #fff; border: 1px solid #555; padding: 8px; border-radius: 6px; font-size: 14px; }
            QTextEdit:focus { border: 1px solid #4fc3f7; }
            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; }
            QPushButton:hover { background-color: #1557b0; }
        """)
        layout = QVBoxLayout(self)

        lbl_desc = QLabel("💡 这里的提示词将在生图时，自动追加到每一个分镜的末尾。")
        lbl_desc.setStyleSheet("color: #4fc3f7; margin-bottom: 10px;")
        layout.addWidget(lbl_desc)

        layout.addWidget(QLabel("快捷画风预设选择："))
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(self.presets.keys())
        self.combo_preset.currentIndexChanged.connect(self.on_preset_changed)
        layout.addWidget(self.combo_preset)
        layout.addSpacing(10)

        layout.addWidget(QLabel("✅ 全局正向提示词 (Global Positive Prompt):"))
        self.txt_pos = QTextEdit()
        self.txt_pos.setPlaceholderText("例如: masterpiece, best quality, anime style...")
        layout.addWidget(self.txt_pos)

        layout.addWidget(QLabel("❌ 全局负面提示词 (Global Negative Prompt):"))
        self.txt_neg = QTextEdit()
        self.txt_neg.setPlaceholderText("例如: realistic, 3D, ugly, bad anatomy...")
        layout.addWidget(self.txt_neg)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: #555; border: none;")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 保存配置")
        btn_save.clicked.connect(self.save_settings)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def on_preset_changed(self):
        preset_name = self.combo_preset.currentText()
        if preset_name in self.presets and preset_name != "不使用预设 (保持留白)":
            self.txt_pos.setPlainText(self.presets[preset_name]["pos"])
            self.txt_neg.setPlainText(self.presets[preset_name]["neg"])

    def load_settings(self):
        settings = get_global_style_settings()
        self.txt_pos.setPlainText(settings.get("pos_prompt", ""))
        self.txt_neg.setPlainText(settings.get("neg_prompt", ""))

    def save_settings(self):
        try:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')

            if 'GlobalStyle' not in cfg:
                cfg['GlobalStyle'] = {}

            cfg['GlobalStyle']['pos_prompt'] = self.txt_pos.toPlainText().replace("\n", " ").strip()
            cfg['GlobalStyle']['neg_prompt'] = self.txt_neg.toPlainText().replace("\n", " ").strip()

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")


# ================= 注销授权专用防丢保护弹窗 =================
class UnbindDialog(QDialog):
    def __init__(self, parent=None, card_key=""):
        super().__init__(parent)
        self.setWindowTitle("🔓 注销本机授权")
        self.setFixedSize(550, 300)
        self.card_key = card_key
        self.is_old_version = ("旧版本" in card_key or not card_key)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #e0e0e0; font-size: 15px; }
            QLineEdit { background-color: #252526; color: #ffaa00; border: 1px solid #555; border-radius: 6px; padding: 10px; font-size: 14px; font-weight: bold; }
            QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 8px 15px; border-radius: 6px; font-weight: bold; font-size: 14px; }
            QPushButton:hover { background-color: #444; border-color: #1a73e8; }
            #btn_confirm { background-color: #c62828; border: none; }
            #btn_confirm:hover { background-color: #d32f2f; }
            #btn_copy { background-color: #2e7d32; border: none; }
            #btn_copy:hover { background-color: #388e3c; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        if self.is_old_version:
            lbl_warning = QLabel(
                "⚠️ 警告：注销后本机将立刻失去授权！\n\n由于您当前使用的是【旧版授权方式】，系统未能在本地找到备份的卡密。\n注销后若要再次使用，您必须联系管理员获取【新卡密】！")
            lbl_warning.setStyleSheet("color: #ff5252; font-weight: bold;")
            layout.addWidget(lbl_warning)

            layout.addSpacing(10)
            layout.addWidget(QLabel("🔑 卡密状态："))

            self.edit_key = QLineEdit("未找到备份的卡密 (旧版授权)")
            self.edit_key.setReadOnly(True)
            self.edit_key.setStyleSheet("color: #888; background-color: #252526;")
            layout.addWidget(self.edit_key)
        else:
            lbl_warning = QLabel(
                "⚠️ 警告：注销后本机将立刻失去授权！\n\n为防止您更换电脑后无法重新激活，请务必提前【复制并保存】\n下方的原始激活卡密：")
            lbl_warning.setStyleSheet("color: #ff5252; font-weight: bold;")
            layout.addWidget(lbl_warning)

            layout.addSpacing(10)
            layout.addWidget(QLabel("🔑 您的原始激活卡密："))

            row = QHBoxLayout()
            self.edit_key = QLineEdit(self.card_key)
            self.edit_key.setReadOnly(True)
            row.addWidget(self.edit_key)

            btn_copy = QPushButton("📋 一键复制")
            btn_copy.setObjectName("btn_copy")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.clicked.connect(self.copy_key)
            row.addWidget(btn_copy)
            layout.addLayout(row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        confirm_text = "✅ 我已知晓，强行注销" if self.is_old_version else "✅ 我已保存卡密，确认注销"
        self.btn_confirm = QPushButton(confirm_text)
        self.btn_confirm.setObjectName("btn_confirm")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.clicked.connect(self.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_confirm)

        layout.addLayout(btn_row)

    def copy_key(self):
        if not self.is_old_version:
            QApplication.clipboard().setText(self.card_key)
            QMessageBox.information(self, "复制成功",
                                    "卡密已成功复制到剪贴板！\n请务必将其粘贴保存在安全的地方（如微信/备忘录中）。")


# ================= 批量选择项目对话框 =================
class ProjectSelectionDialog(QDialog):
    def __init__(self, parent=None, title="选择批量处理的项目"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(550, 650)
        self.selected_paths = []
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #4fc3f7; font-size: 16px; font-weight: bold; margin-bottom: 10px; }
            QListWidget { background-color: #252526; color: #ffffff; border: 1px solid #444; border-radius: 8px; padding: 8px; font-size: 15px; outline: none;}
            QListWidget::item { padding: 12px 8px; border-bottom: 1px solid #333; border-radius: 4px; }
            QListWidget::item:hover { background-color: #2d2d2d; }
            QListWidget::item:selected { background-color: transparent; color: white; }
            QListWidget::indicator { width: 24px; height: 24px; border: 2px solid #666; border-radius: 4px; background-color: #121212; margin-right: 10px;}
            QListWidget::indicator:hover { border: 2px solid #ff5252; }
            QListWidget::indicator:checked { border: 2px solid #ff5252; background-color: #2a1111; image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><path fill='none' stroke='%23ff5252' stroke-width='4' stroke-linecap='round' stroke-linejoin='round' d='M4 12l5 5L20 6'/></svg>");}
            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; }
            QPushButton:hover { background-color: #1557b0; }
        """)
        layout = QVBoxLayout(self)

        lbl = QLabel("✅ 请在下方勾选需要处理的项目：")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        if os.path.exists(PROJECTS_ROOT_DIR):
            ntp_files = glob.glob(os.path.join(PROJECTS_ROOT_DIR, "*", "*.ntp"))
            ntp_files.sort(key=os.path.getmtime, reverse=True)
            for p in ntp_files:
                name = os.path.basename(p).replace(".ntp", "")
                item = QListWidgetItem(f"📄 项目：{name}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("☑️ 全选")
        btn_select_all.clicked.connect(self.select_all)
        btn_select_all.setStyleSheet("background-color: #2e7d32; border: 1px solid #4caf50;")

        btn_unselect = QPushButton("🔲 反选")
        btn_unselect.clicked.connect(self.unselect_all)
        btn_unselect.setStyleSheet("background-color: #e65100; border: 1px solid #ff9800;")

        btn_ok = QPushButton("🚀 开始批量处理")
        btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_unselect)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def select_all(self):
        for i in range(self.list_widget.count()): self.list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def unselect_all(self):
        for i in range(self.list_widget.count()):
            state = self.list_widget.item(i).checkState()
            new_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            self.list_widget.item(i).setCheckState(new_state)

    def accept_selection(self):
        self.selected_paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_paths.append(item.data(Qt.ItemDataRole.UserRole))
        if not self.selected_paths:
            QMessageBox.warning(self, "提示", "请至少勾选一个项目！")
            return
        self.accept()


# ================= 批量推理专属仪表盘配置面板 =================
class BatchInferenceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎬 批量分镜推理任务配置 (流水线中控台)")
        self.resize(800, 750)
        self.selected_paths = []
        self.init_ui()
        self.load_config()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #e0e0e0; font-size: 14px; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 15px; padding-top: 20px; font-weight: bold; color: #64b5f6; font-size: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }
            QSpinBox { background-color: #333; color: white; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 15px; min-width: 60px; }
            QSpinBox:focus { border: 1px solid #1a73e8; }
            QListWidget { background-color: #252526; color: #ffffff; border: 1px solid #444; border-radius: 8px; padding: 8px; font-size: 15px; outline: none; margin-top: 10px;}
            QListWidget::item { padding: 12px 8px; border-bottom: 1px solid #333; border-radius: 4px; }
            QListWidget::item:hover { background-color: #2d2d2d; }
            QListWidget::item:selected { background-color: transparent; color: white; }
            QListWidget::indicator { width: 24px; height: 24px; border: 2px solid #666; border-radius: 4px; background-color: #121212; margin-right: 10px;}
            QListWidget::indicator:hover { border: 2px solid #ff5252; }
            QListWidget::indicator:checked { border: 2px solid #ff5252; background-color: #2a1111; image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><path fill='none' stroke='%23ff5252' stroke-width='4' stroke-linecap='round' stroke-linejoin='round' d='M4 12l5 5L20 6'/></svg>");}
            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 15px; }
            QPushButton:hover { background-color: #1557b0; }
        """)
        layout = QVBoxLayout(self)

        # --- 高级并发配置区 ---
        grp_config = QGroupBox("🚀 全局推理并发引擎策略 (将实时保存并生效)")
        lyt_config = QHBoxLayout(grp_config)
        lyt_config.setSpacing(10)

        lyt_config.addWidget(QLabel("宏观排队并发 (项目数):"))
        self.spin_proj_cnt = QSpinBox()
        self.spin_proj_cnt.setRange(1, 20)
        self.spin_proj_cnt.setToolTip("同时并排处理多少个【不同】的项目。\n建议设为 1，确保排队稳定性，绝不拥堵。")
        lyt_config.addWidget(self.spin_proj_cnt)

        lyt_config.addSpacing(15)

        lyt_config.addWidget(QLabel("单项目微观并发 (线程数):"))
        self.spin_thread_cnt = QSpinBox()
        self.spin_thread_cnt.setRange(1, 50)
        self.spin_thread_cnt.setToolTip(
            "一个项目内，火力全开同时向 API 发送多少个批次。\n免费 API 建议 3，付费无限制可拉满。")
        lyt_config.addWidget(self.spin_thread_cnt)

        lyt_config.addSpacing(15)

        lyt_config.addWidget(QLabel("单次批次容量 (分镜数):"))
        self.spin_batch_size = QSpinBox()
        self.spin_batch_size.setRange(1, 50)
        self.spin_batch_size.setToolTip("每个请求包打包包含多少个分镜送给 AI。\n默认 5。数字太大易导致 AI 遗漏！")
        lyt_config.addWidget(self.spin_batch_size)

        lyt_config.addStretch()
        layout.addWidget(grp_config)

        # --- 项目列表区 ---
        lbl_proj = QLabel("✅ 请在下方勾选需要进入后台推理队列的项目：")
        lbl_proj.setStyleSheet("color: #4fc3f7; font-weight: bold; margin-top: 15px;")
        layout.addWidget(lbl_proj)

        self.list_widget = QListWidget()
        if os.path.exists(PROJECTS_ROOT_DIR):
            ntp_files = glob.glob(os.path.join(PROJECTS_ROOT_DIR, "*", "*.ntp"))
            ntp_files.sort(key=os.path.getmtime, reverse=True)
            for p in ntp_files:
                name = os.path.basename(p).replace(".ntp", "")
                item = QListWidgetItem(f"📄 项目：{name}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        # --- 按钮区 ---
        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("☑️ 全选")
        btn_select_all.clicked.connect(self.select_all)
        btn_select_all.setStyleSheet("background-color: #2e7d32; border: 1px solid #4caf50;")

        btn_unselect = QPushButton("🔲 反选")
        btn_unselect.clicked.connect(self.unselect_all)
        btn_unselect.setStyleSheet("background-color: #e65100; border: 1px solid #ff9800;")

        btn_ok = QPushButton("🚀 保存配置并启动排队")
        btn_ok.setMinimumWidth(200)
        btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_unselect)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def load_config(self):
        try:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')

            p_cnt = int(cfg['DEFAULT'].get('project_concurrent_count', 1))
            t_cnt = int(cfg['DEFAULT'].get('infer_thread_count', 3))
            b_size = int(cfg['DEFAULT'].get('infer_batch_size', 5))

            self.spin_proj_cnt.setValue(p_cnt)
            self.spin_thread_cnt.setValue(t_cnt)
            self.spin_batch_size.setValue(b_size)
        except Exception:
            pass

    def save_config(self):
        try:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')

            if 'DEFAULT' not in cfg:
                cfg['DEFAULT'] = {}

            cfg['DEFAULT']['project_concurrent_count'] = str(self.spin_proj_cnt.value())
            cfg['DEFAULT']['infer_thread_count'] = str(self.spin_thread_cnt.value())
            cfg['DEFAULT']['infer_batch_size'] = str(self.spin_batch_size.value())

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def select_all(self):
        for i in range(self.list_widget.count()): self.list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def unselect_all(self):
        for i in range(self.list_widget.count()):
            state = self.list_widget.item(i).checkState()
            new_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            self.list_widget.item(i).setCheckState(new_state)

    def accept_selection(self):
        self.selected_paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_paths.append(item.data(Qt.ItemDataRole.UserRole))
        if not self.selected_paths:
            QMessageBox.warning(self, "提示", "请至少勾选一个项目！")
            return

        self.save_config()
        self.accept()


# ================= 批量分镜配置面板 =================
class BatchSplitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✂️ 批量阶梯式分镜任务配置")
        self.resize(950, 650)
        self.selected_tasks = []
        self.selected_mode = 'fixed'
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei"; }
            QLabel { color: #4fc3f7; font-size: 14px; font-weight: bold; margin-bottom: 5px; }
            QTableWidget { background-color: #252526; color: white; border: 1px solid #444; border-radius: 6px; font-size: 15px;}
            QTableWidget::item { padding: 8px; border-bottom: 1px solid #333; }
            QHeaderView::section { background-color: #333; color: #fff; font-weight: bold; padding: 10px; border: none; font-size: 14px;}

            QComboBox { background-color: #333; color: white; border: 1px solid #555; padding: 6px 12px; border-radius: 4px; font-size: 14px; min-height: 25px;}
            QComboBox:hover { border: 1px solid #1a73e8; }
            QComboBox::drop-down { width: 32px; border-left: 1px solid #555; background: #2b2b2b; border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
            QComboBox::drop-down:hover { background: #444; }
            QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #ccc; margin-top: 2px;}
            QComboBox QAbstractItemView { background-color: #2b2b2b; color: #ffffff; outline: none; border: 1px solid #555; selection-background-color: #1a73e8; selection-color: #ffffff; }

            QSpinBox { background-color: #333; color: white; border: 1px solid #555; padding: 4px; border-radius: 4px; font-size: 14px;}
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; padding-top: 20px; font-weight: bold; color: #64b5f6; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #252526; }
            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px;}
            QPushButton:hover { background-color: #1557b0; }
        """)
        layout = QVBoxLayout(self)

        grp_settings = QGroupBox("统一阶梯式随机分镜参数设置")
        sl = QHBoxLayout(grp_settings)
        sl.setSpacing(8)

        sl.addWidget(QLabel("模式:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("按字幕条数 (固定)", "fixed")
        self.combo_mode.addItem("AI 语义分镜", "ai")
        sl.addWidget(self.combo_mode)

        sl.addSpacing(15)
        sl.addWidget(QLabel("前"))
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(1, 1000)
        self.spin_threshold.setValue(30)
        self.spin_threshold.setMinimumWidth(60)
        sl.addWidget(self.spin_threshold)

        sl.addWidget(QLabel("镜合并:"))
        self.spin_early_min = QSpinBox()
        self.spin_early_min.setRange(1, 50)
        self.spin_early_min.setValue(2)
        self.spin_early_min.setMinimumWidth(50)
        sl.addWidget(self.spin_early_min)

        sl.addWidget(QLabel("-"))
        self.spin_early_max = QSpinBox()
        self.spin_early_max.setRange(1, 50)
        self.spin_early_max.setValue(3)
        self.spin_early_max.setMinimumWidth(50)
        sl.addWidget(self.spin_early_max)

        sl.addSpacing(10)
        sl.addWidget(QLabel("条, 之后:"))
        self.spin_late_min = QSpinBox()
        self.spin_late_min.setRange(1, 50)
        self.spin_late_min.setValue(5)
        self.spin_late_min.setMinimumWidth(50)
        sl.addWidget(self.spin_late_min)

        sl.addWidget(QLabel("-"))
        self.spin_late_max = QSpinBox()
        self.spin_late_max.setRange(1, 50)
        self.spin_late_max.setValue(8)
        self.spin_late_max.setMinimumWidth(50)
        sl.addWidget(self.spin_late_max)

        sl.addStretch()
        layout.addWidget(grp_settings)
        layout.addSpacing(10)

        layout.addWidget(QLabel("请勾选需要处理的项目："))
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["选择", "项目名称"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(45)
        layout.addWidget(self.table)

        if os.path.exists(PROJECTS_ROOT_DIR):
            ntp_files = glob.glob(os.path.join(PROJECTS_ROOT_DIR, "*", "*.ntp"))
            ntp_files.sort(key=os.path.getmtime, reverse=True)
            self.table.setRowCount(len(ntp_files))

            for i, p in enumerate(ntp_files):
                name = os.path.basename(p).replace(".ntp", "")

                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk_item.setCheckState(Qt.CheckState.Unchecked)
                chk_item.setData(Qt.ItemDataRole.UserRole, p)
                self.table.setItem(i, 0, chk_item)

                name_item = QTableWidgetItem(f"📄 {name}")
                name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 1, name_item)

        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("☑️ 全选")
        btn_select_all.clicked.connect(self.select_all)
        btn_select_all.setStyleSheet("background-color: #2e7d32;")

        btn_unselect = QPushButton("🔲 反选")
        btn_unselect.clicked.connect(self.unselect_all)
        btn_unselect.setStyleSheet("background-color: #e65100;")

        btn_ok = QPushButton("🚀 启动全局分镜任务")
        btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_unselect)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def select_all(self):
        for i in range(self.table.rowCount()): self.table.item(i, 0).setCheckState(Qt.CheckState.Checked)

    def unselect_all(self):
        for i in range(self.table.rowCount()):
            state = self.table.item(i, 0).checkState()
            new_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            self.table.item(i, 0).setCheckState(new_state)

    def accept_selection(self):
        self.selected_tasks = []
        for i in range(self.table.rowCount()):
            chk_item = self.table.item(i, 0)
            if chk_item.checkState() == Qt.CheckState.Checked:
                self.selected_tasks.append({"path": chk_item.data(Qt.ItemDataRole.UserRole)})

        if not self.selected_tasks:
            QMessageBox.warning(self, "提示", "请至少勾选一个项目！")
            return

        self.selected_mode = self.combo_mode.currentData()
        self.selected_threshold = self.spin_threshold.value()
        self.selected_early_min = self.spin_early_min.value()
        self.selected_early_max = self.spin_early_max.value()
        self.selected_late_min = self.spin_late_min.value()
        self.selected_late_max = self.spin_late_max.value()

        if self.selected_early_min > self.selected_early_max:
            self.selected_early_min, self.selected_early_max = self.selected_early_max, self.selected_early_min
        if self.selected_late_min > self.selected_late_max:
            self.selected_late_min, self.selected_late_max = self.selected_late_max, self.selected_late_min

        self.accept()


# ================= 批量生图专属配置面板 =================
class BatchImageGenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 批量生图任务配置")
        self.resize(1000, 700)
        self.selected_tasks = []
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: white; font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
            QLabel { color: #4fc3f7; font-size: 16px; font-weight: bold; margin-bottom: 8px; }
            QTableWidget { background-color: #252526; color: white; border: 1px solid #444; border-radius: 6px; font-size: 15px;}
            QTableWidget::item { padding: 8px; border-bottom: 1px solid #333; }
            QHeaderView::section { background-color: #333; color: #fff; font-weight: bold; padding: 10px; border: none; font-size: 14px;}

            QComboBox { 
                background-color: #333; color: white; border: 1px solid #555; 
                padding: 6px 12px; border-radius: 4px; font-size: 14px; min-height: 25px;
            }
            QComboBox:hover { border: 1px solid #1a73e8; }
            QComboBox::drop-down { 
                width: 32px; border-left: 1px solid #555; background: #2b2b2b; 
                border-top-right-radius: 4px; border-bottom-right-radius: 4px; 
            }
            QComboBox::drop-down:hover { background: #444; }
            QComboBox::down-arrow { 
                image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; 
                border-top: 6px solid #ccc; margin-top: 2px;
            }
            QComboBox QAbstractItemView { 
                background-color: #2b2b2b; color: #ffffff; outline: none; border: 1px solid #555;
                selection-background-color: #1a73e8; selection-color: #ffffff; 
            }
            QComboBox QAbstractItemView::item { min-height: 35px; padding-left: 8px;}

            QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px;}
            QPushButton:hover { background-color: #1557b0; }
        """)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选需要生图的项目，并为它们选择对应的工作流："))

        cfg = configparser.ConfigParser()
        try:
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')
            raw_json = cfg['DEFAULT'].get('node_map_json', '[]')
        except Exception:
            raw_json = '[]'

        try:
            self.node_list = json.loads(raw_json)
        except:
            self.node_list = []

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["选择", "项目名称", "专属工作流配置"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(50)
        layout.addWidget(self.table)

        if os.path.exists(PROJECTS_ROOT_DIR):
            ntp_files = glob.glob(os.path.join(PROJECTS_ROOT_DIR, "*", "*.ntp"))
            ntp_files.sort(key=os.path.getmtime, reverse=True)
            self.table.setRowCount(len(ntp_files))

            for i, p in enumerate(ntp_files):
                name = os.path.basename(p).replace(".ntp", "")

                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk_item.setCheckState(Qt.CheckState.Unchecked)
                chk_item.setData(Qt.ItemDataRole.UserRole, p)
                self.table.setItem(i, 0, chk_item)

                name_item = QTableWidgetItem(f"📄 {name}")
                name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 1, name_item)

                combo = QComboBox()
                combo.addItem("🌐 自动负载均衡 (全局默认)", "default")
                for node in self.node_list:
                    combo.addItem(f"🔌 {node.get('name')}", node)

                widget_container = QWidget()
                w_layout = QHBoxLayout(widget_container)
                w_layout.setContentsMargins(8, 4, 8, 4)
                w_layout.addWidget(combo)
                self.table.setCellWidget(i, 2, widget_container)
                combo.setProperty("row_index", i)

        btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("☑️ 全选")
        btn_select_all.clicked.connect(self.select_all)
        btn_select_all.setStyleSheet("background-color: #2e7d32;")

        btn_unselect = QPushButton("🔲 反选")
        btn_unselect.clicked.connect(self.unselect_all)
        btn_unselect.setStyleSheet("background-color: #e65100;")

        btn_ok = QPushButton("🚀 启动全局生图任务")
        btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_unselect)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def select_all(self):
        for i in range(self.table.rowCount()): self.table.item(i, 0).setCheckState(Qt.CheckState.Checked)

    def unselect_all(self):
        for i in range(self.table.rowCount()):
            state = self.table.item(i, 0).checkState()
            new_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            self.table.item(i, 0).setCheckState(new_state)

    def accept_selection(self):
        self.selected_tasks = []
        for i in range(self.table.rowCount()):
            chk_item = self.table.item(i, 0)
            if chk_item.checkState() == Qt.CheckState.Checked:
                path = chk_item.data(Qt.ItemDataRole.UserRole)
                container = self.table.cellWidget(i, 2)
                combo = container.findChild(QComboBox)
                node_data = combo.currentData()
                self.selected_tasks.append({"path": path, "node_data": node_data})
        if not self.selected_tasks:
            QMessageBox.warning(self, "提示", "请至少勾选一个项目！")
            return
        self.accept()


# ================= 单一项目编辑器 =================
class ProjectEditor(QWidget):
    def __init__(self, main_app, project_path=None, initial_data=None):
        super().__init__()
        self.main_app = main_app
        self.curr_path = project_path
        self.raw_data = []
        self.is_modified = False
        self._split_thread = None

        default_data = {
            "name": "未命名项目", "audio_path": "", "srt_path": "",
            "role_cards": [], "scenes": [],
            "keyframe_settings": {
                "start_scale": 110, "end_scale": 130, "start_x": 0, "start_y": 0, "end_x": 0, "end_y": 0,
                "random_direction": True, "preset_mode": "custom", "use_custom_pan": False
            },
            "export_settings": {"bgm_volume": 0.2, "subtitle_effect_id": "", "resolution_mode": "16:9", "bgm_path": ""},
            "custom_prompt_template": "", "workflow_file": ""
        }

        if initial_data:
            self.data = initial_data
        elif project_path and os.path.exists(project_path):
            self.load_data_from_file(project_path)
        else:
            self.data = default_data

        self.project_manager = ProjectManager(self)
        self.role_manager = RoleManager(self)
        self.inference_manager = InferenceManager(self)
        self.image_gen_manager = ImageGenManager(self)
        self.export_manager = ExportManager(self)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.perform_autosave)
        self.autosave_timer.start(AUTO_SAVE_INTERVAL)

        self.init_ui()
        if self.curr_path: self.after_load_init()

    def load_data_from_file(self, path):
        try:
            # 🌟 1. 引入全局文件读写锁，安全加载项目数据
            with PROJECT_FILE_LOCK:
                with open(path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)

            # 🌟 2. 【强化版路径自愈逻辑】：解决换版、移动目录后图片丢失问题
            # 获取当前软件运行的绝对根目录，并统一斜杠格式
            current_root = os.path.abspath(os.getcwd())

            if 'scenes' in self.data:
                for scene in self.data['scenes']:
                    if 'images' in scene and scene['images']:
                        fixed_images = []
                        for img_path in scene['images']:
                            # 格式化路径，防止反斜杠冲突
                            img_path = img_path.replace("/", "\\")

                            # 情况 A：如果原始记录的绝对路径仍然有效，直接使用
                            if os.path.exists(img_path):
                                fixed_images.append(img_path)
                            else:
                                # 情况 B：原始路径失效，开始智能“搜寻”
                                img_filename = os.path.basename(img_path)
                                # 强制到当前 EXE 目录下的 temp_gen 文件夹中找同名文件
                                potential_new_path = os.path.abspath(
                                    os.path.join(current_root, "temp_gen", img_filename))

                                if os.path.exists(potential_new_path):
                                    fixed_images.append(potential_new_path)
                                else:
                                    # 实在找不到了，保留原路径（界面会显示空白，但不报错）
                                    fixed_images.append(img_path)

                        # 更新该分镜的图片路径列表
                        scene['images'] = fixed_images

            # 🌟 3. 原有初始化逻辑，确保配置项不缺失
            if 'workflow_file' not in self.data: self.data['workflow_file'] = ""
            if 'export_settings' not in self.data: self.data['export_settings'] = {}
            if 'keyframe_settings' not in self.data: self.data['keyframe_settings'] = {}

            kf_defaults = {
                "start_scale": 110, "end_scale": 130, "start_x": 0, "start_y": 0, "end_x": 0, "end_y": 0,
                "random_direction": True, "preset_mode": "custom", "use_custom_pan": False
            }
            for k, v in kf_defaults.items():
                if k not in self.data['keyframe_settings']:
                    self.data['keyframe_settings'][k] = v

        except Exception as e:
            # 如果加载失败，清空数据以防止程序崩溃
            self.data = {}
            print(f"❌ 加载项目文件异常: {e}")

    def after_load_init(self):
        self.lbl_title.setText(self.data.get('name', '未命名'))
        self.import_page.e_aud.setText(self.data.get('audio_path', ''))
        self.import_page.e_srt.setText(self.data.get('srt_path', ''))
        self.import_page.e_bgm.setText(self.data.get('export_settings', {}).get('bgm_path', ''))
        srt_path = self.data.get('srt_path')
        if srt_path and os.path.exists(srt_path):
            try:
                self.raw_data = LocalSRTParser.parse(srt_path)
            except:
                pass

        if self.data.get('scenes'):
            self.split_page.refresh_subtitle_table()
            self.studio_page.refresh_scene_list()
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(0)

    def perform_autosave(self):
        # 🌟 核心防覆盖补丁 2：只有当项目真的被修改了，才执行自动保存，拒绝无意义的定时空刷
        if self.curr_path and self.data.get('scenes') and self.is_modified:
            self.save_proj(silent=True)

    def mark_modified(self):
        self.is_modified = True
        title = self.data.get('name', '未命名')
        if not self.lbl_title.text().endswith("*"): self.lbl_title.setText(f"{title} *")

    def init_ui(self):
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet("background: #252526; border-bottom: 1px solid #333;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 10, 0)
        self.lbl_title = QLabel(self.data.get('name', '新项目'))
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #4fc3f7;")

        self.nav_widget = QWidget()
        nav_layout = QHBoxLayout(self.nav_widget)
        nav_layout.setContentsMargins(20, 0, 20, 0)

        self.btn_nav_import = self.create_nav_btn("1. 导入素材", lambda: self.stack.setCurrentIndex(0))
        self.btn_nav_split = self.create_nav_btn("2. 分镜规划", self.go_sb)
        self.btn_nav_studio = self.create_nav_btn("3. 绘图工坊", self.go_studio)

        nav_layout.addWidget(self.btn_nav_import)
        nav_layout.addWidget(QLabel(">", styleSheet="color:#555; font-weight:bold;"))
        nav_layout.addWidget(self.btn_nav_split)
        nav_layout.addWidget(QLabel(">", styleSheet="color:#555; font-weight:bold;"))
        nav_layout.addWidget(self.btn_nav_studio)

        btn_save = QPushButton("💾 保存项目")
        btn_save.clicked.connect(lambda: self.save_proj())
        btn_save.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; border: 1px solid #444; font-weight: bold; padding: 5px 15px; border-radius: 4px; } QPushButton:hover { background: #388e3c; }")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)

        bl.addWidget(self.lbl_title)
        bl.addWidget(self.nav_widget)
        bl.addStretch()
        bl.addWidget(btn_save)

        self.stack = QStackedWidget()
        self.import_page = ImportPage(self)
        self.split_page = SplitPage(self)
        self.studio_page = StudioPage(self)
        self.stack.addWidget(self.import_page)
        self.stack.addWidget(self.split_page)
        self.stack.addWidget(self.studio_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.stack)

        self.stack.currentChanged.connect(self.update_nav_style)
        self.update_nav_style(0)

    def create_nav_btn(self, text, func):
        btn = QPushButton(text)
        btn.clicked.connect(func)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def update_nav_style(self, idx):
        style_normal = "background: transparent; border: none; color: #888; font-weight: bold; font-size: 14px;"
        style_active = "background: #333; border: 1px solid #1a73e8; border-radius: 4px; color: #4fc3f7; font-weight: bold; font-size: 14px;"
        self.btn_nav_import.setStyleSheet(style_normal)
        self.btn_nav_split.setStyleSheet(style_normal)
        self.btn_nav_studio.setStyleSheet(style_normal)
        if idx == 0:
            self.btn_nav_import.setStyleSheet(style_active)
        elif idx == 1:
            self.btn_nav_split.setStyleSheet(style_active)
        elif idx == 2:
            self.btn_nav_studio.setStyleSheet(style_active)

    def save_proj(self, silent=False):
        try:
            if not self.curr_path:
                if silent: return False
                path, _ = QFileDialog.getSaveFileName(self, "保存项目", PROJECTS_ROOT_DIR, "Project (*.ntp)")
                if not path: return False
                self.curr_path = path

            # 🌟 核心防覆盖补丁 1：绝对禁止在后台挂机、或者处于其他页面时，从不可见的 UI 强行读取空数据去覆盖刚刚生成的内存数据！
            if hasattr(self, 'studio_page') and self.stack.currentWidget() == self.studio_page:
                self.studio_page.sync_data()

            self.data['audio_path'] = self.import_page.e_aud.text()
            self.data['srt_path'] = self.import_page.e_srt.text()

            if 'export_settings' not in self.data: self.data['export_settings'] = {}
            if self.import_page.e_bgm.text(): self.data['export_settings']['bgm_path'] = self.import_page.e_bgm.text()

            # 🌟 修复 Bug 2: 引入全局文件读写锁，防止主界面自动保存与后台大模型生成同时抢占文件导致文件内容清零！
            with PROJECT_FILE_LOCK:
                with open(self.curr_path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)

            self.is_modified = False
            title = self.data.get('name', '未命名')
            self.lbl_title.setText(title)
            idx = self.main_app.tab_widget.indexOf(self)
            if idx != -1: self.main_app.tab_widget.setTabText(idx, f"📄 {title}")

            if not silent:
                try:
                    self.studio_page.log("项目保存成功")
                except:
                    pass
            return True
        except Exception as e:
            if not silent: QMessageBox.critical(self, "保存失败", str(e))
            return False

    def go_sb(self):
        self.stack.setCurrentIndex(1)

    def go_studio(self):
        self.studio_page.refresh_scene_list()
        self.stack.setCurrentIndex(2)

    def add_role_card(self, name="", desc=""):
        self.role_manager.add_role_card(name, desc)

    def add_empty_role_card(self):
        self.role_manager.add_empty_role_card()

    def clear_roles(self):
        self.role_manager.clear_roles()

    def run_extract(self):
        self.role_manager.run_extract()

    def import_roles_from_file(self):
        self.role_manager.import_from_file()

    def on_roles_extracted_callback(self):
        self.save_proj(silent=True)
        if hasattr(self, 'studio_page'): self.studio_page.log("角色提取完成，数据已自动保存")

    def handle_card_action(self, action, scene_id):
        if action == "infer":
            self.inference_manager.run_infer_target(scene_id)
        elif action == "gen":
            self.image_gen_manager.run_gen_target(scene_id)

    def run_infer_all(self):
        self.inference_manager.run_infer_all()

    def run_infer_target(self, idx):
        self.inference_manager.run_infer_target(idx)

    def run_gen_all(self, skip=False):
        self.image_gen_manager.run_gen_target(None, skip)

    def run_gen_target(self, idx, skip=False):
        self.image_gen_manager.run_gen_target(idx, skip)

    def stop_gen(self):
        self.image_gen_manager.stop_gen()

    def stop_all_tasks(self):
        try:
            if hasattr(self, 'studio_page'):
                self.studio_page.log("🛑 收到停止指令，正在安全中断所有底层任务...")
        except Exception:
            pass

        # 1. 停止推理引擎
        if hasattr(self, 'inference_manager'):
            self.inference_manager.cancel()
            # 🌟 修复 Bug 1 致命闪退：切断信号，拔除引线，防止线程往销毁的 UI 发数据
            if hasattr(self.inference_manager, 'active_workers'):
                for w in self.inference_manager.active_workers:
                    try:
                        w.log_signal.disconnect()
                    except:
                        pass
                    try:
                        w.sys_log_signal.disconnect()
                    except:
                        pass
                    try:
                        w.data_signal.disconnect()
                    except:
                        pass
                    try:
                        w.finished_signal.disconnect()
                    except:
                        pass

        # 2. 停止生图引擎
        if hasattr(self, 'image_gen_manager'):
            self.image_gen_manager.stop_gen()
            if hasattr(self.image_gen_manager, 't_img') and self.image_gen_manager.t_img:
                try:
                    self.image_gen_manager.t_img.requestInterruption()
                except:
                    pass
                # 切断信号
                try:
                    self.image_gen_manager.t_img.log_signal.disconnect()
                except:
                    pass
                try:
                    self.image_gen_manager.t_img.image_ready_signal.disconnect()
                except:
                    pass
                try:
                    self.image_gen_manager.t_img.finished_signal.disconnect()
                except:
                    pass
                try:
                    self.image_gen_manager.t_img.error_signal.disconnect()
                except:
                    pass

        # 3. 停止角色提取引擎
        if hasattr(self, 'role_manager'):
            self.role_manager.cancel()
            if hasattr(self.role_manager, 'thread') and self.role_manager.thread:
                try:
                    self.role_manager.thread.finished_signal.disconnect()
                except:
                    pass
                try:
                    self.role_manager.thread.error_signal.disconnect()
                except:
                    pass
                try:
                    self.role_manager.thread.log_signal.disconnect()
                except:
                    pass

        # 4. 停止智能分镜引擎
        if hasattr(self, '_split_thread') and self._split_thread:
            try:
                self._split_thread.cancel()
            except:
                pass
            try:
                self._split_thread.finished_signal.disconnect()
            except:
                pass
            try:
                self._split_thread.error_signal.disconnect()
            except:
                pass
            try:
                self._split_thread.log_signal.disconnect()
            except:
                pass
            try:
                self._split_thread.progress_signal.disconnect()
            except:
                pass

    def run_exp(self):
        if hasattr(self,
                   'image_gen_manager') and self.image_gen_manager.t_img and self.image_gen_manager.t_img.isRunning():
            reply = QMessageBox.warning(
                self, "生图未完成",
                "当前项目正在生图中，现在导出草稿可能会【缺失部分图片】！\n\n💡 提示：导出本作品绝对不会影响其他正在生图的项目。\n\n是否确认要强制导出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.save_proj(silent=True)
        self.export_manager.run_export()

    def run_split(self, threshold=30, early_min=2, early_max=3, late_min=5, late_max=8, mode=None, silent=False):
        if not self.raw_data and self.import_page.e_srt.text():
            try:
                self.raw_data = LocalSRTParser.parse(self.import_page.e_srt.text())
            except:
                pass
        if not self.raw_data:
            if not silent: QMessageBox.warning(self, "提示", "请先导入SRT字幕")
            return

        self.split_page.btn_split.setEnabled(False)
        self.split_page.btn_split.setText("处理中...")

        m_mode = mode if mode is not None else ('ai' if self.split_page.rb_ai.isChecked() else 'fixed')

        t = SmartSplitThread(
            self.raw_data,
            threshold=threshold,
            early_min=early_min,
            early_max=early_max,
            late_min=late_min,
            late_max=late_max,
            mode=m_mode
        )

        def on_fin(scenes):
            self.data['scenes'] = scenes
            self.renumber_scenes()
            self.split_page.refresh_subtitle_table()
            self.split_page.btn_split.setEnabled(True)
            self.split_page.btn_split.setText("开始智能分镜")
            self.mark_modified()
            self.save_proj(silent=True)
            if hasattr(self, 'studio_page'):
                self.studio_page.refresh_scene_list()
                if silent: self.studio_page.log("✅ 后台分镜划分完毕")
            if not silent:
                QMessageBox.information(self, "完成", "分镜规划完毕")

        def on_err(e):
            self.split_page.btn_split.setEnabled(True)
            self.split_page.btn_split.setText("开始智能分镜")
            if hasattr(self, 'studio_page'):
                self.studio_page.log(f"❌ 分镜失败: {e}")
            if not silent: QMessageBox.warning(self, "错误", str(e))

        t.finished_signal.connect(on_fin)
        t.error_signal.connect(on_err)
        self._split_thread = t
        t.start()

    def reset_split(self):
        if not self.raw_data:
            QMessageBox.warning(self, "提示", "您还没导入字幕或分镜数据为空！")
            return

        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置分镜吗？\n\n这将清空当前的分镜组合，并【1对1还原】为最原始的单条字幕列表。\n(注：已生成的图片和提示词记录将会一并清除)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            scenes = []
            for i, sub in enumerate(self.raw_data):
                scenes.append({
                    "index": i + 1,
                    "duration": round(sub.get('duration', 2.0), 2),
                    "text": sub['text'],
                    "sub_ids": [sub.get('index', i + 1)],
                    "prompt": "",
                    "status": "等待处理",
                    "images": [],
                    "selected_image_index": -1,
                    "roles": []
                })
            self.data['scenes'] = scenes
            self.split_page.refresh_subtitle_table()
            if hasattr(self, 'studio_page'):
                self.studio_page.refresh_scene_list()
            self.mark_modified()
            self.save_proj(silent=True)
            QMessageBox.information(self, "重置成功", "已完美还原为原始的单条字幕列表！")

    def merge_selected_subtitles(self):
        selected_rows = sorted(set(item.row() for item in self.split_page.tb_sb.selectedItems()))
        if len(selected_rows) < 2: return
        merged_sub_ids, merged_texts, merged_duration = [], [], 0
        for row in selected_rows:
            scene = self.data['scenes'][row]
            merged_sub_ids.extend(scene.get('sub_ids', []))
            merged_texts.append(scene['text'])
            merged_duration += scene['duration']
        new_scene = {
            "index": 0, "duration": round(merged_duration, 2), "text": "\n".join(merged_texts),
            "sub_ids": merged_sub_ids, "prompt": "", "status": "等待处理",
            "images": [], "selected_image_index": -1, "roles": []
        }
        for row in reversed(selected_rows): self.data['scenes'].pop(row)
        self.data['scenes'].insert(selected_rows[0], new_scene)
        self.renumber_scenes()
        self.split_page.refresh_subtitle_table()
        self.mark_modified()

    def split_selected_subtitle(self, row):
        if not self.raw_data: return
        scene = self.data['scenes'][row]
        sub_ids = scene.get('sub_ids', [])
        if len(sub_ids) <= 1: return
        raw_map = {x['index']: x for x in self.raw_data}
        new_scenes = []
        for sid in sub_ids:
            raw = raw_map.get(sid)
            if raw:
                new_scenes.append({
                    "index": 0, "duration": raw['duration'], "text": raw['text'],
                    "sub_ids": [sid], "prompt": "", "status": "等待处理",
                    "images": [], "selected_image_index": -1, "roles": []
                })
        if not new_scenes: return
        self.data['scenes'].pop(row)
        for i, ns in enumerate(new_scenes): self.data['scenes'].insert(row + i, ns)
        self.renumber_scenes()
        self.split_page.refresh_subtitle_table()
        self.mark_modified()

    def renumber_scenes(self):
        for i, s in enumerate(self.data['scenes']): s['index'] = i + 1

    def edit_prompt_template(self):
        dlg = PromptTemplateDialog(self.data.get('custom_prompt_template', ''), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.data['custom_prompt_template'] = dlg.get_template()
            self.mark_modified()

    def import_prompt_template(self):
        f, _ = QFileDialog.getOpenFileName(self, "导入", "", "TXT (*.txt)")
        if f:
            with open(f, 'r', encoding='utf-8') as file: self.data['custom_prompt_template'] = file.read()
            self.mark_modified()
            QMessageBox.information(self, "成功", "导入成功")

    def reset_prompt_template(self):
        self.data['custom_prompt_template'] = ""
        self.mark_modified()
        QMessageBox.information(self, "重置", "已恢复默认")

    def clear_all_prompts(self):
        for s in self.data['scenes']: s['prompt'] = ""
        self.studio_page.refresh_scene_list()
        self.mark_modified()

    def batch_select_images(self):
        idx, ok = QInputDialog.getInt(self, "批量选择", "选第几张图 (1-10):", 1, 1, 10, 1)
        if ok:
            cnt = 0
            for s in self.data['scenes']:
                if len(s.get('images', [])) >= idx:
                    s['selected_image_index'] = idx - 1
                    cnt += 1
            self.studio_page.refresh_scene_list()
            self.mark_modified()
            QMessageBox.information(self, "完成", f"已切换 {cnt} 个镜头")

    def open_keyframe_settings(self):
        dlg = KeyframeDialog(self.data.get('keyframe_settings', {}), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.data['keyframe_settings'] = dlg.get_settings_dict()
            self.mark_modified()


# ================= 主窗口程序 =================
class NovelTweetApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("老虎小说推文软件")
        self.resize(1800, 900)
        self.apply_theme()

        self.audio_merger = AudioMergerWidget()
        self.subtitle_merger = SubtitleMergerWidget()

        self.global_task_manager = GlobalTaskManager(self)
        self.global_task_manager.all_finished.connect(self.show_global_finish_msg)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background: #1e1e1e; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 5, 10, 5)

        lbl_logo = QLabel(f"AI 老虎推文软件 Pro ({APP_VERSION})")
        lbl_logo.setStyleSheet("color: #1a73e8; font-weight: bold; font-size: 16px; margin-right: 20px;")
        top_layout.addWidget(lbl_logo)

        btn_home = QPushButton("🏠 首页")
        btn_home.clicked.connect(lambda: self.tab_widget.setCurrentIndex(0))

        btn_settings = QPushButton("⚙ 系统全局设置")
        btn_settings.clicked.connect(self.open_settings_dialog)

        # 🌟 新增：全局画风与提示词设置入口
        btn_style_settings = QPushButton("🎭 全局画风词")
        btn_style_settings.clicked.connect(self.open_global_style_dialog)

        btn_role_lib = QPushButton("📚 全局角色库")
        btn_role_lib.clicked.connect(lambda: RoleLibraryDialog(self).exec())

        btn_g_split = QPushButton("✂️ 批量分镜")
        btn_g_split.clicked.connect(self.run_global_split_tasks)

        btn_g_extract = QPushButton("🧠 批量角色提取")
        btn_g_extract.clicked.connect(self.run_global_role_extract)

        btn_g_infer = QPushButton("🎬 批量分镜推理")
        btn_g_infer.clicked.connect(self.run_global_scene_infer)

        btn_g_gen = QPushButton("🎨 全局批量生图")
        btn_g_gen.clicked.connect(self.run_global_image_gen)

        btn_g_stop = QPushButton("🛑 停止全局任务")
        btn_g_stop.clicked.connect(self.stop_global_tasks)

        btn_unbind = QPushButton("🔓 注销授权")
        btn_unbind.setToolTip("清除本机绑定，方便更换电脑使用")
        btn_unbind.clicked.connect(self.unbind_license)
        btn_unbind.setStyleSheet("""
            QPushButton { background: #5c2b29; color: #ff8a80; border: 1px solid #ff5252; padding: 8px 12px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #d32f2f; color: white; }
        """)

        for b in [btn_home, btn_settings, btn_style_settings, btn_role_lib, btn_g_split, btn_g_extract, btn_g_infer,
                  btn_g_gen]:
            b.setStyleSheet("""
                QPushButton { background: #333; color: #eee; border: 1px solid #555; padding: 8px 12px; border-radius: 4px; font-weight: bold; }
                QPushButton:hover { background: #444; border-color: #1a73e8; }
            """)
            top_layout.addWidget(b)

        btn_g_stop.setStyleSheet("""
            QPushButton { background: #c62828; color: white; border: 1px solid #ff5252; padding: 8px 12px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #d32f2f; }
        """)
        top_layout.addWidget(btn_g_stop)

        top_layout.addWidget(btn_unbind)

        top_layout.addStretch()

        btn_tools = QPushButton("🔧 工具箱")
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; } QMenu::item { padding: 8px 20px; } QMenu::item:selected { background-color: #1a73e8; }")
        menu.addAction("🎵 音频合并", self.open_audio_merger)
        menu.addAction("📝 字幕合并", self.open_subtitle_merger)
        menu.addAction("📤 批量导出草稿", self.open_batch_export)
        btn_tools.setMenu(menu)
        btn_tools.setStyleSheet(
            "QPushButton { background: #2d2d2d; color: #ddd; border: 1px solid #555; padding: 8px 15px; border-radius: 4px; }")
        top_layout.addWidget(btn_tools)

        layout.addWidget(top_bar)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1e1e1e; }
            QTabWidget::tab-bar { left: 5px; }
            QTabBar::tab { background: #2d2d2d; color: #888; padding: 8px 20px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; min-width: 100px; }
            QTabBar::tab:selected { background: #1e1e1e; color: #fff; border-top: 2px solid #1a73e8; font-weight: bold; }
            QTabBar::tab:hover { background: #3a3a3a; color: #ddd; }
            QTabBar::close-button { subcontrol-position: right; }
            QTabBar::close-button:hover { background: #c62828; border-radius: 2px; }
        """)

        self.home_page = HomePage(self)
        self.tab_widget.addTab(self.home_page, "主页")
        self.tab_widget.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

        layout.addWidget(self.tab_widget)

    def open_settings_dialog(self):
        dlg = SettingsDialog(None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, ProjectEditor) and hasattr(widget, 'studio_page'):
                    widget.studio_page.load_workflows_to_combo()

    def open_global_style_dialog(self):
        """打开全局画风设置界面"""
        dlg = GlobalStyleDialog(self)
        dlg.exec()

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #1e1e1e; color: #ffffff; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }
            QWidget { color: #e0e0e0; font-size: 14px; }
            QDialog, QInputDialog { background-color: #252526; border: 1px solid #444; }

            QMessageBox { background-color: #252526; border: 1px solid #555; }
            QMessageBox QLabel { color: #ffffff; font-size: 16px; font-weight: bold; min-height: 45px; margin-right: 20px; }
            QMessageBox QPushButton { background-color: #1a73e8; color: white; border: none; padding: 10px 25px; border-radius: 6px; font-weight: bold; font-size: 15px; min-width: 80px; }
            QMessageBox QPushButton:hover { background-color: #1557b0; }
            QMessageBox QPushButton:pressed { background-color: #0d47a1; }

            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox { background: #1e1e1e; border: 1px solid #555; color: #fff; padding: 6px; border-radius: 4px; }
            QComboBox { background: #333; border: 1px solid #555; color: white; padding: 5px; border-radius: 4px; min-width: 6em; }
            QComboBox QAbstractItemView { background-color: #2b2b2b; color: #ffffff; selection-background-color: #1a73e8; selection-color: #ffffff; outline: none; border: 1px solid #555; }
            QPushButton:disabled { background-color: #252526; color: #666; border-color: #333; }
            QListWidget, QTreeWidget, QTableWidget { background-color: #1e1e1e; alternate-background-color: #252526; color: #e0e0e0; border: 1px solid #444; outline: none; }
            QListWidget::item, QTableWidget::item { padding: 8px; border-bottom: 1px solid #2d2d2d; }
            QListWidget::item:selected, QTableWidget::item:selected { background-color: #37373d; border-left: 3px solid #1a73e8; }
            QHeaderView::section { background-color: #333; color: #fff; padding: 5px; border: none; font-weight: bold; }
            QScrollBar:vertical { background: #1e1e1e; width: 12px; margin: 0; }
            QScrollBar::handle:vertical { background: #444; min-height: 20px; border-radius: 6px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

    def show_global_finish_msg(self, task_type):
        QMessageBox.information(self, "✨ 批量任务完成",
                                f"您启动的批量任务【{task_type}】已全部处理完毕！\n您可以去各个项目页面查看结果。")

    # 🌟 新增方法：用于播放系统成功提示音
    def play_finish_sound(self):
        """播放 Windows 默认成功提示音"""
        try:
            if os.name == 'nt':
                # 使用系统默认的 Asterisk (星号) 提示音，清脆不刺耳
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
        except Exception as e:
            print(f"播放音效失败: {e}")

    def unbind_license(self):
        from 逻辑.auth_module import AuthManager
        card_key = AuthManager.get_current_card_key()

        dlg = UnbindDialog(self, card_key)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if AuthManager.clear_license():
                QMessageBox.information(self, "注销成功", "✅ 本机授权已成功清除！软件即将退出。")
                sys.exit(0)
            else:
                QMessageBox.critical(self, "注销失败", "❌ 授权文件被占用，注销失败，请重启软件后重试。")

    def create_new_project_flow(self):
        name, ok = QInputDialog.getText(self, "新建项目", "项目名称:")
        if not ok or not name.strip(): return
        name = name.strip()
        proj_dir = os.path.join(PROJECTS_ROOT_DIR, name)
        if os.path.exists(proj_dir):
            QMessageBox.warning(self, "错误", "项目已存在")
            return
        try:
            os.makedirs(proj_dir)
            os.makedirs(os.path.join(proj_dir, "assets"))
            ntp_path = os.path.join(proj_dir, f"{name}.ntp")
            default_data = {
                "name": name, "scenes": [], "workflow_file": "",
                "keyframe_settings": {"start_scale": 110, "end_scale": 130, "start_x": 0, "start_y": 0, "end_x": 0,
                                      "end_y": 0, "random_direction": True, "preset_mode": "custom",
                                      "use_custom_pan": False}
            }
            # 🌟 写入新文件时同样上锁，养成好习惯
            with PROJECT_FILE_LOCK:
                with open(ntp_path, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f)
            self.add_project_tab(ntp_path, default_data)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建失败: {e}")

    def create_project_auto(self, name, audio_path, srt_path, open_now=True):
        name = name.strip()
        proj_dir = os.path.join(PROJECTS_ROOT_DIR, name)
        try:
            ntp_path = os.path.join(proj_dir, f"{name}.ntp")
            if not os.path.exists(proj_dir):
                os.makedirs(proj_dir, exist_ok=True)
                os.makedirs(os.path.join(proj_dir, "assets"), exist_ok=True)
                default_data = {
                    "name": name, "audio_path": audio_path, "srt_path": srt_path, "scenes": [], "workflow_file": "",
                    "keyframe_settings": {"start_scale": 110, "end_scale": 130, "start_x": 0, "start_y": 0, "end_x": 0,
                                          "end_y": 0, "random_direction": True, "preset_mode": "custom",
                                          "use_custom_pan": False}
                }
                with PROJECT_FILE_LOCK:
                    with open(ntp_path, 'w', encoding='utf-8') as f:
                        json.dump(default_data, f, indent=2, ensure_ascii=False)
            if open_now: self.load_project_file(ntp_path)
        except Exception as e:
            print(f"批量创建项目 {name} 失败: {e}")

    def stop_global_tasks(self):
        # 一键强杀！停止所有项目的后台任务，清理队列
        count = 0
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ProjectEditor):
                widget.stop_all_tasks()
                count += 1

        if count > 0:
            QMessageBox.warning(self, "任务中止", "已强制清空全局排队队列，并向底层发送【强制停止】指令！")

    def run_global_split_tasks(self):
        dlg = BatchSplitDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tasks = dlg.selected_tasks
            mode = dlg.selected_mode
            self.global_task_manager.start_batch("批量分镜规划")
            count = 0
            for task in tasks:
                editor = self.load_project_file(task["path"])
                if editor:
                    editor.run_split(
                        threshold=dlg.selected_threshold,
                        early_min=dlg.selected_early_min,
                        early_max=dlg.selected_early_max,
                        late_min=dlg.selected_late_min,
                        late_max=dlg.selected_late_max,
                        mode=mode,
                        silent=True
                    )
                    if hasattr(editor, '_split_thread') and editor._split_thread:
                        self.global_task_manager.add_task()
                        editor._split_thread.finished_signal.connect(
                            lambda *args: self.global_task_manager.on_task_finished())
                        editor._split_thread.error_signal.connect(
                            lambda *args: self.global_task_manager.on_task_finished())
                    count += 1

    def run_global_role_extract(self):
        dlg = ProjectSelectionDialog(self, "批量角色提取 - 请勾选需要处理的项目")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            paths = dlg.selected_paths
            self.global_task_manager.start_batch("批量角色提取")
            count = 0
            for p in paths:
                editor = self.load_project_file(p)
                if editor:
                    editor.run_extract()
                    if hasattr(editor.role_manager, 'thread') and editor.role_manager.thread:
                        self.global_task_manager.add_task()
                        editor.role_manager.thread.finished_signal.connect(
                            lambda *args: self.global_task_manager.on_task_finished())
                        editor.role_manager.thread.error_signal.connect(
                            lambda *args: self.global_task_manager.on_task_finished())
                    count += 1

    def run_global_scene_infer(self):
        """完美对接原生跨项目底层排队机制，附带全套并发控制面板"""
        dlg = BatchInferenceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            paths = dlg.selected_paths
            if not paths:
                return

            # 寻找一个当前打开的项目作为“挂载点”，如果没有则打开第一个
            host_editor = None
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, ProjectEditor):
                    host_editor = widget
                    break

            if not host_editor:
                host_editor = self.load_project_file(paths[0])

            if not host_editor:
                QMessageBox.warning(self, "错误", "未能加载宿主项目，任务启动失败！")
                return

            # 切换到宿主标签页，让用户直观看到全局日志播报
            for i in range(self.tab_widget.count()):
                if self.tab_widget.widget(i) == host_editor:
                    self.tab_widget.setCurrentIndex(i)
                    break

            count = 0
            for p_path in paths:
                try:
                    target_editor = None
                    # 如果该项目刚好已经被打开了，为了避免脏数据，直接调用它的内存数据保存并排队
                    for i in range(self.tab_widget.count()):
                        w = self.tab_widget.widget(i)
                        if isinstance(w, ProjectEditor) and w.curr_path == p_path:
                            target_editor = w
                            break

                    if target_editor:
                        scenes = target_editor.data.get('scenes', [])
                        roles = target_editor.data.get('role_cards', [])
                        custom_template = target_editor.data.get('custom_prompt_template', '')
                        target_editor.save_proj(silent=True)
                    else:
                        # 核心大招：对于绝大部分没打开的挂机项目，在后台离线读取，不污染UI
                        with PROJECT_FILE_LOCK:
                            with open(p_path, 'r', encoding='utf-8') as f:
                                proj_data = json.load(f)
                        scenes = proj_data.get('scenes', [])
                        roles = proj_data.get('role_cards', [])
                        custom_template = proj_data.get('custom_prompt_template', '')

                    if not scenes:
                        continue

                    # 直接注入到宿主的排队引擎中
                    host_editor.inference_manager.submit_project_task(
                        project_path=p_path,
                        scenes_list=scenes,
                        role_cards=roles,
                        custom_template=custom_template
                    )
                    count += 1
                except Exception as e:
                    print(f"读取项目 {p_path} 加入队列失败: {e}")

            if count > 0:
                QMessageBox.information(
                    self,
                    "批量排队成功",
                    f"🎉 成功将 {count} 个项目注入全局推理队列！\n"
                    f"请不要关闭当前项目，您可以在右侧日志窗口查看所有项目的进度播报。"
                )

    def run_global_image_gen(self):
        dlg = BatchImageGenDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tasks = dlg.selected_tasks
            self.global_task_manager.start_batch("批量全局生图")
            count = 0
            for task in tasks:
                editor = self.load_project_file(task["path"])
                if editor:
                    node_data = task["node_data"]
                    if node_data == "default" or node_data is None:
                        editor.data['selected_workflow_name'] = 'default'
                        if 'workflow_file' in editor.data: del editor.data['workflow_file']
                        if 'target_node_url' in editor.data: del editor.data['target_node_url']
                    else:
                        editor.data['selected_workflow_name'] = node_data.get('name')
                        editor.data['workflow_file'] = node_data.get('workflow')
                        editor.data['target_node_url'] = node_data.get('url')

                    if hasattr(editor, 'studio_page'):
                        editor.studio_page.load_workflows_to_combo()

                    editor.run_gen_all(skip=False)
                    if hasattr(editor.image_gen_manager, 't_img') and editor.image_gen_manager.t_img:
                        self.global_task_manager.add_task()

                        proj_name = editor.data.get('name', '未命名')

                        def create_project_finished_callback(p_name):
                            def _cb():
                                # 🌟 优化：单个项目生图完成时播放提示音
                                self.play_finish_sound()
                                self.global_task_manager.on_task_finished()
                                QMessageBox.information(self, "✅ 单项目生图完成",
                                                        f"🎉 项目【{p_name}】的生图任务已全部完成！")

                            return _cb

                        try:
                            editor.image_gen_manager.t_img.finished_signal.disconnect()
                        except Exception:
                            pass

                        editor.image_gen_manager.t_img.finished_signal.connect(
                            create_project_finished_callback(proj_name))
                        editor.image_gen_manager.t_img.error_signal.connect(
                            lambda *args: self.global_task_manager.on_task_finished())
                    count += 1

    def open_proj(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", PROJECTS_ROOT_DIR, "Project (*.ntp)")
        if path: self.load_project_file(path)

    def load_project_file(self, path):
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ProjectEditor) and widget.curr_path == path:
                self.tab_widget.setCurrentIndex(i)
                return widget
        return self.add_project_tab(path)

    def add_project_tab(self, path, data=None):
        try:
            editor = ProjectEditor(self, path, data)
            name = data.get('name') if data else os.path.basename(path).replace(".ntp", "")
            idx = self.tab_widget.addTab(editor, f"📄 {name}")
            self.tab_widget.setCurrentIndex(idx)
            self.home_page.load_recent_projects()
            return editor
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            return None

    def close_tab(self, idx):
        if idx == 0: return
        widget = self.tab_widget.widget(idx)
        if isinstance(widget, ProjectEditor):
            if widget.is_modified:
                reply = QMessageBox.question(self, "未保存", f"项目 [{widget.data.get('name')}] 有未保存内容，是否保存？",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Cancel: return
                if reply == QMessageBox.StandardButton.Yes: widget.save_proj()

            # 关闭自动保存，防止幽灵保存
            widget.autosave_timer.stop()

            # 【关键】拔除引线：强制停止底层所有线程，并断开与界面的信号连接，杜绝野指针崩溃！
            widget.stop_all_tasks()

        self.tab_widget.removeTab(idx)

        if isinstance(widget, ProjectEditor):
            widget.deleteLater()

    def open_audio_merger(self):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "🎵 音频合并":
                self.tab_widget.setCurrentIndex(i)
                return
        self.tab_widget.addTab(self.audio_merger, "🎵 音频合并")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

    def open_subtitle_merger(self):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "📝 字幕合并":
                self.tab_widget.setCurrentIndex(i)
                return
        self.tab_widget.addTab(self.subtitle_merger, "📝 字幕合并")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

    def open_batch_export(self):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "📤 批量导出":
                self.tab_widget.setCurrentIndex(i)
                return
        from 界面.batch_export_page import BatchExportPage
        page = BatchExportPage(self)
        self.tab_widget.addTab(page, "📤 批量导出")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

    def run_batch_export(self, paths):
        host_editor = None
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ProjectEditor):
                host_editor = widget
                break

        if not host_editor and paths:
            host_editor = self.load_project_file(paths[0])

        if host_editor:
            host_editor.export_manager.run_batch_export(paths)
        else:
            QMessageBox.warning(self, "提示", "未能加载导出模块，请先打开任意一个项目！")