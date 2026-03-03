import configparser
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QPushButton,
                             QFormLayout, QComboBox, QLineEdit, QHBoxLayout,
                             QDialogButtonBox, QTextEdit, QFileDialog)
from PyQt6.QtCore import Qt

from 配置.app_config import CONFIG_FILE, DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_UPSCALE_FACTOR
from 配置 import config
from 逻辑.app_workers import ConnectionTestThread


# =========================================================
#  设置窗口
# =========================================================

class TestLogDialog(QDialog):
    def __init__(self, parent, service_type, manual_url=None):
        super().__init__(parent)
        self.setWindowTitle(f"连接诊断 - {service_type.upper()}")
        self.resize(700, 500)
        self.service_type = service_type
        self.manual_url = manual_url

        layout = QVBoxLayout()
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setStyleSheet("""
            background-color: #111; 
            color: #00ff00; 
            font-family: 'Consolas', 'Courier New', monospace; 
            font-size: 14px;
            border: 1px solid #444;
            padding: 10px;
        """)
        layout.addWidget(self.text_log)

        self.btn_close = QPushButton("关闭窗口")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        self.btn_close.setStyleSheet("""
            QPushButton { background-color: #333; color: white; padding: 10px; font-size: 14px; border: 1px solid #555; }
            QPushButton:hover { background-color: #444; }
            QPushButton:disabled { color: #777; }
        """)
        layout.addWidget(self.btn_close)
        self.setLayout(layout)
        self.start_test()

    def log(self, text):
        self.text_log.append(text)
        sb = self.text_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_test(self):
        self.thread = ConnectionTestThread(self.service_type, self.manual_url)
        self.thread.log_signal.connect(self.log)
        self.thread.finished_signal.connect(lambda s: self.btn_close.setEnabled(True))
        self.thread.start()

    def closeEvent(self, event):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait()
        super().closeEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统全局配置")
        self.resize(850, 750)  # 稍微加高一点
        self.cfg = configparser.ConfigParser()
        try:
            self.cfg.read(CONFIG_FILE, encoding='utf-8')
        except Exception:
            # 读取失败时使用空配置
            pass
        if 'DEFAULT' not in self.cfg: self.cfg['DEFAULT'] = {}
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { font-size: 14px; font-weight: bold; color: #ffffff; }

            QLineEdit { 
                background: #333; 
                color: #ffffff; 
                padding: 8px; 
                border: 1px solid #555; 
                border-radius: 4px; 
            }
            QLineEdit:focus { border: 1px solid #1a73e8; }

            QComboBox { 
                background: #333; 
                color: #ffffff; 
                padding: 6px; 
                border: 1px solid #555; 
                border-radius: 4px; 
            }
            QComboBox QAbstractItemView {
                background-color: #333333;
                color: #ffffff;
                selection-background-color: #1a73e8;
                selection-color: #ffffff;
                border: 1px solid #555;
            }

            QPushButton { 
                padding: 8px; 
                background: #3a3a3a; 
                color: white; 
                border: 1px solid #555; 
                border-radius: 4px; 
            }
            QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
        """)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(15)

        self.combo_type = QComboBox()
        self.combo_type.addItems(["OpenAI Compatible (如 DeepSeek/OneAPI)", "Google Gemini Native"])
        if self.cfg['DEFAULT'].get('api_type') == 'google': self.combo_type.setCurrentIndex(1)

        self.e_base = QLineEdit(self.cfg['DEFAULT'].get('base_url', DEFAULT_BASE_URL))
        self.combo_model = QComboBox();
        self.combo_model.setEditable(True)
        self.combo_model.addItems([
            "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-2.0-pro-exp",
            "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo",
            "deepseek-chat", "deepseek-reasoner"
        ])
        self.combo_model.setEditText(self.cfg['DEFAULT'].get('model_name', DEFAULT_MODEL))

        self.e_key = QLineEdit(self.cfg['DEFAULT'].get('gemini_key', ''));
        self.e_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_proxy = QLineEdit(self.cfg['DEFAULT'].get('proxy_url', ''))
        self.e_comfy = QLineEdit(self.cfg['DEFAULT'].get('comfy_url', config.DEFAULT_COMFYUI_URL))
        self.e_jy = QLineEdit(self.cfg['DEFAULT'].get('jianying_path', config.JIANYING_DRAFT_DIR))
        self.e_wf = QLineEdit(self.cfg['DEFAULT'].get('default_workflow', ''))

        # --- 新增：放大倍数 ---
        self.combo_upscale = QComboBox()
        self.combo_upscale.addItems(["1x (原图导出)", "2x (高清放大)", "4x (超清放大)"])
        current_upscale = self.cfg['DEFAULT'].get('upscale_factor', DEFAULT_UPSCALE_FACTOR)
        if "2x" in current_upscale:
            self.combo_upscale.setCurrentIndex(1)
        elif "4x" in current_upscale:
            self.combo_upscale.setCurrentIndex(2)
        else:
            self.combo_upscale.setCurrentIndex(0)

        btn_wf = QPushButton("浏览...");
        btn_wf.clicked.connect(lambda: self.set_wf())

        btn_test_ai = QPushButton("⚡ 测试 AI 通讯诊断")
        btn_test_ai.setStyleSheet("background-color: #1a73e8; font-weight: bold;")
        btn_test_ai.clicked.connect(self.test_ai)

        btn_test_cf = QPushButton("⚡ 测试 ComfyUI 连接")
        btn_test_cf.setStyleSheet("background-color: #ca5c00; font-weight: bold;")
        btn_test_cf.clicked.connect(self.test_cf)

        form.addRow("API协议:", self.combo_type)
        form.addRow("Base URL:", self.e_base)
        form.addRow("模型名称:", self.combo_model)
        form.addRow("API Key:", self.e_key)
        form.addRow("代理地址:", self.e_proxy)
        form.addRow("", btn_test_ai)
        form.addRow("ComfyUI:", self.e_comfy)
        form.addRow("", btn_test_cf)

        # 插入放大选项
        form.addRow("导出画质:", self.combo_upscale)

        form.addRow("剪映目录:", self.e_jy)
        h = QHBoxLayout();
        h.addWidget(self.e_wf);
        h.addWidget(btn_wf)
        form.addRow("工作流:", h)

        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save);
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def set_wf(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择工作流", "", "JSON (*.json)")
        if f: self.e_wf.setText(f)

    def test_ai(self):
        self.save(manual=False);
        TestLogDialog(self, "gemini").exec()

    def test_cf(self):
        current_input = self.e_comfy.text().strip()
        TestLogDialog(self, "comfy", manual_url=current_input).exec()

    def save(self, manual=True):
        d = self.cfg['DEFAULT']
        d['api_type'] = 'openai' if self.combo_type.currentIndex() == 0 else 'google'
        d['base_url'] = self.e_base.text().strip()
        d['model_name'] = self.combo_model.currentText().strip()
        d['gemini_key'] = self.e_key.text().strip()
        d['proxy_url'] = self.e_proxy.text().strip()
        d['comfy_url'] = self.e_comfy.text().strip()
        d['jianying_path'] = self.e_jy.text().strip()
        d['default_workflow'] = self.e_wf.text().strip()

        # 保存放大倍数
        idx = self.combo_upscale.currentIndex()
        if idx == 1:
            d['upscale_factor'] = "2x"
        elif idx == 2:
            d['upscale_factor'] = "4x"
        else:
            d['upscale_factor'] = "1x"

        with open(CONFIG_FILE, 'w') as f:
            self.cfg.write(f)
        if manual: self.accept()