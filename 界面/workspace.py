import json
import os
import datetime
import re  # 🌟 新增：用于精准解析带有 ID 的智能文本，防止错位
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QSplitter, QFrame, QTextEdit, QMessageBox,
    QFileDialog, QSizePolicy, QMenu, QComboBox, QSpinBox  # 🌟 增加 QSpinBox 导入
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from 界面.scene_card import SceneCard
from 界面.project_role_dialog import ProjectRoleDialog


class StudioPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.scene_widgets = {}

        self.stats_timer = QTimer(self)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.timeout.connect(self._do_update_stats)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== 顶部控制区 ==========
        top_frame = QFrame()
        top_frame.setFixedHeight(70)
        top_frame.setStyleSheet("background: #252526; border-bottom: 1px solid #444;")
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(15, 10, 15, 10)
        top_layout.setSpacing(12)

        btn_style_base = """
            QPushButton {{
                background: {bg}; 
                color: white; 
                border: none; 
                padding: 6px 12px; 
                border-radius: 4px;
                font-weight: bold;
                min-height: 20px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {pressed}; }}
        """

        lbl_title = QLabel("绘图工坊")
        lbl_title.setStyleSheet("color: #4fc3f7; font-size: 18px; font-weight: bold; margin-right: 10px;")
        top_layout.addWidget(lbl_title)

        btn_role = QPushButton("🎭 角色设定")
        btn_role.clicked.connect(self.open_role_dialog)
        btn_role.setStyleSheet(btn_style_base.format(bg="#9c27b0", hover="#ba68c8", pressed="#7b1fa2"))
        top_layout.addWidget(btn_role)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("border: 1px solid #444;")
        top_layout.addWidget(sep1)

        lbl_wf = QLabel("🔌 生图配置:")
        lbl_wf.setStyleSheet("color: #ccc; font-weight: bold;")
        top_layout.addWidget(lbl_wf)

        self.combo_workflow = QComboBox()
        self.combo_workflow.setToolTip("选择要使用的节点/工作流组合")
        self.combo_workflow.setMinimumWidth(180)
        self.combo_workflow.setMinimumHeight(32)
        self.combo_workflow.setStyleSheet("""
            QComboBox { background: #333; color: white; border: 1px solid #555; padding: 4px; border-radius: 4px; }
            QComboBox::drop-down { border: none; background: transparent; }
            QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 5px solid #ccc; margin-right: 5px; }
        """)
        self.combo_workflow.currentIndexChanged.connect(self.on_workflow_changed)
        top_layout.addWidget(self.combo_workflow)

        btn_refresh_wf = QPushButton("🔄")
        btn_refresh_wf.setFixedSize(35, 35)
        btn_refresh_wf.setToolTip("刷新配置列表")
        btn_refresh_wf.clicked.connect(self.load_workflows_to_combo)
        btn_refresh_wf.setStyleSheet(
            "QPushButton { background: #444; color: white; border: 1px solid #555; border-radius: 4px; } QPushButton:hover { background: #555; }")
        top_layout.addWidget(btn_refresh_wf)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("border: 1px solid #444;")
        top_layout.addWidget(sep2)

        # 🌟 完美插入：推理并发控制区
        lbl_thread = QLabel("推理并发:")
        lbl_thread.setStyleSheet("color: #ccc; font-weight: bold;")
        top_layout.addWidget(lbl_thread)

        self.spin_thread = QSpinBox()
        self.spin_thread.setRange(1, 20)
        self.spin_thread.setValue(3)  # 默认3并发
        self.spin_thread.setToolTip("设置同时请求AI接口的线程数。\n提示: 免费API建议1-3，付费不限流API可调大。")
        self.spin_thread.setStyleSheet("""
            QSpinBox { background: #333; color: white; border: 1px solid #555; padding: 4px; border-radius: 4px; min-height: 22px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 16px; }
        """)
        self.spin_thread.valueChanged.connect(self.on_thread_count_changed)
        top_layout.addWidget(self.spin_thread)

        style_blue = btn_style_base.format(bg="#1a73e8", hover="#4285f4", pressed="#0d47a1")

        btn_infer_all = QPushButton("🧠 全局分镜推理")
        btn_infer_all.clicked.connect(self.main_window.run_infer_all)
        btn_infer_all.setStyleSheet(style_blue)
        top_layout.addWidget(btn_infer_all)

        btn_gen_all = QPushButton("🎨 全局批量生图")
        btn_gen_all.clicked.connect(lambda: self.main_window.run_gen_all(skip=False))
        btn_gen_all.setStyleSheet(style_blue)
        top_layout.addWidget(btn_gen_all)

        btn_gen_skip = QPushButton("🎨 仅生成缺失图")
        btn_gen_skip.clicked.connect(lambda: self.main_window.run_gen_all(skip=True))
        btn_gen_skip.setStyleSheet(style_blue)
        top_layout.addWidget(btn_gen_skip)

        style_red = btn_style_base.format(bg="#c62828", hover="#e53935", pressed="#b71c1c")

        btn_clear_prompts = QPushButton("🧹 清空提示词")
        btn_clear_prompts.clicked.connect(self.action_clear_prompts)
        btn_clear_prompts.setStyleSheet(style_red)
        top_layout.addWidget(btn_clear_prompts)

        btn_stop = QPushButton("🛑 停止任务")
        btn_stop.clicked.connect(self.main_window.stop_all_tasks)
        btn_stop.setStyleSheet(style_red)
        top_layout.addWidget(btn_stop)

        style_green = btn_style_base.format(bg="#2e7d32", hover="#43a047", pressed="#1b5e20")

        btn_export = QPushButton("🚀 导出剪映草稿")
        btn_export.clicked.connect(self.main_window.run_exp)
        btn_export.setStyleSheet(style_green)
        top_layout.addWidget(btn_export)

        style_gray = btn_style_base.format(bg="#3a3a3a", hover="#4a4a4a", pressed="#252526")

        btn_text_menu = QPushButton("📄 文案管理 ▼")
        text_menu = QMenu()
        text_menu.setStyleSheet(
            "QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; } QMenu::item { padding: 8px 20px; } QMenu::item:selected { background-color: #1a73e8; }")
        text_menu.addAction("📥 导入文案 (覆盖扩容)", self.import_texts)
        text_menu.addAction("📤 导出文案 (防错位备份)", self.export_texts)
        btn_text_menu.setMenu(text_menu)
        btn_text_menu.setStyleSheet(style_gray)
        top_layout.addWidget(btn_text_menu)

        btn_prompt_menu = QPushButton("🎨 提示词管理 ▼")
        prompt_menu = QMenu()
        prompt_menu.setStyleSheet(
            "QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; } QMenu::item { padding: 8px 20px; } QMenu::item:selected { background-color: #1a73e8; }")
        prompt_menu.addAction("📥 导入提示词 (覆盖扩容)", self.import_prompts)
        prompt_menu.addAction("📤 导出提示词 (防错位备份)", self.export_prompts)
        btn_prompt_menu.setMenu(prompt_menu)
        btn_prompt_menu.setStyleSheet(style_gray)
        top_layout.addWidget(btn_prompt_menu)

        top_layout.addStretch()
        main_layout.addWidget(top_frame)

        # ========== 主内容区：只保留分镜卡片区 ==========
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #444; width: 2px; }")

        scene_widget = QWidget()
        scene_layout = QVBoxLayout(scene_widget)
        scene_layout.setContentsMargins(5, 5, 5, 5)

        scene_tools = QHBoxLayout()
        lbl_scene = QLabel("🎬 分镜列表")
        lbl_scene.setStyleSheet("color: #ddd; font-weight: bold; font-size: 14px;")

        self.lbl_stats = QLabel("统计: 0 镜头")
        self.lbl_stats.setStyleSheet("color: #888; font-size: 12px; margin-left: 10px;")

        scene_tools.addWidget(lbl_scene)
        scene_tools.addWidget(self.lbl_stats)
        scene_tools.addStretch()
        scene_layout.addLayout(scene_tools)

        self.scene_scroll = QScrollArea()
        self.scene_scroll.setWidgetResizable(True)
        self.scene_scroll.setStyleSheet("background: #1e1e1e; border: none;")
        self.scene_container = QWidget()
        self.cards_layout = QVBoxLayout(self.scene_container)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setSpacing(10)
        self.scene_scroll.setWidget(self.scene_container)
        scene_layout.addWidget(self.scene_scroll)

        splitter.addWidget(scene_widget)
        main_layout.addWidget(splitter, 1)

        # ========== 底部日志区 ==========
        log_frame = QFrame()
        log_frame.setFixedHeight(150)
        log_frame.setStyleSheet("background: #1e1e1e; border-top: 1px solid #444;")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(5, 5, 5, 5)

        lbl_log = QLabel("📋 运行日志")
        lbl_log.setStyleSheet("color: #aaa; font-weight: bold;")
        log_layout.addWidget(lbl_log)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("""
            QTextEdit { 
                background: #1e1e1e; 
                color: #e0e0e0;
                font-family: Consolas; 
                border: 1px solid #444; 
                border-radius: 4px; 
            }
        """)
        log_layout.addWidget(self.log_view)

        main_layout.addWidget(log_frame)

    # --- 功能实现 ---

    def showEvent(self, event):
        super().showEvent(event)
        self.load_workflows_to_combo()

        # 🌟 优化：界面显示时，从全局配置文件中读取并发数设置
        import configparser
        from 配置.app_config import CONFIG_FILE

        thread_val = 3  # 默认值
        try:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')
            # 尝试获取全局设置，如果没有则使用 3
            thread_val = int(cfg['DEFAULT'].get('infer_thread_count', 3))
        except Exception:
            pass

        self.spin_thread.blockSignals(True)
        self.spin_thread.setValue(thread_val)
        self.spin_thread.blockSignals(False)

    # 🌟 优化：捕获并发数变化并存入全局配置文件，保证多项目通用
    def on_thread_count_changed(self, val):
        import configparser
        from 配置.app_config import CONFIG_FILE
        import os

        cfg = configparser.ConfigParser()
        try:
            if os.path.exists(CONFIG_FILE):
                try:
                    cfg.read(CONFIG_FILE, encoding='utf-8')
                except UnicodeDecodeError:
                    cfg.read(CONFIG_FILE, encoding='gbk')
        except Exception:
            pass

        if 'DEFAULT' not in cfg:
            cfg['DEFAULT'] = {}

        cfg['DEFAULT']['infer_thread_count'] = str(val)

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                cfg.write(f)
        except Exception as e:
            self.log(f"⚠️ 全局并发设置保存失败: {e}", color="#ffaa00")

    def load_workflows_to_combo(self):
        import configparser
        from 配置.app_config import CONFIG_FILE

        self.combo_workflow.blockSignals(True)
        self.combo_workflow.clear()
        self.combo_workflow.addItem("🌐 全局默认 (自动负载均衡)", "default")

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

        for item in self.node_list:
            name = item.get('name', '未命名')
            self.combo_workflow.addItem(f"🔌 {name}", item)

        current_selection = self.main_window.data.get('selected_workflow_name', 'default')
        index = 0
        if current_selection != 'default':
            for i in range(self.combo_workflow.count()):
                data = self.combo_workflow.itemData(i)
                if data and isinstance(data, dict) and data.get('name') == current_selection:
                    index = i
                    break
        self.combo_workflow.setCurrentIndex(index)
        self.combo_workflow.blockSignals(False)

    def on_workflow_changed(self, index):
        data = self.combo_workflow.itemData(index)
        if data == "default" or data is None:
            self.main_window.data['selected_workflow_name'] = 'default'
            if 'workflow_file' in self.main_window.data: del self.main_window.data['workflow_file']
            if 'target_node_url' in self.main_window.data: del self.main_window.data['target_node_url']
        else:
            self.main_window.data['selected_workflow_name'] = data.get('name')
            self.main_window.data['workflow_file'] = data.get('workflow')
            self.main_window.data['target_node_url'] = data.get('url')

        self.main_window.mark_modified()
        self.log(f"✅ 已切换生图配置: {self.combo_workflow.currentText()}")

    def open_role_dialog(self):
        dlg = ProjectRoleDialog(self.main_window, self)
        dlg.exec()

    def log(self, text, color=None):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if not color:
            if "❌" in text or "Error" in text or "失败" in text:
                color = "#ff5555"
            elif "✅" in text or "成功" in text or "完成" in text:
                color = "#55ff55"
            elif "🚀" in text or "开始" in text:
                color = "#55ffff"
            elif "⚠️" in text:
                color = "#ffaa00"
            else:
                color = "#cccccc"

        html_msg = f'<span style="color:#888;">[{timestamp}]</span> <span style="color:{color};">{text}</span>'
        self.log_view.append(html_msg)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def action_clear_prompts(self):
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要彻底清空所有镜头的提示词吗？\n注意：此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            scenes = self.main_window.data.get('scenes', [])
            for s in scenes:
                s['prompt'] = ""
                if 'prompt_zh' in s: s['prompt_zh'] = ""
                if 'prompt_zh_raw' in s: s['prompt_zh_raw'] = ""
                if 'prompt_en_raw' in s: s['prompt_en_raw'] = ""
                if 'prompt_zh_display' in s: s['prompt_zh_display'] = ""
                if 'roles' in s: s['roles'] = []
                if 'role_desc_list' in s: s['role_desc_list'] = []

            self.main_window.mark_modified()
            try:
                self.main_window.save_proj(silent=True)
            except Exception:
                pass

            for idx, card in self.scene_widgets.items():
                try:
                    card.refresh_ui()
                except Exception:
                    pass

            self.log("🧹 所有镜头的提示词已彻底清空！", color="#ff5555")

    # ================= 高性能分批加载 + 精准刷新逻辑 =================

    def refresh_scene_list(self):
        self.v_scroll_val = self.scene_scroll.verticalScrollBar().value()
        self.batch_index = float('inf')

        self.scene_scroll.setUpdatesEnabled(False)
        try:
            while self.cards_layout.count():
                item = self.cards_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.scene_widgets.clear()
        finally:
            self.scene_scroll.setUpdatesEnabled(True)

        self.scenes = self.main_window.data.get('scenes', [])
        self.batch_index = 0
        self.batch_size = 4
        self.update_stats()
        self._batch_add_cards()

    def _batch_add_cards(self):
        if not hasattr(self, 'batch_index') or self.batch_index >= len(self.scenes):
            if hasattr(self, 'v_scroll_val'):
                self.scene_scroll.verticalScrollBar().setValue(self.v_scroll_val)
            return

        end = min(self.batch_index + self.batch_size, len(self.scenes))
        for i in range(self.batch_index, end):
            s = self.scenes[i]
            try:
                card = SceneCard(s, self.main_window, lazy_load=True)
            except TypeError:
                card = SceneCard(s, self.main_window)

            self.cards_layout.addWidget(card)
            self.scene_widgets[i] = card

        self.batch_index = end

        if self.batch_index < len(self.scenes):
            QTimer.singleShot(50, self._batch_add_cards)

    def batch_update_cards(self, list_indices):
        """🌟 核心修复：坚决不能在这里使用 setUpdatesEnabled(False)，这会导致局部刷新被彻底挂起！"""
        scenes = self.main_window.data.get('scenes', [])
        for list_index in list_indices:
            card = self.scene_widgets.get(list_index)
            if card:
                try:
                    _ = card.objectName()
                except RuntimeError:
                    continue

                try:
                    # 🌟 核心防空数据补丁：确保UI刷新前，卡片绑定的是内存中最热乎的数据字典！
                    if list_index < len(scenes):
                        card.scene_data = scenes[list_index]

                    # 触发带有呼吸灯视觉反馈的渲染更新
                    card.refresh_ui(flash=True)
                except Exception as e:
                    print(f"卡片渲染异常拦截: {e}")

        self.update_stats()

    def update_scene_card(self, list_index):
        scenes = self.main_window.data.get('scenes', [])
        if list_index < 0 or list_index >= len(scenes): return

        card = self.scene_widgets.get(list_index)
        if card:
            try:
                _ = card.objectName()
            except RuntimeError:
                return

            try:
                if list_index < len(scenes):
                    card.scene_data = scenes[list_index]
                # 针对单个用户操作，不启用闪烁特效
                card.refresh_ui()
            except Exception as e:
                pass

        self.update_stats()

    def update_stats(self, scenes=None):
        self.stats_timer.start(50)

    def _do_update_stats(self):
        try:
            scenes = self.main_window.data.get('scenes', [])
            total = len(scenes)
            has_img = sum(1 for s in scenes if s.get('images'))
            self.lbl_stats.setText(f"总计: {total} 镜头 | 已有图: {has_img}")
        except Exception:
            pass

    def sync_data(self):
        """
        🌟 核心防空数据补丁：废弃全局强制抓取 UI 文本的逻辑！
        原因：SceneCard 内部的 input_cn.textChanged 信号已经实时同步了用户的手动修改。
        在这里全局盲目遍历抓取，极易将“后台刚更新、但 UI 还没来得及渲染的旧空文本”反向覆写回内存，导致数据清空！
        """
        pass
    # =================================================================

    # ========== 文案导入导出 (🌟 优化版：防错位 + 自动扩容不丢数据) ==========
    def export_texts(self):
        scenes = self.main_window.data.get('scenes', [])
        if not scenes: return QMessageBox.information(self, "提示", "没有分镜数据可导出。")
        path, selected_filter = QFileDialog.getSaveFileName(self, "导出文案", "texts_backup",
                                                            "JSON 文件 (*.json);;文本文件 (*.txt)")
        if not path: return
        if '.' not in os.path.basename(path):
            path += '.json' if "JSON" in selected_filter else '.txt'

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.json':
                export_data = [{'index': s['index'], 'text': s['text']} for s in scenes]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
            elif ext == '.txt':
                with open(path, 'w', encoding='utf-8') as f:
                    for s in scenes:
                        # 🌟 关键优化：在导出的 TXT 前面加上唯一 ID 标识，防止重导时错位
                        f.write(f"[ID:{s['index']}] " + s['text'].replace('\n', ' ').replace('\r', '') + '\n')
            self.log(f"✅ 文案已导出到：{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def import_texts(self):
        scenes = self.main_window.data.get('scenes', [])
        if not scenes: return QMessageBox.warning(self, "提示", "当前项目没有分镜，请先创建分镜。")
        path, _ = QFileDialog.getOpenFileName(self, "导入文案", "", "JSON 文件 (*.json);;文本文件 (*.txt)")
        if not path: return
        ext = os.path.splitext(path)[1].lower()

        try:
            data_map = {}  # {str(index): content}

            if ext == '.json':
                with open(path, 'r', encoding='utf-8') as f:
                    imported = json.load(f)
                if isinstance(imported, list) and len(imported) > 0 and isinstance(imported[0], dict):
                    data_map = {str(item['index']): item.get('text', '') for item in imported if 'index' in item}
                elif isinstance(imported, list):
                    # 兼容纯列表 JSON（按最大可能构建字典）
                    for i, txt in enumerate(imported):
                        idx_str = str(scenes[i]['index']) if i < len(scenes) else str(
                            (scenes[-1]['index'] if scenes else 0) + (i - len(scenes) + 1))
                        data_map[idx_str] = str(txt)

            elif ext == '.txt':
                with open(path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                is_smart_mode = any(re.match(r'^\[ID:(.*?)\]', line) for line in lines[:5])

                if is_smart_mode:
                    for line in lines:
                        match = re.match(r'^\[ID:(.*?)\]\s*(.*)', line)
                        if match:
                            data_map[str(match.group(1)).strip()] = match.group(2).strip()
                else:
                    # 兼容旧版纯文本顺序匹配，若文本超出镜头数也能生成虚假 index
                    for i, line in enumerate(lines):
                        idx_str = str(scenes[i]['index']) if i < len(scenes) else str(
                            (scenes[-1]['index'] if scenes else 0) + (i - len(scenes) + 1))
                        data_map[idx_str] = line

            # 🌟 核心：执行精准替换与自动扩容
            updated_count = 0
            existing_indices = set(str(s['index']) for s in scenes)
            max_idx = max([s['index'] for s in scenes]) if scenes else 0

            for s in scenes:
                s_idx = str(s['index'])
                if s_idx in data_map:
                    s['text'] = data_map[s_idx]
                    updated_count += 1

            # 自动扩容：处理多出来的105条数据（新增空白分镜承载）
            new_added_count = 0
            for k, v in data_map.items():
                if k not in existing_indices:
                    try:
                        new_idx = int(k)
                    except ValueError:
                        max_idx += 1
                        new_idx = max_idx

                    scenes.append({
                        "index": new_idx,
                        "duration": 2.0,
                        "text": v,
                        "sub_ids": [new_idx],
                        "prompt": "",
                        "status": "等待处理",
                        "images": [],
                        "selected_image_index": -1,
                        "roles": []
                    })
                    new_added_count += 1
                    max_idx = max(max_idx, new_idx)

            if new_added_count > 0:
                scenes.sort(key=lambda x: x['index'])

            self.main_window.mark_modified()
            self.main_window.save_proj(silent=True)
            self.refresh_scene_list()

            msg = f"✅ 成功更新了 {updated_count} 个现有镜头的文案！"
            if new_added_count > 0:
                msg += f"\n\n🔥 自动扩容：检测到多出 {new_added_count} 条文案，已为您自动创建新卡片承载，数据零丢失！"

            QMessageBox.information(self, "导入完成", msg)
            self.log(f"✅ 文案智能导入完成 (更新:{updated_count}, 扩容:{new_added_count})")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    # ========== 提示词导入导出 (🌟 优化版：防错位 + 角色替换 + 自动扩容) ==========
    def export_prompts(self):
        scenes = self.main_window.data.get('scenes', [])
        if not scenes: return QMessageBox.information(self, "提示", "没有分镜数据可导出。")
        path, selected_filter = QFileDialog.getSaveFileName(self, "导出提示词", "prompts_backup",
                                                            "JSON 文件 (*.json);;文本文件 (*.txt)")
        if not path: return
        if '.' not in os.path.basename(path):
            path += '.json' if "JSON" in selected_filter else '.txt'

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.json':
                export_data = [{'index': s['index'], 'prompt': s.get('prompt', '')} for s in scenes]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
            elif ext == '.txt':
                with open(path, 'w', encoding='utf-8') as f:
                    for s in scenes:
                        # 🌟 关键优化：加入 ID 锚点
                        f.write(f"[ID:{s['index']}] " + s.get('prompt', '').replace('\n', ' ').replace('\r', '') + '\n')
            self.log(f"✅ 提示词已导出到：{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def import_prompts(self):
        scenes = self.main_window.data.get('scenes', [])
        if not scenes:
            QMessageBox.warning(self, "提示", "当前项目没有分镜，请先创建分镜。")
            return

        path, _ = QFileDialog.getOpenFileName(self, "导入提示词", "", "JSON 文件 (*.json);;文本文件 (*.txt)")
        if not path: return

        ext = os.path.splitext(path)[1].lower()
        project_roles = self.main_window.data.get('role_cards', [])

        def process_imported_prompt(raw_p):
            if not raw_p: return ""
            matched_descs = []
            for pr in project_roles:
                r_name = pr.get('name', '').strip()
                r_desc = pr.get('desc', '').strip()
                if r_name and r_desc and r_name in raw_p:
                    raw_p = raw_p.replace(r_name, f"({r_desc})")
                    if r_desc not in matched_descs:
                        matched_descs.append(r_desc)
            if matched_descs:
                raw_p = ", ".join(matched_descs) + ", " + raw_p
            return raw_p

        try:
            data_map = {}
            if ext == '.json':
                with open(path, 'r', encoding='utf-8') as f:
                    imported = json.load(f)
                if isinstance(imported, list) and len(imported) > 0 and isinstance(imported[0], dict):
                    data_map = {str(item['index']): item.get('prompt', '') for item in imported if 'index' in item}
                elif isinstance(imported, list):
                    for i, txt in enumerate(imported):
                        idx_str = str(scenes[i]['index']) if i < len(scenes) else str(
                            (scenes[-1]['index'] if scenes else 0) + (i - len(scenes) + 1))
                        data_map[idx_str] = str(txt)

            elif ext == '.txt':
                with open(path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                is_smart_mode = any(re.match(r'^\[ID:(.*?)\]', line) for line in lines[:5])

                if is_smart_mode:
                    for line in lines:
                        match = re.match(r'^\[ID:(.*?)\]\s*(.*)', line)
                        if match:
                            data_map[str(match.group(1)).strip()] = match.group(2).strip()
                else:
                    for i, line in enumerate(lines):
                        idx_str = str(scenes[i]['index']) if i < len(scenes) else str(
                            (scenes[-1]['index'] if scenes else 0) + (i - len(scenes) + 1))
                        data_map[idx_str] = line

            # 🌟 核心：执行精准替换与自动扩容
            updated_count = 0
            existing_indices = set(str(s['index']) for s in scenes)
            max_idx = max([s['index'] for s in scenes]) if scenes else 0

            for s in scenes:
                s_idx = str(s['index'])
                if s_idx in data_map:
                    s['prompt'] = process_imported_prompt(data_map[s_idx])
                    updated_count += 1

            # 自动扩容：处理多出来的提示词
            new_added_count = 0
            for k, v in data_map.items():
                if k not in existing_indices:
                    try:
                        new_idx = int(k)
                    except ValueError:
                        max_idx += 1
                        new_idx = max_idx

                    scenes.append({
                        "index": new_idx,
                        "duration": 2.0,
                        "text": "【扩展分镜空占位】",  # 仅导入提示词时，没有文案的话占位处理
                        "sub_ids": [new_idx],
                        "prompt": process_imported_prompt(v),
                        "status": "等待处理",
                        "images": [],
                        "selected_image_index": -1,
                        "roles": []
                    })
                    new_added_count += 1
                    max_idx = max(max_idx, new_idx)

            if new_added_count > 0:
                scenes.sort(key=lambda x: x['index'])

            self.main_window.mark_modified()
            self.main_window.save_proj(silent=True)
            self.refresh_scene_list()

            msg = f"✅ 成功导入了 {updated_count} 个镜头的提示词，并完成了角色自动替换！"
            if new_added_count > 0:
                msg += f"\n\n🔥 自动扩容：检测到多出 {new_added_count} 条提示词，已为您自动创建新卡片承载，数据零丢失！"

            QMessageBox.information(self, "导入完成", msg)
            self.log(f"✅ 提示词智能导入完成 (更新:{updated_count}, 扩容:{new_added_count})")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))