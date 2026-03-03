import os
import shutil
import configparser
import re
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QScrollArea, QWidget, QGridLayout, QSizePolicy,
    QFileDialog, QMessageBox, QMenu  # 🌟 新增 QMenu
)
from PyQt6.QtCore import Qt, QTimer, QUrl, QSize, pyqtSignal, pyqtSlot, QThread, QPoint
from PyQt6.QtGui import QPixmap, QDesktopServices, QMouseEvent, QImageReader, QImage

from 配置.app_config import CONFIG_FILE
from 逻辑.baidu_trans import BaiduTranslator


class TranslateWorker(QThread):
    """单句翻译工作线程 (升级支持智能语言检测)"""
    translated = pyqtSignal(str, str)  # original_text, translated_text
    error = pyqtSignal(str)

    def __init__(self, text, appid, secret, from_lang='zh'):
        super().__init__()
        self.text = text
        self.appid = appid
        self.secret = secret
        self.from_lang = from_lang

    def run(self):
        translator = BaiduTranslator(self.appid, self.secret)
        # 支持传入 auto 智能识别中英文混合进行翻译
        result, err = translator.translate(self.text, from_lang=self.from_lang, to_lang='en')
        if result:
            self.translated.emit(self.text, result)
        else:
            self.error.emit(err or "翻译失败")


class ClickableLabel(QLabel):
    """支持点击事件的 Label，用于图片预览 (🌟 升级支持右键)"""
    right_clicked = pyqtSignal(QPoint)  # 🌟 新增右键点击信号

    def __init__(self, parent=None, click_callback=None):
        super().__init__(parent)
        self.click_callback = click_callback

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.click_callback:
            self.click_callback()
        elif event.button() == Qt.MouseButton.RightButton:
            # 发射右键信号，并传递全局坐标用于显示菜单
            self.right_clicked.emit(event.globalPosition().toPoint())
        super().mousePressEvent(event)


class ThumbnailLoadWorker(QThread):
    """
    🌟 绝杀修复 2：改用安全的 bytes 传递图片数据。
    彻底杜绝原先传递 C++ QImage 时，后台垃圾回收与前台渲染撞车引发的 0xC0000409 悬空指针崩溃！
    """
    thumb_loaded = pyqtSignal(int, bytes, str)
    all_loaded = pyqtSignal()

    def __init__(self, card_index, paths, target_size):
        super().__init__()
        self.card_index = card_index
        self.paths = paths
        self.target_size = target_size

    def run(self):
        for idx, path in enumerate(self.paths):
            if not os.path.exists(path):
                continue
            try:
                # 只在后台读取纯二进制数据，绝不实例化 Qt 的 C++ UI 对象
                with open(path, 'rb') as f:
                    img_data = f.read()
                self.thumb_loaded.emit(idx, img_data, path)
            except Exception:
                pass
        self.all_loaded.emit()


class SceneCard(QFrame):
    _pixmap_cache = {}
    images_loaded = pyqtSignal(int)

    def __init__(self, scene_data, main_window, lazy_load=False):
        super().__init__()
        self.scene_data = scene_data
        self.index = scene_data['index']
        self.main_window = main_window
        self.lazy_load = lazy_load
        self._loaded = False
        self._last_preview_path = None
        self._cached_preview_pixmap = None

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._do_load)

        self._active_img_workers = []
        self._active_trans_threads = []

        self._is_translating = False

        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.perform_auto_translate)

        self.cfg = configparser.ConfigParser()
        try:
            self.cfg.read(CONFIG_FILE, encoding='utf-8')
        except Exception:
            pass
        self.baidu_appid = self.cfg['DEFAULT'].get('baidu_appid', '').strip()
        self.baidu_secret = self.cfg['DEFAULT'].get('baidu_secret', '').strip()
        self.translator_enabled = bool(self.baidu_appid and self.baidu_secret)

        self.setup_ui()
        self.refresh_ui()

    @classmethod
    def clear_cache(cls):
        """清空图片缓存，释放内存"""
        cls._pixmap_cache.clear()

    def setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(300)

        self.setStyleSheet("""
            SceneCard { background-color: #1e1e1e; border-bottom: 1px solid #333; border-radius: 0px; }
            SceneCard:hover { background-color: #252526; }
            QLabel { font-family: "Microsoft YaHei", Consolas; color: #ccc; border: none; }
            QLabel#IndexLabel { font-size: 24px; font-weight: bold; color: #666; }
            QLabel#DurationLabel { font-size: 12px; color: #777; margin-top: 5px; }
            QLabel#TextBubble { background-color: #2d2d2d; color: #eeeeee; padding: 10px; border-radius: 6px; font-size: 18px; line-height: 1.4; border: 1px solid #3c3c3c; }
            QLabel[role_tag="true"] { background-color: #383838; color: #ccc; padding: 4px 10px; border-radius: 10px; font-size: 11px; border: 1px solid #444; }
            QTextEdit { background-color: #111; border: 1px solid #333; color: #ddd; border-radius: 4px; padding: 5px; font-family: Consolas, "Microsoft YaHei"; font-size: 15px; }
            QTextEdit:focus { border: 1px solid #1a73e8; background-color: #000; }
            QPushButton { background-color: #2d2d2d; color: #ccc; border: 1px solid #444; padding: 6px 12px; border-radius: 4px; font-size: 12px; font-weight: bold; }
            QPushButton:hover { background-color: #3d3d3d; border-color: #666; color: white; }
            QPushButton:pressed { background-color: #1a73e8; border-color: #1a73e8; }
            QPushButton#BtnInfer { border-left: 3px solid #9c27b0; }
            QPushButton#BtnGen { border-left: 3px solid #e65100; }
            QPushButton#BtnDel { border-left: 3px solid #c62828; }
            QPushButton#BtnImport { border-left: 3px solid #2e7d32; }
            QPushButton#BtnExport { border-left: 3px solid #0288d1; }
            QLabel[thumb="true"] { border: 2px solid #333; border-radius: 4px; background: transparent; }
            QLabel[thumb="true"]:hover { border-color: #888; }
            QLabel[thumb_selected="true"] { border-color: #1a73e8; }
            QLabel#PreviewImg { background-color: transparent; border: none; }
            QLabel.SectionTitle { color: #555; font-size: 11px; font-weight: bold; text-transform: uppercase; margin-bottom: 4px; }
        """)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(20, 15, 20, 15)
        self.main_layout.setSpacing(20)

        col_info = QVBoxLayout()
        col_info.setSpacing(10)

        row_idx = QHBoxLayout()
        row_idx.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_id = QLabel(f"{self.index}")
        self.lbl_id.setObjectName("IndexLabel")
        self.lbl_dur = QLabel(f"{self.scene_data['duration']}s")
        self.lbl_dur.setObjectName("DurationLabel")

        row_idx.addWidget(self.lbl_id)
        row_idx.addSpacing(10)
        row_idx.addWidget(self.lbl_dur)
        row_idx.addStretch()
        col_info.addLayout(row_idx)

        self.lbl_text = QLabel(self.scene_data['text'])
        self.lbl_text.setObjectName("TextBubble")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        col_info.addWidget(self.lbl_text)

        self.main_layout.addLayout(col_info, stretch=20)

        col_roles = QVBoxLayout()
        col_roles.setSpacing(5)
        lbl_role_title = QLabel("角色 / ROLES")
        lbl_role_title.setStyleSheet("color: #555; font-size: 11px; font-weight: bold;")
        col_roles.addWidget(lbl_role_title)

        self.role_container = QWidget()
        self.role_layout = QVBoxLayout(self.role_container)
        self.role_layout.setContentsMargins(0, 0, 0, 0)
        self.role_layout.setSpacing(5)
        self.role_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        col_roles.addWidget(self.role_container)
        col_roles.addStretch()

        self.main_layout.addLayout(col_roles, stretch=10)

        col_prompt = QVBoxLayout()
        col_prompt.setSpacing(5)

        lbl_prompt_cn = QLabel("画面描述 (中文)")
        lbl_prompt_cn.setStyleSheet("color: #555; font-size: 11px; font-weight: bold;")
        col_prompt.addWidget(lbl_prompt_cn)

        self.input_cn = QTextEdit()
        self.input_cn.setPlaceholderText("在此输入中文，自动翻译成英文...")
        self.input_cn.textChanged.connect(self.on_cn_user_change)
        col_prompt.addWidget(self.input_cn)

        lbl_prompt_en = QLabel("PROMPT (English)")
        lbl_prompt_en.setStyleSheet("color: #555; font-size: 11px; font-weight: bold;")
        col_prompt.addWidget(lbl_prompt_en)

        self.input_en = QTextEdit()
        self.input_en.setPlaceholderText("Stable Diffusion 提示词...")
        self.input_en.setStyleSheet("color: #aaa; font-style: italic;")
        self.input_en.textChanged.connect(self.sync_data)
        col_prompt.addWidget(self.input_en)

        self.main_layout.addLayout(col_prompt, stretch=30)

        col_media = QHBoxLayout()
        col_media.setSpacing(10)

        v_preview = QVBoxLayout()
        lbl_prev_title = QLabel("当前选择")
        lbl_prev_title.setStyleSheet("color: #555; font-size: 11px; font-weight: bold;")
        v_preview.addWidget(lbl_prev_title)

        preview_container = QWidget()
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.preview_lbl = ClickableLabel(click_callback=self.on_preview_click)
        self.preview_lbl.setObjectName("PreviewImg")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_lbl.setMinimumSize(50, 50)

        self.preview_lbl.right_clicked.connect(
            lambda pos: self.show_image_context_menu(pos, self.scene_data.get('selected_image_index', -1)))

        preview_container_layout.addWidget(self.preview_lbl)
        v_preview.addWidget(preview_container)

        col_media.addLayout(v_preview, stretch=3)

        v_grid = QVBoxLayout()
        lbl_grid_title = QLabel("备选组")
        lbl_grid_title.setStyleSheet("color: #555; font-size: 11px; font-weight: bold;")
        v_grid.addWidget(lbl_grid_title)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("background: transparent; border: none;")
        self.grid_scroll.setFixedWidth(80)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.grid_scroll.setWidget(self.grid_widget)
        v_grid.addWidget(self.grid_scroll)
        col_media.addLayout(v_grid, stretch=1)

        self.main_layout.addLayout(col_media, stretch=35)

        col_btns = QVBoxLayout()
        col_btns.setSpacing(10)
        col_btns.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lbl_ops_title = QLabel("操作")
        lbl_ops_title.setStyleSheet("color: #555; font-size: 11px; font-weight: bold; margin-bottom: 5px;")
        col_btns.addWidget(lbl_ops_title)

        self.btn_infer = QPushButton("推理提示词")
        self.btn_infer.setObjectName("BtnInfer")
        self.btn_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_infer.clicked.connect(lambda: self.main_window.handle_card_action("infer", self.index))

        self.btn_gen = QPushButton("重新生图")
        self.btn_gen.setObjectName("BtnGen")
        self.btn_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_gen.clicked.connect(lambda: self.main_window.handle_card_action("gen", self.index))

        self.btn_del = QPushButton("🗑️ 删除图片")
        self.btn_del.setObjectName("BtnDel")
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.clicked.connect(self.delete_current_image)

        self.btn_import = QPushButton("📥 导入图片")
        self.btn_import.setObjectName("BtnImport")
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.clicked.connect(self.import_images)

        self.btn_export = QPushButton("📤 导出图片")
        self.btn_export.setObjectName("BtnExport")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.clicked.connect(self.export_images)

        h_import_export = QHBoxLayout()
        h_import_export.addWidget(self.btn_import)
        h_import_export.addWidget(self.btn_export)

        self.lbl_status = QLabel("状态: 待处理")
        self.lbl_status.setStyleSheet("color: #666; font-size: 10px; margin-top: 10px;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        col_btns.addWidget(self.btn_infer)
        col_btns.addWidget(self.btn_gen)
        col_btns.addWidget(self.btn_del)
        col_btns.addLayout(h_import_export)
        col_btns.addWidget(self.lbl_status)
        col_btns.addStretch()

        self.main_layout.addLayout(col_btns)

    def on_cn_user_change(self):
        if self._is_translating:
            return
        self.sync_data()
        if self.translator_enabled:
            # 🌟 延长到 800 毫秒防抖，打字体验更丝滑
            self.debounce_timer.start(800)

    def perform_auto_translate(self):
        if self._is_translating:
            return
        text = self.input_cn.toPlainText().strip()
        if not text:
            return
        if not self.translator_enabled:
            self.input_en.setPlaceholderText("请先配置百度翻译API")
            return

        self._is_translating = True
        self.input_en.setPlaceholderText("翻译中...")

        # 中文框修改，固定使用 zh 到 en 的翻译
        thread = TranslateWorker(text, self.baidu_appid, self.baidu_secret, from_lang='zh')
        thread.translated.connect(self.on_translate_ready)
        thread.error.connect(self.on_translate_error)

        self._active_trans_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._cleanup_trans_thread(t))
        thread.start()

    def _cleanup_trans_thread(self, thread):
        try:
            _ = self.objectName()  # 探针：如果 C++ 对象已死，这里直接抛异常
            if thread in self._active_trans_threads:
                self._active_trans_threads.remove(thread)
                thread.deleteLater()
            if not self._active_trans_threads:
                self._is_translating = False
        except RuntimeError:
            thread.deleteLater()
        except Exception:
            pass

    def on_translate_ready(self, original_text, translated_text):
        try:
            _ = self.objectName()
            current_text = self.input_cn.toPlainText().strip()
            if current_text == original_text:
                # 阻塞信号，防止死循环触发 sync_data
                self.input_en.blockSignals(True)
                self.input_en.setPlainText(translated_text)
                self.input_en.blockSignals(False)
                self.sync_data()
        except RuntimeError:
            pass

    def on_translate_error(self, error_msg):
        try:
            _ = self.objectName()
            self.input_en.setPlaceholderText(f"翻译失败: {error_msg}")
        except RuntimeError:
            pass

    def _translate_en_text_async(self, text):
        # 英文框混杂中文时，使用 auto 智能语言检测
        thread = TranslateWorker(text, self.baidu_appid, self.baidu_secret, from_lang='auto')
        thread.translated.connect(self.on_en_translate_ready)
        thread.error.connect(self.on_en_translate_error)
        self._active_trans_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._cleanup_trans_thread(t))
        thread.start()

    def on_en_translate_ready(self, original_text, translated_text):
        try:
            _ = self.objectName()
            # 净化由于翻译产生的全角中文标点符号，防止影响 SD 解析
            translated_text = translated_text.replace('，', ', ').replace('。', '. ').replace('：', ':')
            translated_text = translated_text.replace('（', '(').replace('）', ')')

            current_text = self.input_en.toPlainText().strip()
            # 只有当用户没有在这期间大幅手动修改英文框时，才进行替换
            if current_text == original_text.strip():
                self.input_en.blockSignals(True)
                self.input_en.setPlainText(translated_text)
                self.input_en.blockSignals(False)
                self.sync_data()
        except RuntimeError:
            pass

    def on_en_translate_error(self, error_msg):
        try:
            _ = self.objectName()
            current_text = self.input_en.toPlainText().strip()
            # 如果翻译失败（比如断网），则退化到“正则表达式强行清理中文法”作为最终兜底
            self.input_en.blockSignals(True)
            self.input_en.setPlainText(self._strip_chinese(current_text))
            self.input_en.blockSignals(False)
            self.sync_data()
        except RuntimeError:
            pass

    def _strip_chinese(self, text):
        """🌟 强制清理兜底防线 + 幽灵提示词终极清理"""
        if not text:
            return text
        # 1. 替换常见中文标点为英文标点
        text = text.replace('，', ', ').replace('。', '. ').replace('！', '! ').replace('：', ': ')
        # 2. 暴力剔除纯汉字
        text = re.sub(r'[\u4e00-\u9fa5]+', '', text).strip()
        # 3. 绝杀幽灵残留：如果括号内只有冒号、数字或根本没任何有效英文字母（例如残留了数字或符号），直接连带括号一起删掉
        text = re.sub(r'\([^\w]*:?\d*\.?\d*\)', '', text)
        # 4. 暴力清理孤立的标点组合，比如 " , : " 或 ", , "
        text = re.sub(r'([,:])\s*([,:])+', r'\1', text)
        # 5. 清理连续产生的多余逗号
        text = re.sub(r'(,\s*){2,}', ', ', text)
        # 6. 清理首尾多余标点
        text = text.strip(' ,.:')
        return text

    def sync_data(self):
        """🌟 彻底解耦双轨制数据，告别拼接旧字段污染"""
        if self._is_translating:
            return
        cn = self.input_cn.toPlainText()
        en = self.input_en.toPlainText()

        # 全量同步，防止后续任何环节拿不到字段
        self.scene_data['prompt_zh'] = cn
        self.scene_data['prompt_zh_raw'] = cn
        self.scene_data['prompt_zh_display'] = cn
        self.scene_data['prompt_en_raw'] = en

        if cn or en:
            self.scene_data['prompt'] = f"[CN]: {cn}\n[EN]: {en}"
        else:
            self.scene_data['prompt'] = ""

    def sync_to_data(self):
        """🌟 兼容主界面 workspace 的同步调用"""
        self.sync_data()

    # 🌟 核心新增：增加 flash 动画参数，供瀑布流热更新调用
    def refresh_ui(self, flash=False):
        # 1. 梯级容错读取：优先读 raw，没有再读 display，最后尝试传统字段，彻底终结空白 Bug
        zh_text = self.scene_data.get('prompt_zh_raw', '')
        if not zh_text:
            zh_text = self.scene_data.get('prompt_zh_display', '')
        if not zh_text:
            zh_text = self.scene_data.get('prompt_zh', '')

        en_text = self.scene_data.get('prompt_en_raw', '')

        # 2. 兼容旧版本拼接数据的读取（保证加载老工程不丢失数据）
        if not en_text and not zh_text:
            raw = self.scene_data.get('prompt', '')
            if "[CN]:" in raw and "[EN]:" in raw:
                try:
                    parts = raw.split("[EN]:")
                    zh_text = parts[0].replace("[CN]:", "").strip()
                    en_text = parts[1].strip()
                except:
                    zh_text = raw
            else:
                if any(ord(c) > 127 for c in raw):
                    zh_text = raw
                else:
                    en_text = raw

        # 动态翻译AI混杂的中文字符
        has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', en_text))

        if has_chinese:
            if self.translator_enabled:
                self._translate_en_text_async(en_text)
            else:
                en_text = self._strip_chinese(en_text)

        self.input_cn.blockSignals(True)
        self.input_en.blockSignals(True)
        self.input_cn.setPlainText(zh_text)
        self.input_en.setPlainText(en_text)
        self.input_cn.blockSignals(False)
        self.input_en.blockSignals(False)

        roles = self.scene_data.get('roles', [])
        current_roles_state = list(roles)
        if not hasattr(self, '_current_roles_state') or self._current_roles_state != current_roles_state:
            self._current_roles_state = current_roles_state
            while self.role_layout.count():
                item = self.role_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if roles:
                for r in roles:
                    lbl = QLabel(r)
                    lbl.setProperty("role_tag", "true")
                    self.role_layout.addWidget(lbl)

        self._refresh_images_async()

        imgs = self.scene_data.get('images', [])
        if imgs:
            self.lbl_status.setText("已完成")
            self.lbl_status.setStyleSheet("color: #4caf50; font-size: 12px; font-weight:bold; margin-top: 10px;")
        else:
            if en_text:
                self.lbl_status.setText("待生图")
                self.lbl_status.setStyleSheet("color: #ff9800; font-size: 12px; margin-top: 10px;")
            else:
                self.lbl_status.setText("待推理")
                self.lbl_status.setStyleSheet("color: #666; font-size: 12px; margin-top: 10px;")

        # 🌟 当被批处理更新触发时，执行视觉反馈动画
        if flash:
            self.highlight_update()

    # 🌟 核心新增：呼吸灯特效函数
    def highlight_update(self):
        """为了实现“瀑布流”的视觉效果，增加文本框的呼吸闪烁"""
        highlight_style = """
            QTextEdit { 
                background-color: #0b2b1a; 
                border: 1px solid #4caf50; 
                color: #fff; 
                border-radius: 4px; 
                padding: 5px; 
                font-family: Consolas, "Microsoft YaHei"; 
                font-size: 15px; 
            }
        """
        self.input_cn.setStyleSheet(highlight_style)
        self.input_en.setStyleSheet(highlight_style)
        # 600毫秒后恢复原状，不影响输入
        QTimer.singleShot(600, self.restore_text_style)

    # 🌟 核心新增：恢复默认样式的函数
    def restore_text_style(self):
        try:
            _ = self.objectName()
            # 清空自身的局部样式，完美回落到父级 SceneCard 的全局默认样式
            self.input_cn.setStyleSheet("")
            self.input_en.setStyleSheet("")
        except RuntimeError:
            pass

    def _refresh_images_async(self):
        images = self.scene_data.get('images', [])
        sel_idx = self.scene_data.get('selected_image_index', -1)

        if not images:
            self.scene_data['selected_image_index'] = -1
            sel_idx = -1
        elif sel_idx >= len(images):
            sel_idx = len(images) - 1
            self.scene_data['selected_image_index'] = sel_idx
        elif sel_idx < 0 and images:
            sel_idx = 0
            self.scene_data['selected_image_index'] = 0

        current_state = (list(images), sel_idx)
        if hasattr(self, '_current_image_state') and self._current_image_state == current_state:
            return
        self._current_image_state = current_state

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._update_preview()

        col_count = 1
        thumb_size = QSize(60, 60)
        need_async_load = False

        for i, path in enumerate(images):
            if not os.path.exists(path):
                continue

            thumb_lbl = ClickableLabel(click_callback=lambda idx=i: self.set_image_index(idx))
            thumb_lbl.setFixedSize(60, 60)
            thumb_lbl.setProperty("thumb", "true")
            if i == sel_idx:
                thumb_lbl.setProperty("thumb_selected", "true")
            else:
                thumb_lbl.setProperty("thumb_selected", "false")
            thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_lbl.setCursor(Qt.CursorShape.PointingHandCursor)

            thumb_lbl.right_clicked.connect(lambda pos, idx=i: self.show_image_context_menu(pos, idx))

            cache_key = f"{path}@{thumb_size.width()}x{thumb_size.height()}"
            if cache_key in self._pixmap_cache:
                thumb_lbl.setPixmap(self._pixmap_cache[cache_key])
            else:
                thumb_lbl.setStyleSheet("background-color: #333; border: 1px solid #555;")
                thumb_lbl.setText("")
                need_async_load = True

            row = i // col_count
            col = i % col_count
            self.grid_layout.addWidget(thumb_lbl, row, col)

        if need_async_load and not self._loaded:
            self.load_images_async()

    def showEvent(self, event):
        super().showEvent(event)
        if self.lazy_load and not self._loaded:
            self._load_timer.start(50)

    def _do_load(self):
        if self._loaded:
            return
        self._loaded = True
        self.load_images_async()

    def load_images_async(self):
        images = self.scene_data.get('images', [])
        if not images:
            self.images_loaded.emit(self.index)
            return

        thumb_size = QSize(60, 60)
        all_cached = True
        pixmaps = []
        for path in images:
            cache_key = f"{path}@{thumb_size.width()}x{thumb_size.height()}"
            if cache_key in self._pixmap_cache:
                pixmaps.append(self._pixmap_cache[cache_key])
            else:
                all_cached = False
                break

        if all_cached:
            self.images_loaded.emit(self.index)
            return

        worker = ThumbnailLoadWorker(self.index, images, thumb_size)
        worker.thumb_loaded.connect(self.on_thumb_loaded)
        worker.all_loaded.connect(self.on_all_thumbs_loaded)

        self._active_img_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_img_worker(w))
        worker.start()

    def _cleanup_img_worker(self, worker):
        try:
            _ = self.objectName()
            if worker in self._active_img_workers:
                self._active_img_workers.remove(worker)
                worker.deleteLater()
        except RuntimeError:
            worker.deleteLater()
        except Exception:
            pass

    @pyqtSlot(int, bytes, str)
    def on_thumb_loaded(self, idx, img_data, path):
        try:
            _ = self.objectName()
        except RuntimeError:
            return

        image = QImage()
        if not image.loadFromData(img_data):
            return

        thumb_size = QSize(60, 60)
        image = image.scaled(thumb_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pix = QPixmap.fromImage(image)

        images = self.scene_data.get('images', [])
        if idx < len(images) and images[idx] == path:
            cache_key = f"{path}@{thumb_size.width()}x{thumb_size.height()}"
            self._pixmap_cache[cache_key] = pix

        thumb_labels = []
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLabel):
                thumb_labels.append(item.widget())
        if idx < len(thumb_labels):
            lbl = thumb_labels[idx]
            lbl.setPixmap(pix)
            lbl.setStyleSheet("")

    @pyqtSlot()
    def on_all_thumbs_loaded(self):
        try:
            _ = self.objectName()
        except RuntimeError:
            return
        self._update_preview()
        self.images_loaded.emit(self.index)

    def _update_preview(self):
        images = self.scene_data.get('images', [])
        sel_idx = self.scene_data.get('selected_image_index', -1)

        if not images:
            self.scene_data['selected_image_index'] = -1
            sel_idx = -1
        elif sel_idx >= len(images):
            sel_idx = len(images) - 1
            self.scene_data['selected_image_index'] = sel_idx
        elif sel_idx < 0 and images:
            sel_idx = 0
            self.scene_data['selected_image_index'] = 0

        if images and sel_idx >= 0:
            path = images[sel_idx]

            # 🌟 核心修复 2：UI 渲染前的二次防御
            if not os.path.exists(path):
                try:
                    # 尝试动态去当前工程下的 assets 找找看
                    project_dir = os.path.dirname(os.path.abspath(self.main_window.curr_path))
                    alt_path = os.path.join(project_dir, "assets", os.path.basename(path))
                    if os.path.exists(alt_path):
                        path = alt_path
                        self.scene_data['images'][sel_idx] = path  # 顺手把内存里的错误路径纠正
                    else:
                        raise FileNotFoundError("Image truly lost")
                except Exception:
                    self.preview_lbl.setFixedSize(120, 80)
                    self.preview_lbl.clear()
                    self.preview_lbl.setText("IMAGE LOST")
                    self._last_preview_path = None
                    self._cached_preview_pixmap = None
                    return

            if path == self._last_preview_path and self._cached_preview_pixmap is not None:
                pix = self._cached_preview_pixmap
                self.preview_lbl.setPixmap(pix)
                self.preview_lbl.setFixedSize(pix.size())
                return

            reader = QImageReader(path)
            orig_size = reader.size()
            if orig_size.isValid():
                max_h = 240
                aspect = orig_size.width() / orig_size.height()
                new_h = min(orig_size.height(), max_h)
                new_w = int(new_h * aspect)
                reader.setScaledSize(QSize(new_w, new_h))
                image = reader.read()
                if not image.isNull():
                    pix = QPixmap.fromImage(image)
                    self._cached_preview_pixmap = pix
                    self._last_preview_path = path
                    self.preview_lbl.setFixedSize(new_w, new_h)
                    self.preview_lbl.setPixmap(pix)
                    self.preview_lbl.setText("")
                else:
                    self._load_fallback_pixmap(path, max_h)
            else:
                self._load_fallback_pixmap(path, max_h)
        else:
            self.preview_lbl.setFixedSize(120, 80)
            self.preview_lbl.clear()
            self.preview_lbl.setText("NO IMAGE")
            self._last_preview_path = None
            self._cached_preview_pixmap = None

    def _load_fallback_pixmap(self, path, max_h):
        """辅助方法：抽取原有 fallback 加载逻辑保持代码整洁"""
        pix = QPixmap(path)
        if pix.height() > 0:
            aspect = pix.width() / pix.height()
            new_h = min(pix.height(), max_h)
            new_w = int(new_h * aspect)
            scaled_pix = pix.scaled(new_w, new_h,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            self._cached_preview_pixmap = scaled_pix
            self._last_preview_path = path
            self.preview_lbl.setFixedSize(new_w, new_h)
            self.preview_lbl.setPixmap(scaled_pix)
            self.preview_lbl.setText("")
        else:
            self.preview_lbl.setFixedSize(120, 80)
            self.preview_lbl.clear()
            self.preview_lbl.setText("NO IMAGE")

    def import_images(self):
        if not self.main_window.curr_path:
            QMessageBox.warning(self, "未保存", "请先保存项目后再导入图片。")
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要导入的图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not file_paths:
            return

        project_dir = os.path.dirname(self.main_window.curr_path)
        assets_dir = os.path.join(project_dir, "assets")
        os.makedirs(assets_dir, exist_ok=True)

        imported_paths = []
        for src_path in file_paths:
            base_name = os.path.basename(src_path)
            name, ext = os.path.splitext(base_name)
            dest_path = os.path.join(assets_dir, base_name)
            counter = 1
            while os.path.exists(dest_path):
                new_name = f"{name}_{counter}{ext}"
                dest_path = os.path.join(assets_dir, new_name)
                counter += 1
            try:
                shutil.copy2(src_path, dest_path)
                imported_paths.append(dest_path)
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"复制文件失败: {str(e)}")

        if imported_paths:
            self.scene_data.setdefault('images', []).extend(imported_paths)
            self.scene_data['selected_image_index'] = len(self.scene_data['images']) - 1
            self.refresh_ui()
            self.main_window.save_proj(silent=True)
            self.images_loaded.emit(self.index)
            self.main_window.studio_page.log(f"镜头 {self.index} 已导入 {len(imported_paths)} 张图片")

    def export_images(self):
        images = self.scene_data.get('images', [])
        if not images:
            QMessageBox.information(self, "提示", "当前镜头没有图片可导出。")
            return

        export_dir = QFileDialog.getExistingDirectory(self, "选择导出文件夹")
        if not export_dir:
            return

        exported = 0
        for src_path in images:
            if not os.path.exists(src_path):
                continue
            base_name = os.path.basename(src_path)
            dest_path = os.path.join(export_dir, base_name)
            counter = 1
            while os.path.exists(dest_path):
                name, ext = os.path.splitext(base_name)
                new_name = f"{name}_{counter}{ext}"
                dest_path = os.path.join(export_dir, new_name)
                counter += 1
            try:
                shutil.copy2(src_path, dest_path)
                exported += 1
            except Exception as e:
                QMessageBox.warning(self, "导出失败", f"复制文件失败: {str(e)}")

        QMessageBox.information(self, "导出完成", f"成功导出 {exported} 张图片到：{export_dir}")
        self.main_window.studio_page.log(f"镜头 {self.index} 已导出 {exported} 张图片")

    def set_image_index(self, idx):
        self.scene_data['selected_image_index'] = idx
        self._refresh_images_async()

    def delete_current_image(self):
        imgs = self.scene_data.get('images', [])
        curr = self.scene_data.get('selected_image_index', -1)
        if 0 <= curr < len(imgs):
            img_path = imgs.pop(curr)  # 弹出并获取路径

            # 🌟 新增：同时从硬盘文件夹中物理删除该图片
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except Exception as e:
                    print(f"物理删除图片失败，可能文件被占用: {e}")

            self.scene_data['selected_image_index'] = max(0, curr - 1) if imgs else -1
            self.refresh_ui()

    def on_preview_click(self):
        imgs = self.scene_data.get('images', [])
        curr = self.scene_data.get('selected_image_index', -1)
        if 0 <= curr < len(imgs):
            QDesktopServices.openUrl(QUrl.fromLocalFile(imgs[curr]))

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def show_image_context_menu(self, global_pos, img_idx):
        imgs = self.scene_data.get('images', [])
        if img_idx < 0 or img_idx >= len(imgs):
            return

        img_path = imgs[img_idx]

        # 创建菜单
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; }
            QMenu::item { padding: 8px 20px; }
            QMenu::item:selected { background-color: #1a73e8; }
        """)

        action_open = menu.addAction("📁 打开图片所在位置")
        action_del = menu.addAction("🗑️ 删除此图片")

        # 显示菜单并获取用户的选择
        action = menu.exec(global_pos)

        if action == action_open:
            if os.path.exists(img_path):
                # 🌟 调用 Windows 底层指令，打开文件夹并高亮选中该图片
                os.system(f'explorer /select,"{os.path.normpath(img_path)}"')


        elif action == action_del:

            # 如果删除的是当前正在预览的大图，直接调用现成的删除逻辑

            if img_idx == self.scene_data.get('selected_image_index', -1):

                self.delete_current_image()

            else:

                # 如果删除的是其他备选小图，获取路径并移除

                img_path_to_del = imgs.pop(img_idx)

                # 🌟 新增：同时从硬盘文件夹中物理删除该图片

                if img_path_to_del and os.path.exists(img_path_to_del):

                    try:

                        os.remove(img_path_to_del)

                    except Exception as e:

                        print(f"物理删除图片失败，可能文件被占用: {e}")

                curr = self.scene_data.get('selected_image_index', -1)

                # 修正索引防越界

                if img_idx < curr:
                    self.scene_data['selected_image_index'] = curr - 1

                self.refresh_ui()