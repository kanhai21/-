import configparser
import os
import shutil
import random
import json
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from 配置.app_config import CONFIG_FILE, DEFAULT_COMFYUI_URL
from 逻辑.app_workers import ImageGenThread
from 逻辑.baidu_trans import BaiduTranslator


class ImageGenManager(QObject):
    image_ready = pyqtSignal(int, str)
    generation_finished = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window  # 这里实际传入的是 ProjectEditor 实例
        self.t_img = None

    def run_gen_target(self, idx, skip_existing=False):
        # 强制保存检查
        if not self.main_window.curr_path:
            reply = QMessageBox.question(
                self.main_window,
                "未保存",
                "多作品模式下，生图前必须保存项目以隔离素材。\n是否立即保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if not self.main_window.save_proj(): return
            else:
                return
        else:
            # 静默保存进度
            self.main_window.save_proj(silent=True)

        # 核心优化：多编码容错读取配置
        cfg = configparser.ConfigParser()
        try:
            for enc in ['utf-8', 'utf-8-sig', 'gbk']:
                try:
                    cfg.read(CONFIG_FILE, encoding=enc)
                    break
                except Exception:
                    continue
        except Exception:
            pass  # 读取失败时使用默认配置

        # 确定节点池：判断是指定了单节点，还是全局自动分配
        target_node_url = self.main_window.data.get('target_node_url', '')
        project_wf = self.main_window.data.get('workflow_file', '')
        node_list = []

        if target_node_url and project_wf:
            # 用户在 UI 中手动指定了当前项目的专属节点
            node_list = [{'url': target_node_url, 'workflow': project_wf, 'name': '项目专属节点'}]
            if hasattr(self.main_window, 'studio_page'):
                self.main_window.studio_page.log(f"🔒 使用绑定节点: {target_node_url}")
        else:
            # 用户选择“全局默认”，系统准备进入智能负载均衡
            raw_json = cfg['DEFAULT'].get('node_map_json', '[]')
            try:
                node_list = json.loads(raw_json)
            except:
                node_list = []

            # 兼容极旧版本的配置格式
            if not node_list:
                url_list_str = cfg['DEFAULT'].get('comfy_ui_nodes', '')
                url_list = [u.strip() for u in url_list_str.split(',') if u.strip()]
                if not url_list:
                    url_list = [cfg['DEFAULT'].get('comfy_url', DEFAULT_COMFYUI_URL)]
                default_wf = cfg['DEFAULT'].get('default_workflow', '')
                node_list = [{'url': u, 'workflow': default_wf, 'name': f"节点-{i}"} for i, u in enumerate(url_list)]

            if hasattr(self.main_window, 'studio_page'):
                self.main_window.studio_page.log(f"🌐 启用智能负载均衡 (共 {len(node_list)} 个节点池)...")

        # 确定需要生图的镜头列表
        target_list = None
        if idx:
            target_list = [idx]
        elif skip_existing:
            target_list = []
            for s in self.main_window.data.get('scenes', []):
                if not s.get('images'): target_list.append(s['index'])
            if not target_list:
                QMessageBox.information(self.main_window, "提示", "所有镜头均已有图片，无需生成。")
                return

        role_map = {r['name']: r['desc'] for r in self.main_window.data.get('role_cards', [])}

        baidu_appid = cfg['DEFAULT'].get('baidu_appid', '')
        baidu_secret = cfg['DEFAULT'].get('baidu_secret', '')
        translator = None
        if baidu_appid and baidu_secret:
            translator = BaiduTranslator(baidu_appid, baidu_secret)

        # ====== 核心升级：读取用户的画幅/分辨率比例 ======
        # (默认16:9，将传递给底层用于自动修改 EmptyLatentImage 节点)
        resolution_mode = self.main_window.data.get('export_settings', {}).get('resolution_mode', '16:9')

        # 启动前安全停止已有的生图线程
        self.stop_gen()

        self.t_img = ImageGenThread(
            node_list=node_list,          # 传递节点池
            scenes=self.main_window.data.get('scenes', []),
            target_list=target_list,
            role_map=role_map,
            translator=translator,
            resolution=resolution_mode    # 传递画幅参数
        )

        self.t_img.image_ready_signal.connect(self.on_img_ready)

        # 绑定日志输出，增加容错防崩溃
        if hasattr(self.main_window, 'studio_page'):
            self.t_img.log_signal.connect(
                lambda msg: self.main_window.studio_page.log(msg) if hasattr(self, 'main_window') else None
            )
            self.t_img.error_signal.connect(
                lambda e: self.main_window.studio_page.log(f"❌ {e}", color="#ff5555") if hasattr(self, 'main_window') else None
            )

        self.t_img.finished_signal.connect(self.on_generation_finished)
        self.t_img.start()

    def stop_gen(self):
        """安全停止生图任务，防卡死防崩溃"""
        if self.t_img and self.t_img.isRunning():
            try:
                self.t_img.image_ready_signal.disconnect()
                self.t_img.log_signal.disconnect()
                self.t_img.error_signal.disconnect()
                self.t_img.finished_signal.disconnect()
            except Exception:
                pass

            self.t_img.requestInterruption()

            try:
                if hasattr(self.main_window, 'studio_page'):
                    self.main_window.studio_page.log("🛑 已发送中止指令，生图队列将停止", color="#ffaa00")
            except Exception:
                pass

            self.t_img = None

    def on_img_ready(self, scene_id, temp_path):
        """处理生成的图片，带严格防崩溃和路径规范化机制"""
        try:
            if not hasattr(self, 'main_window') or self.main_window is None:
                return
        except Exception:
            return

        # 🌟 核心修复 3：使用绝对安全路径存储，避免产生相对路径的歧义
        project_dir = os.path.dirname(os.path.abspath(self.main_window.curr_path))
        assets_dir = os.path.join(project_dir, "assets")

        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir)

        try:
            filename = os.path.basename(temp_path)
            # 使用 normpath 彻底规范化路径斜杠（防止 Windows 下正反斜杠混杂导致匹配失败）
            final_path = os.path.normpath(os.path.join(assets_dir, filename))
            shutil.move(temp_path, final_path)
        except Exception as e:
            print(f"移动图片失败: {e}")
            final_path = temp_path

        list_idx = -1
        try:
            scenes = self.main_window.data.get('scenes', [])
            for i, s in enumerate(scenes):
                if s.get('index') == scene_id:
                    list_idx = i
                    break

            if list_idx != -1:
                s = scenes[list_idx]
                s.setdefault('images', []).append(final_path)
                s['selected_image_index'] = len(s['images']) - 1

                if hasattr(self.main_window, 'studio_page'):
                    self.main_window.studio_page.update_scene_card(list_idx)
                    self.main_window.studio_page.update_stats(scenes)
            else:
                print(f"警告：找不到 index={scene_id} 的镜头数据。")
        except Exception as e:
            print(f"更新UI与数据异常: {e}")

        try:
            self.main_window.save_proj(silent=True)
            self.image_ready.emit(scene_id, final_path)
        except Exception:
            pass

    def on_generation_finished(self):
        try:
            if hasattr(self.main_window, 'studio_page'):
                self.main_window.studio_page.log("🎉 生图任务队列完成", color="#55ff55")
            self.generation_finished.emit()
        except Exception:
            pass