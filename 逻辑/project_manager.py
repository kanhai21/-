import os
import json
import shutil
import stat
import time
import configparser
import threading  # 🌟 新增：引入线程锁模块
from datetime import datetime
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QInputDialog
from PyQt6.QtCore import QObject, pyqtSignal, Qt

from 逻辑.srt_util import LocalSRTParser
from 界面.role_card import RoleCard
from 界面.scene_card import SceneCard
from 配置.app_config import CONFIG_FILE, DEFAULT_BGM_VOLUME, DEFAULT_SUBTITLE_EFFECT_ID, DEFAULT_RESOLUTION_MODE

# 1. 明确项目保存根目录 (与 main_window.py 保持一致)
PROJECTS_ROOT_DIR = os.path.join(os.getcwd(), "资源", "saved_projects")
os.makedirs(PROJECTS_ROOT_DIR, exist_ok=True)


class ProjectManager(QObject):
    project_loaded = pyqtSignal(dict)
    project_saved = pyqtSignal(str)
    projects_list_changed = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        # 🌟 核心防御：创建一个文件写入锁，防止多线程高频并发修改同一文件导致文件损坏
        self.save_lock = threading.Lock()

    def create_new_project(self):
        name, ok = QInputDialog.getText(self.main_window, "新建项目", "请输入项目名称:", text="我的小说推文")
        if not ok or not name.strip():
            return None
        name = name.strip()
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            if char in name:
                QMessageBox.warning(self.main_window, "非法名称", f"名称不能包含字符: {invalid_chars}")
                return None

        project_dir = os.path.join(PROJECTS_ROOT_DIR, name)
        ntp_path = os.path.join(project_dir, f"{name}.ntp")

        if os.path.exists(project_dir):
            if os.path.exists(ntp_path):
                QMessageBox.warning(self.main_window, "已存在", "该项目名称已存在，请换一个。")
                return None
            else:
                try:
                    shutil.rmtree(project_dir)
                except Exception as e:
                    QMessageBox.warning(self.main_window, "占用警告", f"检测到残留文件夹但无法清理（可能被占用）: {e}")
                    return None

        try:
            os.makedirs(project_dir)
            assets_dir = os.path.join(project_dir, "assets")
            os.makedirs(assets_dir, exist_ok=True)

            # 读取配置文件中的默认导出设置
            cfg = configparser.ConfigParser()
            try:
                cfg.read(CONFIG_FILE, encoding='utf-8')
            except Exception:
                # 读取失败时使用默认值
                default_bgm_volume = DEFAULT_BGM_VOLUME
                default_subtitle_effect_id = DEFAULT_SUBTITLE_EFFECT_ID
                default_resolution_mode = DEFAULT_RESOLUTION_MODE
            else:
                default_bgm_volume = cfg['DEFAULT'].getfloat('bgm_volume', DEFAULT_BGM_VOLUME)
                default_subtitle_effect_id = cfg['DEFAULT'].get('subtitle_effect_id', DEFAULT_SUBTITLE_EFFECT_ID)
                default_resolution_mode = cfg['DEFAULT'].get('resolution_mode', DEFAULT_RESOLUTION_MODE)

            # 2. 初始化数据结构 (包含新的关键帧参数)
            initial_data = {
                "name": name,
                "audio_path": "",
                "srt_path": "",
                "role_cards": [],
                "scenes": [],
                "keyframe_settings": {
                    "start_scale": 110, "end_scale": 130,
                    "start_x": 0, "start_y": 0,
                    "end_x": 0, "end_y": 0,
                    "random_direction": True,
                    "preset_mode": "custom"  # 新增字段
                },
                "export_settings": {
                    "bgm_volume": default_bgm_volume,
                    "subtitle_effect_id": default_subtitle_effect_id,
                    "resolution_mode": default_resolution_mode,
                    "bgm_path": ""
                },
                "custom_prompt_template": ""
            }

            with open(ntp_path, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)

            return ntp_path
        except Exception as e:
            QMessageBox.critical(self.main_window, "创建失败", str(e))
            return None

    def open_project(self, file_path=None):
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(self.main_window, "打开", PROJECTS_ROOT_DIR, "Project (*.ntp)")
        if file_path:
            self.load_project(file_path)

    def load_project(self, file_path):
        try:
            SceneCard.clear_cache()

            with open(file_path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)

            self.main_window.curr_path = file_path

            # 🌟 核心修复 1：路径自动重定位 (Path Relocation)
            # 获取当前 .ntp 文件所在的实际绝对目录
            project_dir = os.path.dirname(os.path.abspath(file_path))
            assets_dir = os.path.join(project_dir, "assets")

            # 遍历所有镜头，校验并修复图片路径
            for scene in data.get('scenes', []):
                if 'images' in scene and isinstance(scene['images'], list):
                    fixed_images = []
                    for img_p in scene['images']:
                        if not img_p:
                            continue
                        # 如果记录的绝对路径已失效（比如移动了文件夹或换了电脑）
                        if not os.path.exists(img_p):
                            # 尝试在当前项目的 assets 文件夹中寻找同名文件
                            base_name = os.path.basename(img_p)
                            new_p = os.path.join(assets_dir, base_name)
                            if os.path.exists(new_p):
                                fixed_images.append(new_p)
                            else:
                                # 彻底丢失的图片记录将被跳过，防止前端 UI 崩溃或显示错误
                                continue
                        else:
                            fixed_images.append(img_p)
                    # 将修复后的有效路径写回内存数据
                    scene['images'] = fixed_images

            self.main_window.data = data
            self.main_window.lbl_title.setText(data.get('name', os.path.basename(file_path)))

            if hasattr(self.main_window, 'import_page'):
                self.main_window.import_page.e_aud.setText(data.get('audio_path', ''))
                self.main_window.import_page.e_srt.setText(data.get('srt_path', ''))
                # 加载 BGM 路径到界面
                bgm_path = data.get('export_settings', {}).get('bgm_path', '')
                self.main_window.import_page.e_bgm.setText(bgm_path)

            srt_path = data.get('srt_path')
            if srt_path and os.path.exists(srt_path):
                try:
                    self.main_window.raw_data = LocalSRTParser.parse(srt_path)
                except Exception as e:
                    print(f"解析原始字幕失败: {e}")
                    self.main_window.raw_data = []
            else:
                self.main_window.raw_data = []

            # 3. 兼容性处理：补全缺失的关键帧参数
            if 'keyframe_settings' not in self.main_window.data:
                self.main_window.data['keyframe_settings'] = {}

            kf_defaults = {
                "start_scale": 110, "end_scale": 130,
                "start_x": 0, "start_y": 0, "end_x": 0, "end_y": 0,
                "random_direction": True, "preset_mode": "custom"
            }
            # 合并默认值
            current_kf = self.main_window.data['keyframe_settings']
            for k, v in kf_defaults.items():
                if k not in current_kf:
                    current_kf[k] = v
            self.main_window.data['keyframe_settings'] = current_kf

            if 'custom_prompt_template' not in self.main_window.data:
                self.main_window.data['custom_prompt_template'] = ""

            if 'export_settings' not in self.main_window.data:
                self.main_window.data['export_settings'] = {
                    "bgm_volume": DEFAULT_BGM_VOLUME,
                    "subtitle_effect_id": DEFAULT_SUBTITLE_EFFECT_ID,
                    "resolution_mode": DEFAULT_RESOLUTION_MODE,
                    "bgm_path": ""
                }

            self.main_window.clear_roles()
            for r in data.get('role_cards', []):
                self.main_window.add_role_card(r.get('name'), r.get('desc'))

            for s in self.main_window.data['scenes']:
                if 'sub_ids' not in s:
                    s['sub_ids'] = [s['index']]
                if 'prompt' not in s or s['prompt'] is None:
                    s['prompt'] = ""

            self.project_loaded.emit(data)
            return True
        except Exception as e:
            QMessageBox.critical(self.main_window, "读取失败", f"错误: {str(e)}")
            return False

    def load_project_data_silent(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)

            # 🌟 核心修复：后台静默读取数据时，也执行一遍路径重定位保护
            project_dir = os.path.dirname(os.path.abspath(file_path))
            assets_dir = os.path.join(project_dir, "assets")

            for scene in data.get('scenes', []):
                if 'images' in scene and isinstance(scene['images'], list):
                    fixed_images = []
                    for img_p in scene['images']:
                        if not img_p:
                            continue
                        if not os.path.exists(img_p):
                            base_name = os.path.basename(img_p)
                            new_p = os.path.join(assets_dir, base_name)
                            if os.path.exists(new_p):
                                fixed_images.append(new_p)
                        else:
                            fixed_images.append(img_p)
                    scene['images'] = fixed_images

            return data
        except Exception as e:
            print(f"静默加载失败: {e}")
            return None

    def save_project(self, file_path=None, silent=False, sync_from_cards=True):
        try:
            if file_path is None:
                if not self.main_window.curr_path:
                    if silent:
                        return False
                    file_path, _ = QFileDialog.getSaveFileName(self.main_window, "保存",
                                                               os.path.join(PROJECTS_ROOT_DIR, "proj.ntp"),
                                                               "Project (*.ntp)")
                    if not file_path:
                        return False
                else:
                    file_path = self.main_window.curr_path

            if sync_from_cards and hasattr(self.main_window, 'studio_page'):
                roles = []
                for i in range(self.main_window.studio_page.role_list_layout.count()):
                    w = self.main_window.studio_page.role_list_layout.itemAt(i).widget()
                    if isinstance(w, RoleCard):
                        roles.append(w.get_data())
                self.main_window.data['role_cards'] = roles

                for i in range(self.main_window.studio_page.cards_layout.count()):
                    w = self.main_window.studio_page.cards_layout.itemAt(i).widget()
                    if isinstance(w, SceneCard):
                        w.sync_data()

            if hasattr(self.main_window, 'import_page'):
                self.main_window.data['audio_path'] = self.main_window.import_page.e_aud.text()
                self.main_window.data['srt_path'] = self.main_window.import_page.e_srt.text()
                # 同步 BGM 路径
                if 'export_settings' not in self.main_window.data:
                    self.main_window.data['export_settings'] = {}
                if self.main_window.import_page.e_bgm.text():
                    self.main_window.data['export_settings']['bgm_path'] = self.main_window.import_page.e_bgm.text()

            # 🌟 核心防御：在此处加锁，确保同一时间只有一条线程能写入硬盘
            with self.save_lock:

                # 🌟 高危 BUG FIX：防撞保护机制，防止离线挂机进度被前台UI内存旧数据覆盖
                # 写入前先对比一下磁盘现存的文件。如果有后台新刷出来的图片或提示词进度，强行保留继承并合并到待保存内存里。
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as fp_disk:
                            disk_data = json.load(fp_disk)
                        disk_scenes = {str(s.get('index')): s for s in disk_data.get('scenes', [])}

                        for mem_s in self.main_window.data.get('scenes', []):
                            idx = str(mem_s.get('index'))
                            if idx in disk_scenes:
                                ds = disk_scenes[idx]
                                # 如果当前内存的英文提示词是空的，但是硬盘文件里有提示词，说明后台跑出来了！热更新内存合并！
                                if not mem_s.get('prompt_en_raw') and ds.get('prompt_en_raw'):
                                    mem_s['prompt'] = ds.get('prompt', '')
                                    mem_s['prompt_en_raw'] = ds.get('prompt_en_raw', '')
                                    mem_s['prompt_zh_raw'] = ds.get('prompt_zh_raw', '')
                                    mem_s['prompt_zh_display'] = ds.get('prompt_zh_display', '')
                                    mem_s['roles'] = ds.get('roles', [])
                                    mem_s['status'] = ds.get('status', '提示词已生成')

                                # 同理保护生成的图片不丢失
                                if not mem_s.get('images') and ds.get('images'):
                                    mem_s['images'] = ds.get('images', [])
                                    mem_s['status'] = ds.get('status', mem_s.get('status'))
                    except Exception:
                        # 忽略可能出现的文件占用锁或JSON损坏，以保障整体正常保存
                        pass

                # 合并完毕后，安全覆盖进硬盘
                with open(file_path, 'w', encoding='utf-8') as fp:
                    json.dump(self.main_window.data, fp, indent=2, ensure_ascii=False)

            self.main_window.curr_path = file_path
            self.project_saved.emit(file_path)
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self.main_window, "保存失败", f"详情: {str(e)}")
            return False

    def delete_project(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        name = item.text().split('\n')[0]

        reply = QMessageBox.warning(self.main_window, "确认删除", f"确定要彻底删除项目「{name}」吗？\n文件路径: {path}",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if self.main_window.curr_path and os.path.abspath(self.main_window.curr_path) == os.path.abspath(path):
                self.main_window.reset_to_home()

            folder = os.path.dirname(path)

            def on_rm_error(func, path, exc_info):
                os.chmod(path, stat.S_IWRITE)
                try:
                    func(path)
                except Exception:
                    pass

            shutil.rmtree(folder, onerror=on_rm_error)
            self.projects_list_changed.emit()
            QMessageBox.information(self.main_window, "成功", "项目已删除")
        except Exception as e:
            try:
                time.sleep(0.5)
                folder = os.path.dirname(path)
                shutil.rmtree(folder, ignore_errors=True)
                self.projects_list_changed.emit()
            except:
                QMessageBox.critical(self.main_window, "错误",
                                     f"删除失败: {e}\n可能文件正在被占用，请关闭相关文件夹后重试。")