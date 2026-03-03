import configparser
import os
import json
import uuid
from PyQt6.QtCore import QObject, QTimer, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from 逻辑.app_workers import PromptWorker
from 配置.app_config import CONFIG_FILE


class InferenceManager(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window

        # 全新的项目级任务队列
        self.project_queue = []
        self.active_workers = []  # 当前正在运行的工作线程

        self.current_session_id = str(uuid.uuid4())  # 当前推理会话的唯一标识，防御脏数据
        self.thread_count = 1  # 默认并发运行的项目数，后续从配置读取

        # 防抖动保存定时器，保护硬盘
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._do_save_proj)

        # 🌟 核心新增：UI 渲染节流阀（防卡顿/崩溃机制）
        # 收集需要刷新的卡片索引，避免多线程瞬间高频触发 UI 渲染导致界面假死
        self.ui_update_queue = {}  # 格式: {project_path: set([scene_index1, scene_index2, ...])}
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self._flush_ui_updates)
        self.ui_update_timer.start(1000)  # 严格控制：每 1000 毫秒（1秒）统一合并刷新一次界面

    def _get_project_id(self):
        if hasattr(self.main_window, 'curr_path') and self.main_window.curr_path:
            return self.main_window.curr_path
        return "Unsaved_Project"

    def _ensure_saved(self):
        """排队机制依赖物理文件路径，推理前强制要求保存"""
        if not getattr(self.main_window, 'curr_path', None):
            reply = QMessageBox.question(
                self.main_window,
                "未保存",
                "多作品排队推理模式下，必须先保存项目以确定路径（方便后台数据隔离）。\n是否立即保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if not self.main_window.save_proj():
                    return False
            else:
                return False
        else:
            # 静默保存最新进度，防止内存和文件数据不同步
            self.main_window.save_proj(silent=True)
        return True

    def _load_config(self):
        """动态加载配置（包括并发数和百度翻译的密钥）"""
        baidu_appid, baidu_secret = "", ""
        project_concurrent_count = 1
        try:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                cfg.read(CONFIG_FILE, encoding='gbk')

            baidu_appid = cfg['DEFAULT'].get('baidu_appid', '').strip()
            baidu_secret = cfg['DEFAULT'].get('baidu_secret', '').strip()
            project_concurrent_count = int(cfg['DEFAULT'].get('project_concurrent_count', 1))
        except Exception:
            pass

        self.thread_count = project_concurrent_count
        return baidu_appid, baidu_secret

    def run_infer_target(self, scene_id):
        """针对当前界面的单条镜头进行推理"""
        if not self.main_window.data.get('scenes'):
            QMessageBox.warning(self.main_window, "提示", "请先进行分镜规划")
            return

        if not self._ensure_saved():
            return

        list_idx = None
        target_scene = None
        for i, s in enumerate(self.main_window.data['scenes']):
            if s['index'] == scene_id:
                list_idx = i
                target_scene = s
                break

        if list_idx is None:
            QMessageBox.warning(self.main_window, "错误", f"未找到镜头编号 {scene_id}")
            return

        # 将单一镜头作为特殊项目提交
        self.submit_project_task(
            project_path=self._get_project_id(),
            scenes_list=[target_scene],
            role_cards=self.main_window.data.get('role_cards', []),
            custom_template=self.main_window.data.get('custom_prompt_template', '')
        )

    def run_infer_all(self):
        """针对当前界面打开的项目进行全量推理"""
        if not self.main_window.data.get('scenes'):
            QMessageBox.warning(self.main_window, "提示", "请先进行分镜规划")
            return

        if not self._ensure_saved():
            return

        proj_id = self._get_project_id()

        # 防呆设计：检查该项目是否已经在队列中或正在运行
        is_running = any(w.project_path == proj_id for w in self.active_workers)
        is_queued = any(t['project_path'] == proj_id for t in self.project_queue)

        if is_running or is_queued:
            reply = QMessageBox.question(
                self.main_window,
                "提示",
                "当前项目已经在推理队列中，继续提交将重新排队。\n确定要继续加入队列吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.submit_project_task(
            project_path=proj_id,
            scenes_list=self.main_window.data['scenes'],
            role_cards=self.main_window.data.get('role_cards', []),
            custom_template=self.main_window.data.get('custom_prompt_template', '')
        )

    def submit_project_task(self, project_path, scenes_list, role_cards, custom_template):
        """无论从哪里调用，只要把完整的项目数据传进来，就能自动排队"""
        task = {
            'project_path': project_path,
            'scenes_list': scenes_list,
            'role_cards': role_cards,
            'custom_template': custom_template
        }
        self.project_queue.append(task)

        total_tasks = len(self.project_queue) + len(self.active_workers)
        if total_tasks > self.thread_count:
            self.on_log(self.current_session_id, project_path,
                        f"📥 项目已加入队列！前面还有 {len(self.project_queue) - 1} 个作品等待处理...", color="#ffaa00")

        self._check_queue()

    def _check_queue(self):
        """核心调度器：控制项目并发数，自动抽取任务指派给新线程"""
        baidu_appid, baidu_secret = self._load_config()

        while len(self.active_workers) < self.thread_count and self.project_queue:
            task = self.project_queue.pop(0)

            self.on_log(self.current_session_id, task['project_path'],
                        f"🚀 宏观调度放行：正式启动专属推理引擎处理本项目...", color="#55ffff")

            worker = PromptWorker(
                session_id=self.current_session_id,
                project_path=task['project_path'],
                scenes_list=task['scenes_list'],
                role_cards=task['role_cards'],
                custom_template=task['custom_template'],
                baidu_appid=baidu_appid,
                baidu_secret=baidu_secret
            )

            worker.log_signal.connect(self.on_log)
            worker.sys_log_signal.connect(self.on_sys_log)
            worker.data_signal.connect(self.on_batch_data_update)
            worker.finished_signal.connect(self.on_worker_finished)

            worker.start()
            self.active_workers.append(worker)

    @pyqtSlot(str, str, list)
    def on_batch_data_update(self, session_id, p_path, updates):
        """处理底层传回的批次数据：更新内存，并立刻刷新 UI 防止被覆写"""
        if session_id != self.current_session_id:
            return

        target_editor = None
        # 严格穿透层级，获取当前真实的项目编辑器实例
        if p_path == self._get_project_id():
            target_editor = self.main_window
        elif hasattr(self.main_window, 'main_app') and hasattr(self.main_window.main_app, 'tab_widget'):
            tab_widget = self.main_window.main_app.tab_widget
            for i in range(tab_widget.count()):
                widget = tab_widget.widget(i)
                if hasattr(widget, 'curr_path') and getattr(widget, 'curr_path', '') == p_path:
                    target_editor = widget
                    break

        if target_editor:
            # 更新内存数据
            scenes = target_editor.data.get('scenes', [])
            scene_map = {s['index']: (i, s) for i, s in enumerate(scenes)}
            updated_indices = []

            for item in updates:
                scene_id = item['scene_index']
                data = item['data']

                if scene_id in scene_map:
                    list_idx, target_scene = scene_map[scene_id]

                    # 全量字段同步，杜绝死角
                    target_scene['prompt'] = data.get('prompt', '')
                    if 'prompt_zh_raw' in data:
                        target_scene['prompt_zh'] = data['prompt_zh_raw']
                        target_scene['prompt_zh_raw'] = data['prompt_zh_raw']
                    if 'prompt_en_raw' in data:
                        target_scene['prompt_en_raw'] = data['prompt_en_raw']
                    if 'prompt_zh_display' in data:
                        target_scene['prompt_zh_display'] = data['prompt_zh_display']
                    if 'roles' in data:
                        target_scene['roles'] = data['roles']

                    target_scene['status'] = "提示词已生成"
                    updated_indices.append(list_idx)

            if updated_indices:
                if p_path not in self.ui_update_queue:
                    self.ui_update_queue[p_path] = set()
                self.ui_update_queue[p_path].update(updated_indices)

                # 🌟 核心防覆盖修复 1：
                # 收到后台数据后，绝不能等 1 秒！必须立刻强制刷新界面！
                # 这样接下来的 save_proj 就绝不会抓取到旧的空数据！
                self._flush_ui_updates()

                if hasattr(target_editor, 'mark_modified'):
                    target_editor.mark_modified()

                if hasattr(target_editor, 'save_proj'):
                    target_editor.save_proj(silent=True)

    def _flush_ui_updates(self):
        """🌟 节流阀：定期将队列中的 UI 刷新任务批量执行"""
        if not self.ui_update_queue:
            return

        # 复制一份当前队列并清空原队列
        queue_snapshot = self.ui_update_queue.copy()
        self.ui_update_queue.clear()

        for p_path, indices_set in queue_snapshot.items():
            if not indices_set:
                continue

            target_editor = None
            # 🌟 修复关键：严格穿透层级获取真实的页面对象
            if p_path == self._get_project_id():
                target_editor = self.main_window
            elif hasattr(self.main_window, 'main_app') and hasattr(self.main_window.main_app, 'tab_widget'):
                tab_widget = self.main_window.main_app.tab_widget
                for i in range(tab_widget.count()):
                    widget = tab_widget.widget(i)
                    if hasattr(widget, 'curr_path') and getattr(widget, 'curr_path', '') == p_path:
                        target_editor = widget
                        break

            if target_editor and hasattr(target_editor, 'studio_page'):
                try:
                    if hasattr(target_editor.studio_page, 'batch_update_cards'):
                        target_editor.studio_page.batch_update_cards(list(indices_set))
                except Exception:
                    pass

    @pyqtSlot(str, str)
    def on_worker_finished(self, session_id, p_path):
        """当一个作品的所有分镜全部处理完毕时触发"""
        if session_id != self.current_session_id: return

        # 清理该完成的线程引用
        self.active_workers = [w for w in self.active_workers if w.project_path != p_path]

        if p_path == self._get_project_id():
            self.main_window.studio_page.log("✅ 当前项目推理任务已全部完成！", color="#55ff55")
        else:
            proj_name = os.path.basename(p_path)
            self.main_window.studio_page.log(f"🎉 挂机队列项目 [{proj_name}] 推理已全部完成！", color="#55ff55")

        # 当前任务完成，检查队列，继续启动下一个作品
        self._check_queue()

    def _trigger_debounced_save(self):
        self.save_timer.start(2000)

    def _do_save_proj(self):
        try:
            self.main_window.save_proj(silent=True)
        except:
            pass

    @pyqtSlot(str, str, str)
    def on_log(self, session_id, p_path, msg, color="#aaaaaa"):
        if session_id != self.current_session_id: return
        if p_path == self._get_project_id():
            self.main_window.studio_page.log(msg, color=color)
        else:
            proj_name = os.path.basename(p_path)
            self.main_window.studio_page.log(f"[{proj_name}] {msg}", color=color)

    @pyqtSlot(str, str, str)
    def on_sys_log(self, session_id, p_path, msg):
        if session_id != self.current_session_id: return
        if p_path == self._get_project_id():
            self.main_window.studio_page.log(msg, color="#ff5555")
        else:
            proj_name = os.path.basename(p_path) if p_path else "系统"
            self.main_window.studio_page.log(f"[{proj_name}] {msg}", color="#ff5555")

    def cancel(self):
        """强制终止所有排队任务与正在运行的线程"""
        # 更新 session_id，让仍在运行旧会话的野线程数据失效被拦截
        self.current_session_id = str(uuid.uuid4())

        # 清空等待队列
        self.project_queue.clear()
        self.ui_update_queue.clear()

        # 通知正在运行的线程停止内部循环
        for worker in self.active_workers:
            worker.is_running = False

        self.active_workers.clear()
        self.on_log(self.current_session_id, self._get_project_id(), "🛑 收到停止指令，已安全中断所有底层任务并清空队列！",
                    color="#ff5555")