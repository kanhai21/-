import os
import json
import collections
import time
import configparser
import math
import wave  # Python内置原生音频解析库
from datetime import time as dt_time
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread
from PyQt6.QtWidgets import QMessageBox, QDialog

# 核心导入
from 逻辑.logic_jianying import JianYingExporter
from 逻辑.export_thread import ExportThread
from 逻辑.subtitle_align import time_to_us  # 时间对齐工具
from 界面.export_options_dialog import ExportOptionsDialog
from 配置.app_config import CONFIG_FILE, get_keyframe_defaults, get_global_export_defaults

# 🌟 新增：引入我们写好的黑盒模板外挂引擎
from 工具.jianying_template_module import JianyingTemplateProcessor

try:
    from mutagen import File

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False


class ExportManager(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.thread = None
        self.batch_queue = collections.deque()
        self.is_batch_processing = False
        self.batch_total = 0
        self.batch_current = 0
        self.success_count = 0
        self.fail_count = 0

        # 定义全局帧率基准 (必须与 logic_jianying.py 保持一致)
        self.FPS = 30.0
        self.FRAME_US = 1000000.0 / self.FPS

    def _get_audio_duration_us(self, audio_path):
        """获取音频精确时长(微秒) - 包含多重保底机制"""
        if not audio_path or not os.path.exists(audio_path):
            return 0

        # 1. 优先尝试使用 mutagen (支持 mp3, m4a 等多种格式)
        if MUTAGEN_AVAILABLE:
            try:
                f = File(audio_path)
                if f and f.info:
                    return int(round(f.info.length * 1_000_000))
            except:
                pass

        # 2. 原生保底方案：如果是 wav 文件，使用 Python 内置 wave 库解析（无需安装第三方包）
        if audio_path.lower().endswith('.wav'):
            try:
                with wave.open(audio_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    if rate > 0:
                        duration = frames / float(rate)
                        return int(round(duration * 1_000_000))
            except:
                pass

        return 0

    def _snap_to_frame(self, us):
        """
        【核心算法】将微秒时间强制吸附到最近的帧刻度
        """
        frames = round(us / self.FRAME_US)
        return int(frames * self.FRAME_US)

    def _calculate_aligned_data(self, scenes, raw_data, total_audio_us):
        """
        【终极对齐算法】
        """
        # 1. 建立字幕索引映射 {index: raw_start_us}
        sub_raw_map = {}
        if raw_data:
            for item in raw_data:
                try:
                    t_val = time_to_us(item['start'])
                    t_end = time_to_us(item['end'])
                    sub_raw_map[item['index']] = {
                        "start": t_val,
                        "end": t_end,
                        "text": item['text'],
                        "index": item['index']
                    }
                except:
                    continue

        # 2. 确定每个 Scene 的"原始绝对开始时间"
        scene_raw_starts = []
        for i, scene in enumerate(scenes):
            sub_ids = scene.get('sub_ids', [])
            found_start = False
            start_us = 0
            if sub_ids:
                valid_starts = [sub_raw_map[sid]["start"] for sid in sub_ids if sid in sub_raw_map]
                if valid_starts:
                    start_us = min(valid_starts)
                    found_start = True

            if i == 0:
                start_us = 0
                found_start = True

            if not found_start:
                scene_raw_starts.append(None)
            else:
                scene_raw_starts.append(start_us)

        for i in range(len(scene_raw_starts)):
            if scene_raw_starts[i] is None:
                prev = scene_raw_starts[i - 1] if i > 0 else 0
                scene_raw_starts[i] = prev

        for i in range(1, len(scene_raw_starts)):
            if scene_raw_starts[i] < scene_raw_starts[i - 1]:
                scene_raw_starts[i] = scene_raw_starts[i - 1]

        final_images_data = []
        aligned_subtitles = []
        current_video_cursor = 0
        count = len(scenes)
        total_audio_aligned = self._snap_to_frame(total_audio_us)

        for i in range(count):
            raw_scene_start = scene_raw_starts[i]

            if i < count - 1:
                raw_next_start = scene_raw_starts[i + 1]
                raw_duration = raw_next_start - raw_scene_start
            else:
                if total_audio_aligned > raw_scene_start:
                    raw_duration = total_audio_aligned - raw_scene_start
                else:
                    fallback_duration = 3_000_000
                    if sub_raw_map:
                        try:
                            last_sub_end = max([sub["end"] for sub in sub_raw_map.values()])
                            if last_sub_end > raw_scene_start:
                                fallback_duration = last_sub_end - raw_scene_start + 500_000
                        except:
                            pass
                    raw_duration = fallback_duration

            if raw_duration <= 0:
                raw_duration = 1_000_000

            snapped_duration_us = self._snap_to_frame(raw_duration)
            if snapped_duration_us < int(self.FRAME_US):
                snapped_duration_us = int(self.FRAME_US)

            video_scene_start = current_video_cursor

            sub_ids = scenes[i].get('sub_ids', [])
            if sub_ids:
                first_sub_raw_start = None
                for sid in sub_ids:
                    if sid in sub_raw_map:
                        first_sub_raw_start = sub_raw_map[sid]["start"]
                        break

                if first_sub_raw_start is not None:
                    drift_offset = video_scene_start - first_sub_raw_start
                    for sid in sub_ids:
                        if sid in sub_raw_map:
                            raw_sub = sub_raw_map[sid]
                            new_start = raw_sub["start"] + drift_offset
                            new_end = raw_sub["end"] + drift_offset

                            aligned_subtitles.append({
                                'start_us': new_start,
                                'end_us': new_end,
                                'text': raw_sub["text"].replace('\n', ' ').strip()
                            })

            s = scenes[i]
            img_path = ""
            if s.get('images'):
                idx = s.get('selected_image_index', 0)
                if 0 <= idx < len(s['images']):
                    img_path = s['images'][idx]
                else:
                    img_path = s['images'][0]

            final_images_data.append({
                "path": img_path,
                "duration_us": snapped_duration_us,
                "sub_ids": sub_ids,
                "scene_index": s.get('index', 0)
            })

            current_video_cursor += snapped_duration_us

        return final_images_data, aligned_subtitles

    def _get_draft_root_dir(self):
        """轻量级方法：仅从配置文件或默认路径中获取剪映的草稿保存根目录"""
        config_path = os.path.abspath(CONFIG_FILE)
        if not os.path.exists(config_path):
            config_path = os.path.join(os.getcwd(), 'config.ini')

        draft_dir = ""
        if os.path.exists(config_path):
            try:
                cfg = configparser.ConfigParser()
                for enc in ['utf-8', 'utf-8-sig', 'gbk']:
                    try:
                        with open(config_path, 'r', encoding=enc) as f:
                            cfg.read_file(f)
                        break
                    except:
                        continue
                if 'DEFAULT' in cfg:
                    draft_dir = cfg['DEFAULT'].get('jianying_path', '')
                if not draft_dir and 'Settings' in cfg:
                    draft_dir = cfg['Settings'].get('jianying_path', '')
                if draft_dir:
                    draft_dir = draft_dir.strip().strip('"').strip("'")
            except Exception as e:
                print(f"配置文件读取异常: {e}")

        if not draft_dir:
            default_paths = [
                os.path.expanduser("~") + "/Documents/JianyingPro Drafts",
                "D:/APP/剪映/JianyingPro Drafts",
                "C:/Users/Public/Documents/JianyingPro Drafts"
            ]
            for p in default_paths:
                if os.path.exists(p):
                    draft_dir = p
                    break

        if draft_dir and not os.path.exists(draft_dir):
            try:
                os.makedirs(draft_dir, exist_ok=True)
            except:
                pass

        return draft_dir

    def _get_configured_exporter(self, project_name, resolution_mode="16:9", upscale_factor="None",
                                 local_kf_settings=None):
        draft_dir = self._get_draft_root_dir()

        # 合并运镜设置
        kf_settings = get_keyframe_defaults()
        if local_kf_settings:
            kf_settings.update(local_kf_settings)

        return JianYingExporter(
            project_name=project_name,
            draft_root_dir=draft_dir,
            upscale_factor=upscale_factor,
            canvas_ratio=resolution_mode,
            keyframe_settings=kf_settings
        )

    def _resolve_export_params(self, local_settings):
        global_defaults = get_global_export_defaults()
        bgm_path = local_settings.get('bgm_path', '').strip()
        use_global_bgm = False
        if not bgm_path:
            bgm_path = global_defaults.get('bgm_path', '').strip()
            use_global_bgm = True

        if use_global_bgm:
            bgm_vol = float(global_defaults.get('bgm_volume', 0.2))
        else:
            bgm_vol = float(local_settings.get('bgm_volume', 0.2))

        effect_id = local_settings.get('subtitle_effect_id', '').strip()
        if not effect_id:
            effect_id = global_defaults.get('subtitle_effect_id', '').strip()

        return bgm_path, bgm_vol, effect_id

    def run_export(self):
        data = self.main_window.data
        scenes = data.get('scenes', [])

        if not scenes:
            QMessageBox.warning(self.main_window, "提示", "当前项目没有任何分镜，无法导出。")
            return

        missing_scenes = []
        for s in scenes:
            images = s.get('images', [])
            if not images:
                missing_scenes.append(str(s.get('index', '?')))
                continue
            idx = s.get('selected_image_index', 0)
            if idx < 0 or idx >= len(images):
                idx = 0
            img_path = images[idx]
            if not img_path or not os.path.exists(img_path):
                missing_scenes.append(str(s.get('index', '?')))

        if missing_scenes:
            QMessageBox.warning(
                self.main_window,
                "⚠️ 导出拦截：图片缺失",
                f"无法导出草稿！检测到以下镜头未生成图片或文件已丢失：\n\n"
                f"镜头号：{', '.join(missing_scenes)}\n\n"
                f"请先去【绘图工坊】为这些镜头生成图片，然后再尝试导出草稿。"
            )
            return

        current_export_settings = data.get('export_settings', {})
        if not current_export_settings.get('bgm_path') and self.main_window.import_page.e_bgm.text():
            current_export_settings['bgm_path'] = self.main_window.import_page.e_bgm.text()

        dlg = ExportOptionsDialog(current_export_settings, self.main_window)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_export_settings = dlg.get_settings()
        self.main_window.data['export_settings'] = new_export_settings
        self.main_window.import_page.e_bgm.setText(new_export_settings.get('bgm_path', ''))

        if not self.main_window.save_proj(silent=True):
            return

        if not dlg.should_export:
            self.main_window.studio_page.log("✅ 导出参数已保存")
            QMessageBox.information(self.main_window, "保存成功", "参数已保存！下次导出将自动应用。")
            return

        audio_path = data.get('audio_path', '')
        if not audio_path or not os.path.exists(audio_path):
            QMessageBox.warning(self.main_window, "错误", f"未找到配音文件：\n{audio_path}")
            return

        raw_data = self.main_window.raw_data
        if not raw_data:
            srt_path = data.get('srt_path', '')
            if srt_path and os.path.exists(srt_path):
                from 逻辑.srt_util import LocalSRTParser
                try:
                    raw_data = LocalSRTParser.parse(srt_path)
                    self.main_window.raw_data = raw_data
                except Exception as e:
                    QMessageBox.warning(self.main_window, "错误", f"无法解析字幕文件：{e}")
                    return
            else:
                QMessageBox.warning(self.main_window, "错误", "未找到原始字幕数据，无法导出字幕。")
                return

        total_audio_us = self._get_audio_duration_us(audio_path)
        if total_audio_us == 0:
            self.main_window.studio_page.log("⚠️ 警告：无法读取音频精确时长，将通过字幕时间智能推算。")

        try:
            images_data, aligned_subtitles = self._calculate_aligned_data(scenes, raw_data, total_audio_us)
        except Exception as e:
            QMessageBox.critical(self.main_window, "计算错误", f"时间轴计算失败: {str(e)}")
            return

        final_bgm_path, final_bgm_vol, final_effect_id = self._resolve_export_params(new_export_settings)
        if final_bgm_path and not os.path.exists(final_bgm_path):
            final_bgm_path = ""

        resolution = new_export_settings.get('resolution_mode', '16:9')

        # ================= 🌟 核心修复：精准拉取放大倍数 =================
        upscale_factor = new_export_settings.get('upscale_factor')
        if not upscale_factor or str(upscale_factor).lower() in ['none', 'null', '']:
            try:
                cfg = configparser.ConfigParser()
                for enc in ['utf-8', 'utf-8-sig', 'gbk']:
                    try:
                        cfg.read(CONFIG_FILE, encoding=enc)
                        break
                    except Exception:
                        continue
                if cfg.has_option('DEFAULT', 'upscale_factor'):
                    upscale_factor = cfg.get('DEFAULT', 'upscale_factor')
                elif cfg.has_option('Settings', 'upscale_factor'):
                    upscale_factor = cfg.get('Settings', 'upscale_factor')
                else:
                    upscale_factor = 'None'
            except Exception:
                upscale_factor = 'None'

        if not upscale_factor:
            upscale_factor = 'None'
        # ===============================================================

        local_kf = data.get('keyframe_settings', {})
        project_name = data.get('name', 'NewProject')

        exporter = self._get_configured_exporter(
            project_name,
            resolution_mode=resolution,
            upscale_factor=upscale_factor,
            local_kf_settings=local_kf
        )

        self.main_window.studio_page.log(
            f"🚀 开始导出: {project_name} (画幅: {resolution}, 画质放大: {upscale_factor})...")
        if final_effect_id:
            self.main_window.studio_page.log(f"✨ 应用花字特效: {final_effect_id}")

        self.thread = ExportThread(
            exporter,
            audio_path,
            images_data,
            aligned_subtitles,
            bgm_path=final_bgm_path,
            bgm_volume=final_bgm_vol,
            subtitle_effect_id=final_effect_id
        )
        self.thread.finished_signal.connect(self.on_single_success)
        self.thread.error_signal.connect(self.on_single_error)
        self.thread.log_signal.connect(self.main_window.studio_page.log)
        self.thread.start()

    def on_single_success(self, path):
        self.main_window.studio_page.log(f"✅ 导出成功! 草稿路径: {path}")
        QMessageBox.information(self.main_window, "成功", f"导出完成！\n{path}")

    def on_single_error(self, err):
        self.main_window.studio_page.log(f"❌ 导出失败: {err}")
        QMessageBox.critical(self.main_window, "导出失败", str(err))

    def run_batch_export(self, paths):
        pass


# ================= 🌟 模板外挂线程 =================
class TemplateExportThread(QThread):
    batch_finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    # 🌟 修复：增加 upscale_factor 参数接收
    def __init__(self, template_dir, proj_data, draft_dir, proj_name, aligned_subtitles=None, images_data=None,
                 upscale_factor="None"):
        super().__init__()
        self.template_dir = template_dir
        self.proj_data = proj_data
        self.draft_dir = draft_dir
        self.proj_name = proj_name
        self.aligned_subtitles = aligned_subtitles
        self.images_data = images_data
        self.upscale_factor = upscale_factor

    def run(self):
        try:
            # 🌟 修复：将放大倍数传递给底层的模板处理引擎
            processor = JianyingTemplateProcessor(
                self.template_dir, self.proj_data, self.draft_dir, self.proj_name, self.upscale_factor
            )

            # 强行将精确的时间轴数据注入到处理引擎中
            processor.aligned_subtitles = self.aligned_subtitles
            processor.images_data = self.images_data

            def log_cb(msg):
                self.log_signal.emit(msg.strip())

            success = processor.process(log_cb)
            if success:
                self.batch_finished_signal.emit()
            else:
                self.error_signal.emit("模板处理失败，请查看控制台日志。")
        except Exception as e:
            self.error_signal.emit(f"模板引擎致命异常: {str(e)}")


# ================= 用于后台批量导出的管理器 =================
class BatchExportManager(ExportManager):
    def __init__(self, batch_page):
        super().__init__(batch_page.main_window)
        self.batch_page = batch_page

    def _log_batch(self, text):
        if hasattr(self.batch_page, 'append_log'):
            self.batch_page.append_log(text)
        else:
            print(f"[BatchExport] {text}")

    def _on_batch_thread_finished(self):
        self.success_count += 1
        self._log_batch(f"✅ 成功：项目 {self.batch_current} 导出完毕！")
        if hasattr(self.batch_page, 'update_progress'):
            self.batch_page.update_progress(self.batch_current, self.batch_total)
        self._trigger_next_batch()

    def _on_batch_thread_error(self, err_msg):
        self._log_batch(f"❌ 错误拦截：{err_msg}")
        self.fail_count += 1
        if hasattr(self.batch_page, 'update_progress'):
            self.batch_page.update_progress(self.batch_current, self.batch_total)
        self._trigger_next_batch()

    def run_batch_export(self, paths):
        if self.is_batch_processing:
            QMessageBox.warning(self.batch_page, "提示", "已有任务在运行中。")
            return

        self.batch_queue.clear()
        for p in paths:
            self.batch_queue.append(p)

        self.batch_total = len(paths)
        self.batch_current = 0
        self.success_count = 0
        self.fail_count = 0
        self.is_batch_processing = True

        self._log_batch(f"=== 开始全自动批量导出 {self.batch_total} 个项目 ===")
        self._process_next_batch_item()

    def _process_next_batch_item(self):
        if not self.batch_queue:
            self.is_batch_processing = False
            summary = f"批量后台导出圆满结束。\\n✅ 成功: {self.success_count} 个\\n❌ 失败: {self.fail_count} 个"
            self._log_batch(f"\\n🎉 {summary}")
            QMessageBox.information(self.batch_page, "批量导出完成", summary.replace("\\n", "\n"))

            if hasattr(self.batch_page, 'btn_run'):
                self.batch_page.btn_run.setEnabled(True)
                self.batch_page.btn_run.setText("🚀 启动后台批量静默导出")
            return

        ntp_path = self.batch_queue.popleft()
        self.batch_current += 1

        if hasattr(self.batch_page, 'update_progress'):
            self.batch_page.update_progress(self.batch_current - 1, self.batch_total)

        try:
            filename = os.path.basename(ntp_path)
            self._log_batch(f"\\n----------------------------------")
            self._log_batch(f"[{self.batch_current}/{self.batch_total}] 正在硬盘加载: {filename}")

            if not os.path.exists(ntp_path):
                raise Exception("找不到对应的工程文件")

            with open(ntp_path, 'r', encoding='utf-8') as f:
                proj_data = json.load(f)

            proj_name = proj_data.get('name', filename.replace('.ntp', ''))
            audio_path = proj_data.get('audio_path', '')
            scenes = proj_data.get('scenes', [])
            srt_path = proj_data.get('srt_path', '')

            if not audio_path or not os.path.exists(audio_path):
                raise Exception("配音音频文件缺失或被移动")
            if not scenes:
                raise Exception("该项目尚未生成分镜数据")

            missing_scenes = []
            for s in scenes:
                images = s.get('images', [])
                if not images:
                    missing_scenes.append(str(s.get('index', '?')))
                    continue
                idx = s.get('selected_image_index', 0)
                if idx < 0 or idx >= len(images):
                    idx = 0
                img_path = images[idx]
                if not img_path or not os.path.exists(img_path):
                    missing_scenes.append(str(s.get('index', '?')))

            if missing_scenes:
                raise Exception(f"因缺失图片被拦截 (镜头: {','.join(missing_scenes)})，请先生图")

            if not srt_path or not os.path.exists(srt_path):
                raise Exception("字幕SRT文件缺失")

            export_settings = proj_data.get('export_settings', {})
            template_path = export_settings.get('template_path', '').strip()

            from 逻辑.srt_util import LocalSRTParser
            raw_data = LocalSRTParser.parse(srt_path)
            total_audio_us = self._get_audio_duration_us(audio_path)

            # 🌟 获得绝对准确的视频帧与字幕帧！
            images_data, aligned_subtitles = self._calculate_aligned_data(scenes, raw_data, total_audio_us)

            # ================= 🌟 核心修复点：精准读取全局放大倍数 =================
            resolution = export_settings.get('resolution_mode', '16:9')
            upscale_factor = export_settings.get('upscale_factor')

            # 如果项目自身没存放大倍数，或者值无效，自动去配置中心拉取全局默认值
            if not upscale_factor or str(upscale_factor).lower() in ['none', 'null', '']:
                try:
                    cfg = configparser.ConfigParser()
                    for enc in ['utf-8', 'utf-8-sig', 'gbk']:
                        try:
                            cfg.read(CONFIG_FILE, encoding=enc)
                            break
                        except Exception:
                            continue

                    if cfg.has_option('DEFAULT', 'upscale_factor'):
                        upscale_factor = cfg.get('DEFAULT', 'upscale_factor')
                    elif cfg.has_option('Settings', 'upscale_factor'):
                        upscale_factor = cfg.get('Settings', 'upscale_factor')
                    else:
                        upscale_factor = 'None'
                except Exception:
                    upscale_factor = 'None'

            if not upscale_factor:
                upscale_factor = 'None'
            # =========================================================================

            local_kf = proj_data.get('keyframe_settings', {})

            if template_path and os.path.exists(template_path):
                self._log_batch(f"➡️ 检测到专属模板设定，启动黑盒基因克隆引擎 (放大倍数: {upscale_factor})...")

                draft_dir = self._get_draft_root_dir()

                # 🌟 将正确读取的放大倍数传入模板处理线程
                self.thread = TemplateExportThread(
                    template_path, proj_data, draft_dir, proj_name,
                    aligned_subtitles=aligned_subtitles,
                    images_data=images_data,
                    upscale_factor=upscale_factor
                )
                self.thread.batch_finished_signal.connect(self._on_batch_thread_finished)
                self.thread.error_signal.connect(self._on_batch_thread_error)
                self.thread.log_signal.connect(self._log_batch)
                self.thread.start()

            else:
                # 原生无模板导出逻辑
                final_bgm_path, final_bgm_vol, final_effect_id = self._resolve_export_params(export_settings)

                if final_bgm_path and not os.path.exists(final_bgm_path):
                    self._log_batch(f"⚠️ 指定的BGM文件已失效，将移除BGM: {final_bgm_path}")
                    final_bgm_path = ""

                self._log_batch(
                    f"➡️ 正在拼接原生剪映数据: {proj_name} (画幅: {resolution}, 画质放大: {upscale_factor})")

                exporter = self._get_configured_exporter(
                    proj_name,
                    resolution_mode=resolution,
                    upscale_factor=upscale_factor,
                    local_kf_settings=local_kf
                )

                self.thread = ExportThread(
                    exporter, audio_path, images_data, aligned_subtitles,
                    bgm_path=final_bgm_path, bgm_volume=final_bgm_vol, subtitle_effect_id=final_effect_id
                )
                self.thread.batch_finished_signal.connect(self._on_batch_thread_finished)
                self.thread.error_signal.connect(self._on_batch_thread_error)
                self.thread.start()

        except Exception as e:
            self._log_batch(f"❌ 跳过本项目：{str(e)}")
            self.fail_count += 1
            self._trigger_next_batch()

    def _trigger_next_batch(self):
        QTimer.singleShot(500, self._process_next_batch_item)