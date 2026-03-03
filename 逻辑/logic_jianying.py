import json
import os
import shutil
import subprocess
import time
import uuid
import concurrent.futures
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------- 仅使用 Pillow ----------
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ---------- 音频时长读取 ----------
try:
    from mutagen import File

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# ---------- 导入关键帧模块（从逻辑包导入）----------
from 逻辑.keyframe_module import KeyframeSettings, calculate_keyframe_values


class JianYingExporter:
    """
    剪映草稿导出器（Jianying 5.9 官方格式完美适配版 - BGM 循环铺满版）

    【核心逻辑保持不变】：
    1. 对齐算法：坚持使用 int(x + 0.5) 标准四舍五入，防止丢帧。
    2. 视频基准：以视频总帧数为上帝时间 (Final Duration)。
    3. 字幕磁吸：最后一条字幕强制吸附视频结尾。

    【新增修改】：
    1. BGM 逻辑：如果 BGM 短于视频，会自动循环拼接直到铺满全长。
    """

    # 预设画布尺寸映射
    CANVAS_SIZE_MAP = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:3": (1440, 1080),
        "2.35:1": (1920, 817),
    }

    # 字幕默认参数
    SUBTITLE_FONT_SIZE = 8.0
    SUBTITLE_SCALE = 1.0
    SUBTITLE_Y_POS = -0.85

    # 基础帧率 (剪映标准)
    FPS = 30.0

    def __init__(
            self,
            project_name: str,
            draft_root_dir: str,
            upscale_factor: str = "4x",
            canvas_ratio: Union[str, Dict] = "16:9",
            model_type: str = "realesrgan-x4plus",
            ncnn_exe_path: Optional[str] = None,
            model_dir: Optional[str] = None,
            keyframe_settings: Optional[Dict] = None,
    ) -> None:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow 库未安装，请执行: pip install Pillow")

        self.project_name = project_name
        self.draft_root_dir = self._find_real_root_dir(draft_root_dir)
        self.upscale_factor = upscale_factor
        self.canvas_ratio = canvas_ratio
        self.model_type = model_type

        # 确保项目目录存在
        self.project_dir = Path(self.draft_root_dir) / self.project_name
        self.project_dir.mkdir(parents=True, exist_ok=True)

        self.assets_dir = self.project_dir / "resources"
        self.assets_dir.mkdir(exist_ok=True)

        self.ncnn_exe: Optional[str] = None
        self.model_dir_path: Optional[str] = None
        self._init_ncnn_executable(ncnn_exe_path, model_dir)

        # 初始化关键帧设置
        if keyframe_settings is None:
            self.keyframe_settings = KeyframeSettings(
                start_scale=1.1, end_scale=1.3,
                enable_scale=True, enable_pan_x=True, enable_pan_y=True,
                x_direction="random", y_direction="random", scale_direction="random"
            )
        elif isinstance(keyframe_settings, dict):
            self.keyframe_settings = KeyframeSettings.from_dict(keyframe_settings)
        else:
            self.keyframe_settings = keyframe_settings

        self.total_images = 0
        self.need_upscale_count = 0
        self.actual_upscaled = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.cover_generated = False

    def _to_win_path(self, path_obj: Union[str, Path]) -> str:
        """强制转换为 Windows 反斜杠绝对路径"""
        if path_obj is None:
            return ""
        p = Path(path_obj).resolve()
        return str(p).replace("/", "\\")

    def _get_time_at_frame(self, frame_idx: int) -> int:
        """
        [剪映标准] 获取第 N 帧的绝对微秒时间戳
        剪映逻辑：直接根据 FPS 计算，向下取整。
        """
        return int(frame_idx * 1000000.0 / self.FPS)

    def _us_to_frames(self, us: int) -> int:
        """
        [核心修复算法] 将微秒转换为帧数
        使用 int(x + 0.5) 实现标准的 School Rounding (四舍五入)。
        避免 Python round() 的 Banker's Rounding (2.5->2) 导致的丢帧。
        """
        return int(us * self.FPS / 1000000.0 + 0.5)

    def _find_real_root_dir(self, input_path: str) -> str:
        path = Path(input_path).resolve()
        if (path / "root_meta_info.json").exists():
            return str(path)
        parent = path.parent
        if (parent / "root_meta_info.json").exists():
            return str(parent)
        return str(path)

    def _init_ncnn_executable(self, ncnn_exe_path: Optional[str], model_dir: Optional[str]) -> None:
        if ncnn_exe_path is None:
            search_paths = [
                Path.cwd() / "realesrgan-ncnn-vulkan-20220424-windows" / "realesrgan-ncnn-vulkan.exe",
                Path.cwd() / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
                Path.cwd() / "realesrgan-ncnn-vulkan.exe",
            ]
            for p in search_paths:
                if p.exists():
                    self.ncnn_exe = str(p)
                    break
        else:
            p = Path(ncnn_exe_path)
            if p.exists():
                self.ncnn_exe = str(p)

        if model_dir is None:
            search_dirs = [
                Path.cwd() / "models",
                Path.cwd(),
                Path(__file__).parent / "models",
            ]
            for base in search_dirs:
                if (base / f"{self.model_dir_path}.param").exists():
                    self.model_dir_path = str(base)
                    break
                # Fallback check
                if (base / f"realesrgan-x4plus.param").exists():
                    self.model_dir_path = str(base)
                    break
        else:
            md = Path(model_dir)
            if md.exists():
                self.model_dir_path = str(md)

        # 兜底：如果没找到 model_dir，尝试当前目录
        if not self.model_dir_path:
            self.model_dir_path = str(Path.cwd() / "models")

    @staticmethod
    def _gen_id() -> str:
        return str(uuid.uuid4()).upper()

    def _determine_canvas_size(self, image_list: List[Dict]) -> Tuple[int, int]:
        if isinstance(self.canvas_ratio, dict):
            if self.canvas_ratio.get("mode") == "custom":
                return int(self.canvas_ratio.get("w", 1920)), int(self.canvas_ratio.get("h", 1080))
            preset = self.canvas_ratio.get("value", "16:9")
            return self.CANVAS_SIZE_MAP.get(preset, (1920, 1080))

        if self.canvas_ratio != "original" and self.canvas_ratio in self.CANVAS_SIZE_MAP:
            return self.CANVAS_SIZE_MAP[self.canvas_ratio]

        for img in image_list:
            path = img.get("path")
            if path and os.path.exists(path):
                try:
                    with Image.open(path) as i:
                        w, h = i.width, i.height

                        # 🌟 修复: 严谨解析 upscale_factor，防止 "None" 导致崩溃
                        factor_str = str(self.upscale_factor).lower()
                        if factor_str not in ["none", "null", "", "false", "0", "1", "1x"]:
                            try:
                                factor = int(factor_str.replace("x", ""))
                                w *= factor
                                h *= factor
                            except ValueError:
                                pass

                        if w % 2: w += 1
                        if h % 2: h += 1
                        return w, h
                except Exception:
                    continue
        return 1920, 1080

    def _generate_cover_image(self, first_image_path: str) -> None:
        try:
            cover_path = self.project_dir / "cover.png"
            with Image.open(first_image_path) as img:
                base_width = 512
                w_percent = base_width / float(img.size[0])
                h_size = int(float(img.size[1]) * w_percent)
                img_resized = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
                img_resized.save(cover_path, "PNG")
            self.cover_generated = True
        except Exception as e:
            print(f"❌ 生成封面失败: {e}")
            self.cover_generated = False

    def _process_image(self, src_path: str, canvas_w: int, canvas_h: int) -> Optional[Dict]:
        src = Path(src_path)
        if not src.exists():
            return None

        # 🌟 修复: 严谨解析 upscale_factor，防止 "None" 导致崩溃
        factor_str = str(self.upscale_factor).lower()
        if factor_str in ["none", "null", "", "false", "0", "1", "1x"]:
            factor_str = "1x"

        stem = src.stem
        target_name = src.name
        if factor_str != "1x":
            target_name = f"{stem}_upscaled.png"

        target_path = self.assets_dir / target_name

        if not target_path.exists():
            if factor_str == "1x":
                if hasattr(self, 'counter_lock'):
                    with self.counter_lock:
                        self.skipped_count += 1
                else:
                    self.skipped_count += 1

                try:
                    shutil.copy2(str(src), str(target_path))
                except Exception:
                    return None
            else:
                if hasattr(self, 'counter_lock'):
                    with self.counter_lock:
                        self.need_upscale_count += 1
                else:
                    self.need_upscale_count += 1

                try:
                    factor_val = int(factor_str.replace("x", ""))
                except ValueError:
                    factor_val = 1

                success = False

                # ==== 核心优化：智能跳过 AI 放大 ====
                skip_ai = False
                try:
                    with Image.open(str(src)) as img:
                        # 如果原图短边已经大于等于 1000 像素 (如 SDXL 直出图)
                        # 则完全没必要使用极慢的 AI 放大，直接走传统极速高质量放大
                        if min(img.width, img.height) >= 1000:
                            skip_ai = True
                except:
                    pass

                if factor_val > 1:
                    if not skip_ai and self.ncnn_exe and self.model_dir_path:
                        success = self._ncnn_upscale(src, target_path, factor_val)

                    if not success:
                        # 传统极速高质量插值算法 (Lanczos-4) 备用保底
                        success = self._pillow_resize(src, target_path, factor_val)

                if success:
                    if hasattr(self, 'counter_lock'):
                        with self.counter_lock:
                            self.actual_upscaled += 1
                    else:
                        self.actual_upscaled += 1
                else:
                    return None

        try:
            with Image.open(str(target_path)) as img:
                final_w, final_h = img.width, img.height
        except Exception:
            return None

        # 安全的并发写保护 (防重入生成封面)
        if not getattr(self, 'cover_generated', False):
            if hasattr(self, 'cover_lock'):
                with self.cover_lock:
                    if not self.cover_generated:
                        self._generate_cover_image(str(target_path))
            else:
                self._generate_cover_image(str(target_path))

        return {
            "id": self._gen_id(),
            "path": self._to_win_path(target_path),
            "width": final_w,
            "height": final_h,
            "name": target_name,
        }

    def _ncnn_upscale(self, src_path: Path, target_path: Path, factor: int) -> bool:
        try:
            cmd = [
                self.ncnn_exe, "-i", str(src_path), "-o", str(target_path),
                "-s", str(factor), "-m", self.model_dir_path,
                "-n", self.model_type, "-g", "0", "-f", "png",
            ]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, startupinfo=startupinfo)
            return result.returncode == 0
        except Exception:
            return False

    def _pillow_resize(self, src_path: Path, target_path: Path, factor: int) -> bool:
        try:
            with Image.open(str(src_path)) as img:
                new_size = (img.width * factor, img.height * factor)
                img.resize(new_size, Image.Resampling.LANCZOS).save(str(target_path), quality=95)
                return True
        except Exception:
            return False

    def _update_root_meta_info(self, meta_data: Dict) -> None:
        root_meta_path = Path(self.draft_root_dir) / "root_meta_info.json"
        temp_meta_path = Path(self.draft_root_dir) / f"root_meta_info_{uuid.uuid4().hex}.tmp"

        data = {"all_draft_store": []}
        if root_meta_path.exists():
            try:
                with open(root_meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"读取 root meta 警告: {e}")

        if "all_draft_store" not in data:
            data["all_draft_store"] = []

        new_item = meta_data.copy()
        new_item["draft_fold_path"] = self._to_win_path(self.project_dir)
        new_item["draft_root_path"] = self._to_win_path(self.draft_root_dir)

        if self.cover_generated:
            new_item["draft_cover"] = self._to_win_path(self.project_dir / "cover.png")
        else:
            new_item["draft_cover"] = ""

        data["all_draft_store"] = [item for item in data["all_draft_store"] if
                                   item.get("draft_id") != new_item["draft_id"]]
        data["all_draft_store"].insert(0, new_item)

        try:
            with open(temp_meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if root_meta_path.exists():
                os.replace(str(temp_meta_path), str(root_meta_path))
            else:
                temp_meta_path.rename(root_meta_path)
            os.utime(str(root_meta_path), None)
        except Exception as e:
            print(f"写入 root meta 失败: {e}")
            if temp_meta_path.exists():
                temp_meta_path.unlink()

    def _create_keyframe_track(self, prop_type: str, start_val: float, end_val: float, duration_us: int) -> Dict:
        kf_id_start = self._gen_id()
        kf_id_end = self._gen_id()
        return {
            "id": self._gen_id(),
            "keyframe_list": [
                {
                    "curve_id": "", "graph_id": "", "id": kf_id_start,
                    "left_control": {"x": 0.17, "y": 0.17}, "right_control": {"x": 0.83, "y": 0.83},
                    "property_type": prop_type, "time_offset": 0, "values": [float(start_val)],
                },
                {
                    "curve_id": "", "graph_id": "", "id": kf_id_end,
                    "left_control": {"x": 0.17, "y": 0.17}, "right_control": {"x": 0.83, "y": 0.83},
                    "property_type": prop_type, "time_offset": duration_us, "values": [float(end_val)],
                },
            ],
            "property_type": prop_type,
        }

    def _get_official_text_template(self, effect_id: str = "") -> Dict:
        """
        官方字幕素材模板
        """
        return {
            "add_type": 2,
            "alignment": 1,
            "background_alpha": 1.0,
            "background_color": "#000000",
            "background_height": 0.14,
            "background_horizontal_offset": 0.0,
            "background_round_radius": 0.0,
            "background_style": 0,
            "background_vertical_offset": 0.0,
            "background_width": 0.14,
            "base_content": "",
            "bold_width": 0.0,
            "border_alpha": 1.0,
            "border_color": "#ffffff",
            "border_width": 0.08,
            "caption_template_info": {
                "category_id": "", "category_name": "",
                "effect_id": effect_id,
                "is_new": False, "path": "", "request_id": "",
                "resource_id": effect_id,
                "resource_name": "", "source_platform": 0
            },
            "check_flag": 15,
            "combo_info": {"text_templates": []},
            "content": "",
            "fixed_height": -1.0,
            "fixed_width": -1.0,
            "font_category_id": "",
            "font_category_name": "",
            "font_id": "",
            "font_name": "",
            "font_path": "",
            "font_resource_id": "",
            "font_size": self.SUBTITLE_FONT_SIZE,
            "font_source_platform": 0,
            "font_team_id": "",
            "font_title": "none",
            "font_url": "",
            "fonts": [],
            "force_apply_line_max_width": False,
            "global_alpha": 1.0,
            "group_id": "",
            "has_shadow": False,
            "id": "",
            "initial_scale": 1.0,
            "inner_padding": -1.0,
            "is_rich_text": False,
            "italic_degree": 0,
            "ktv_color": "",
            "language": "",
            "layer_weight": 1,
            "letter_spacing": 0.0,
            "line_feed": 1,
            "line_max_width": 0.82,
            "line_spacing": 0.02,
            "multi_language_current": "none",
            "name": "",
            "original_size": [],
            "preset_category": "",
            "preset_category_id": "",
            "preset_has_set_alignment": False,
            "preset_id": "",
            "preset_index": 0,
            "preset_name": "",
            "recognize_task_id": "",
            "recognize_type": 0,
            "relevance_segment": [],
            "shadow_alpha": 0.9,
            "shadow_angle": -45.0,
            "shadow_color": "",
            "shadow_distance": 5.0,
            "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678928},
            "shadow_smoothing": 0.45,
            "shape_clip_x": False,
            "shape_clip_y": False,
            "source_from": "",
            "style_name": "",
            "sub_type": 0,
            "subtitle_keywords": None,
            "subtitle_template_original_fontsize": 0.0,
            "text_alpha": 1.0,
            "text_color": "#000000",
            "text_curve": None,
            "text_preset_resource_id": "",
            "text_size": 30,
            "text_to_audio_ids": [],
            "tts_auto_update": False,
            "type": "subtitle",
            "typesetting": 0,
            "underline": False,
            "underline_offset": 0.22,
            "underline_width": 0.05,
            "use_effect_default_color": True,
            "words": {"end_time": [], "start_time": [], "text": []}
        }

    def generate_draft(
            self,
            audio_path: Optional[str],
            image_list: List[Dict],
            subtitles: Optional[List[Dict]] = None,
            bgm_path: Optional[str] = None,
            bgm_volume: float = 0.2,
            subtitle_effect_id: str = "",
            **kwargs
    ) -> str:
        """
        生成剪映草稿，支持 BGM 和字幕花字
        """
        self.total_images = len(image_list)
        canvas_w, canvas_h = self._determine_canvas_size(image_list)

        # 0. 预先计算主音频时长
        master_audio_duration_us = 0
        if audio_path and os.path.exists(audio_path):
            if MUTAGEN_AVAILABLE:
                try:
                    af = File(audio_path)
                    if af and af.info:
                        master_audio_duration_us = int(af.info.length * 1_000_000)
                except Exception:
                    pass

        if master_audio_duration_us == 0:
            total_us = 0
            for img in image_list:
                if 'duration_us' in img:
                    total_us += img['duration_us']
                else:
                    total_us += int(float(img.get("duration", 3.0)) * 1_000_000)
            master_audio_duration_us = total_us

        # 创建素材容器
        canvas_color_id = self._gen_id()
        materials: Dict[str, List] = {
            "videos": [], "audios": [], "canvases": [], "speeds": [],
            "sound_channel_mappings": [], "texts": [], "material_animations": [],
            "effects": [], "beats": [], "vocal_separations": [],
        }

        materials["canvases"].append({
            "id": canvas_color_id, "type": "canvas_color", "color": "#000000",
        })

        video_track = {"id": self._gen_id(), "type": "video", "segments": []}
        tracks = [video_track]

        # ================= 核心优化：多线程并发预处理图片 =================
        self.cover_lock = threading.Lock()
        self.counter_lock = threading.Lock()

        processed_images_map = {}
        # 去重处理，防止相同路径的图片被重复放入线程池执行
        unique_paths = list(set([img_data["path"] for img_data in image_list if img_data.get("path")]))

        # 智能匹配最佳线程数 (上限4防止显存爆炸)
        max_workers = min(4, os.cpu_count() or 4)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_image, path, canvas_w, canvas_h): path
                for path in unique_paths
            }
            for future in concurrent.futures.as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    processed_images_map[path] = future.result()
                except Exception as e:
                    print(f"处理图片异常 {path}: {e}")
                    processed_images_map[path] = None
        # ==================================================================

        # ---------------------------------------------------------------------
        # 1. 视频轨道处理 (Video Track) - 【绝对基准】
        # ---------------------------------------------------------------------
        current_frame_cursor = 0

        for img_data in image_list:
            if not img_data.get("path"):
                self.failed_count += 1
                continue

            # 直接从内存中获取已极速处理完毕的图片结果
            processed = processed_images_map.get(img_data["path"])
            if not processed:
                self.failed_count += 1
                continue

            # 时长计算：使用新的 _us_to_frames (int(x+0.5)) 保证符合四舍五入
            if "duration_us" in img_data:
                raw_us = int(img_data["duration_us"])
                clip_frames = self._us_to_frames(raw_us)
            else:
                # 兼容旧逻辑，同样使用 +0.5 舍入
                clip_frames = int(img_data.get("duration", 3.0) * self.FPS + 0.5)

            if clip_frames < 1: clip_frames = 1

            start_us = self._get_time_at_frame(current_frame_cursor)
            end_us = self._get_time_at_frame(current_frame_cursor + clip_frames)
            duration_us = end_us - start_us
            current_frame_cursor += clip_frames

            # Speed & Video Material
            segment_speed_id = self._gen_id()
            materials["speeds"].append({
                "id": segment_speed_id, "mode": 0, "speed": 1.0, "type": "speed"
            })

            video_entry = {
                "id": processed["id"], "path": processed["path"], "duration": 10800000000,
                "type": "photo", "name": processed["name"], "width": processed["width"], "height": processed["height"],
                "check_flag": 63487,
                "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                         "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
                "source": 0, "has_audio": False, "is_copyright": False, "picture_from": "none", "team_id": "",
                "local_material_id": "",
            }
            materials["videos"].append(video_entry)

            # --- 关键帧计算 ---
            base_scale = 1.0
            common_keyframes = []
            static_scale = base_scale
            static_x_pixel = 0.0
            static_y_pixel = 0.0

            if self.keyframe_settings:
                start_vals, end_vals = calculate_keyframe_values(
                    self.keyframe_settings, base_scale=base_scale,
                    base_x=0.0, base_y=0.0, canvas_w=canvas_w, canvas_h=canvas_h, randomize=True,
                )

                def normalize_x(px):
                    return float(px) / float(canvas_w)

                def normalize_y(px):
                    return float(px) / float(canvas_h)

                s_scale = start_vals["scale"]
                e_scale = end_vals["scale"]

                s_x_norm = normalize_x(start_vals["x"])
                e_x_norm = normalize_x(end_vals["x"])

                s_y_norm = normalize_y(start_vals["y"])
                e_y_norm = normalize_y(end_vals["y"])

                if abs(s_scale - e_scale) > 0.001:
                    common_keyframes.append(self._create_keyframe_track("KFTypeScale", s_scale, e_scale, duration_us))
                else:
                    static_scale = s_scale

                if abs(s_x_norm - e_x_norm) > 0.00001:
                    common_keyframes.append(
                        self._create_keyframe_track("KFTypePositionX", s_x_norm, e_x_norm, duration_us))
                else:
                    static_x_pixel = start_vals["x"]

                if abs(s_y_norm - e_y_norm) > 0.00001:
                    common_keyframes.append(
                        self._create_keyframe_track("KFTypePositionY", s_y_norm, e_y_norm, duration_us))
                else:
                    static_y_pixel = start_vals["y"]

            final_static_x = float(static_x_pixel) / float(canvas_w)
            final_static_y = float(static_y_pixel) / float(canvas_h)

            segment = {
                "id": self._gen_id(),
                "material_id": processed["id"],
                "source_timerange": {"start": 0, "duration": duration_us},
                "target_timerange": {"start": start_us, "duration": duration_us},
                "clip": {
                    "alpha": 1.0,
                    "flip": {"horizontal": False, "vertical": False},
                    "rotation": 0.0,
                    "scale": {"x": static_scale, "y": static_scale},
                    "transform": {"x": final_static_x, "y": final_static_y},
                },
                "common_keyframes": common_keyframes,
                "extra_material_refs": [canvas_color_id, segment_speed_id],
                "hdr_settings": {"intensity": 1.0},
                "enable_adjust": True,
                "render_index": 0,
                "uniform_scale": {"on": True, "value": 1.0},
            }
            video_track["segments"].append(segment)

        # ---------------------------------------------------------------------
        # 2. 全局时长 (Total Frames)
        # ---------------------------------------------------------------------
        # 【基准】以视频轨道的总帧数作为整个草稿的“绝对时长”，所有其他轨道向此对齐
        total_video_frames = current_frame_cursor
        final_duration = self._get_time_at_frame(total_video_frames)

        # ---------------------------------------------------------------------
        # 3. 字幕轨道 (Subtitle Track) - 【磁吸对齐】
        # ---------------------------------------------------------------------
        if subtitles:
            text_track = {"id": self._gen_id(), "type": "text", "segments": []}
            valid_sub_count = 0
            sub_render_index = 14000

            num_subs = len(subtitles)
            for idx, sub in enumerate(subtitles):
                try:
                    raw_start_us = int(sub["start_us"])
                    raw_end_us = int(sub["end_us"])

                    # 1. 转换帧数 (使用四舍五入)
                    s_frames = self._us_to_frames(raw_start_us)
                    e_frames = self._us_to_frames(raw_end_us)

                    if e_frames <= s_frames: e_frames = s_frames + 1

                    # 2. 【核心】最后一条字幕的磁吸逻辑
                    is_last_sub = (idx == num_subs - 1)
                    if is_last_sub:
                        # 如果最后一条字幕结束帧与视频总帧数相差在 5 帧以内 (约0.16秒)
                        # 强制将其“吸附”到视频结束帧，解决源数据微小误差导致的黑屏或未对齐
                        if abs(total_video_frames - e_frames) < 5:
                            e_frames = total_video_frames

                    sub_start_us = self._get_time_at_frame(s_frames)
                    sub_end_us = self._get_time_at_frame(e_frames)

                    # 3. 移除强制截断 (允许字幕稍微超出，防止被切)
                    # 仅当完全越界且不是为了吸附时才考虑跳过，但剪映通常允许溢出
                    if sub_start_us >= final_duration: continue

                    sub_duration_us = sub_end_us - sub_start_us
                    if sub_duration_us <= 0: continue

                    text_content = sub["text"].strip()
                    if not text_content: continue
                    text_id = self._gen_id()
                    content_obj = {"text": text_content, "styles": [
                        {"fill": {"alpha": 1.0, "content": {"solid": {"color": [1.0, 1.0, 1.0]}}},
                         "font": {"path": "", "id": ""}, "size": self.SUBTITLE_FONT_SIZE,
                         "strokes": [{"content": {"solid": {"color": [0.0, 0.0, 0.0]}}, "width": 0.08}],
                         "range": [0, len(text_content)]}]}
                    text_entry = self._get_official_text_template(effect_id=subtitle_effect_id)
                    text_entry["id"] = text_id
                    text_entry["content"] = json.dumps(content_obj, ensure_ascii=False)
                    text_entry["font_size"] = self.SUBTITLE_FONT_SIZE
                    materials["texts"].append(text_entry)

                    text_track["segments"].append({
                        "id": self._gen_id(), "material_id": text_id, "source_timerange": None,
                        "target_timerange": {"start": sub_start_us, "duration": sub_duration_us},
                        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
                                 "scale": {"x": self.SUBTITLE_SCALE, "y": self.SUBTITLE_SCALE},
                                 "transform": {"x": 0.0, "y": self.SUBTITLE_Y_POS}},
                        "enable_adjust": True, "render_index": sub_render_index, "track_render_index": 0
                    })
                    valid_sub_count += 1
                    sub_render_index += 1
                except:
                    pass
            if valid_sub_count > 0: tracks.append(text_track)

        # ---------------------------------------------------------------------
        # 4. 音频处理 (Audio Track)
        # ---------------------------------------------------------------------
        if audio_path and os.path.exists(audio_path):
            aid = self._gen_id()
            real_len = final_duration
            if MUTAGEN_AVAILABLE:
                try:
                    af = File(audio_path)
                    if af and af.info:
                        file_len_us = int(af.info.length * 1_000_000)
                        # 如果文件实际长度比视频长，保留文件长度，防止音频被截断声音突变
                        # 剪映会自动处理超出 draft duration 的部分
                        if file_len_us > real_len:
                            real_len = file_len_us
                except:
                    pass

            # 无论音频文件多长，我们在轨道上的“目标时长”设置为 final_duration
            # 这样保证音频与视频视觉上对齐
            materials["audios"].append(
                {"id": aid, "path": self._to_win_path(audio_path), "duration": real_len, "type": "extract_music",
                 "name": "配音", "check_flag": 1})
            tracks.append({"id": self._gen_id(), "type": "audio", "segments": [
                {"id": self._gen_id(), "material_id": aid, "source_timerange": {"start": 0, "duration": final_duration},
                 "target_timerange": {"start": 0, "duration": final_duration}, "volume": 1.0, "render_index": 0}]})

        # ---------------------------------------------------------------------
        # 5. BGM 处理 (BGM Track) - 【循环铺满】
        # ---------------------------------------------------------------------
        if bgm_path and os.path.exists(bgm_path):
            bid = self._gen_id()
            # 1. 获取 BGM 真实时长
            bgm_duration_us = final_duration  # 默认兜底
            if MUTAGEN_AVAILABLE:
                try:
                    af = File(bgm_path)
                    if af and af.info:
                        bgm_duration_us = int(af.info.length * 1_000_000)
                except:
                    pass

            # 2. 添加 BGM 素材
            materials["audios"].append(
                {"id": bid, "path": self._to_win_path(bgm_path), "duration": bgm_duration_us, "type": "extract_music",
                 "name": "BGM", "check_flag": 1})

            # 3. 计算循环片段
            bgm_segments = []
            cursor_us = 0

            # 如果获取不到时长，或者时长极短，防止死循环，直接单次播放
            if bgm_duration_us < 100000:
                bgm_duration_us = final_duration

            while cursor_us < final_duration:
                # 计算剩余需要填充的时长
                remaining_us = final_duration - cursor_us

                # 本次片段使用的时长：取“BGM全长”和“剩余时长”中较小的一个
                clip_duration = min(bgm_duration_us, remaining_us)

                bgm_segments.append({
                    "id": self._gen_id(),
                    "material_id": bid,
                    "source_timerange": {"start": 0, "duration": clip_duration},
                    "target_timerange": {"start": cursor_us, "duration": clip_duration},
                    "volume": float(bgm_volume),
                    "render_index": 0
                })

                cursor_us += clip_duration

            tracks.append({"id": self._gen_id(), "type": "audio", "segments": bgm_segments})

        # 生成文件
        ratio_str = self.canvas_ratio.get("value", "original") if isinstance(self.canvas_ratio, dict) else (
            self.canvas_ratio if self.canvas_ratio != "original" else "original")
        content = {
            "version": 360000, "fps": self.FPS, "id": self._gen_id(), "duration": final_duration,
            "keyframes": {}, "materials": materials, "tracks": tracks,
            "config": {"adjust_max_index": 1, "maintrack_adsorb": True, "material_save_mode": 0,
                       "original_sound_last_index": 1, "record_audio_last_index": 1, "sticker_max_index": 1,
                       "subtitle_sync": True, "video_mute": False},
            "render_index_track_mode_on": True,
            "canvas_config": {"width": canvas_w, "height": canvas_h, "ratio": ratio_str}
        }
        with open(self.project_dir / "draft_content.json", "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

        now = int(time.time() * 1_000_000)
        meta = {"draft_id": self._gen_id(), "draft_name": self.project_name, "draft_new_version": "5.9.0",
                "tm_draft_create": now, "tm_draft_modified": now, "tm_duration": final_duration,
                "draft_cover": "cover.png" if self.cover_generated else "",
                "draft_root_path": self._to_win_path(self.draft_root_dir),
                "draft_fold_path": self._to_win_path(self.project_dir)}
        with open(self.project_dir / "draft_meta_info.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self._update_root_meta_info(meta)
        return str(self.project_dir)