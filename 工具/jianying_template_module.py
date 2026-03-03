import os
import sys
import json
import uuid
import shutil
import copy
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QListWidget, QListWidgetItem, QTextEdit, QMessageBox,
    QProgressBar, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# 引入 Pillow 库用于生成封面缩略图和执行模板高清放大
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# =====================================================================
# 核心逻辑：黑盒劫持与片段循环重组引擎 (严苛时空大一统版)
# =====================================================================
class JianyingTemplateProcessor:
    """剪映模板处理引擎 (黑盒劫持法)"""

    FPS = 30.0  # ✨ 引入原生剪映基准帧率

    # 🌟 修复 1：接收 upscale_factor 参数，默认 "None" 以兼容旧的 UI 调用
    def __init__(self, template_dir, ntp_data, output_draft_dir, project_name, upscale_factor="None"):
        self.template_dir = template_dir
        self.ntp_data = ntp_data
        self.output_draft_dir = output_draft_dir
        self.project_name = project_name
        self.aligned_subtitles = None
        self.images_data = None
        self.upscale_factor = upscale_factor

    @staticmethod
    def _gen_id():
        return str(uuid.uuid4()).upper()

    def _to_win_path(self, path_str):
        return os.path.abspath(path_str).replace("/", "\\")

    def _us_to_frames(self, us: int) -> int:
        """✨ 核心修复：标准四舍五入，防止丢帧"""
        return int(us * self.FPS / 1000000.0 + 0.5)

    def _get_time_at_frame(self, frame_idx: int) -> int:
        """✨ 核心修复：将帧数转回微秒，获得绝对剪映时间"""
        return int(frame_idx * 1000000.0 / self.FPS)

    def _generate_cover_image(self, first_image_path, draft_dir):
        """自动生成标准的草稿封面缩略图"""
        if not PIL_AVAILABLE:
            return ""
        try:
            cover_path = os.path.join(draft_dir, "cover.png")
            with Image.open(first_image_path) as img:
                base_width = 512
                w_percent = base_width / float(img.size[0])
                h_size = int(float(img.size[1]) * w_percent)
                img_resized = img.resize((base_width, h_size), Image.Resampling.LANCZOS)
                img_resized.save(cover_path, "PNG")
            return "cover.png"
        except Exception as e:
            print(f"❌ 生成封面失败: {e}")
            return ""

    def process(self, log_callback):
        try:
            template_name = os.path.basename(self.template_dir)
            log_callback(f"🚀 开始处理模板: {template_name}")

            new_draft_name = f"{self.project_name}_{template_name}"
            new_draft_dir = os.path.join(self.output_draft_dir, new_draft_name)

            if os.path.exists(new_draft_dir):
                shutil.rmtree(new_draft_dir)
            os.makedirs(new_draft_dir)

            draft_json_path = os.path.join(self.template_dir, "draft_content.json")
            if not os.path.exists(draft_json_path):
                raise FileNotFoundError(f"模板目录缺失 draft_content.json: {self.template_dir}")

            with open(draft_json_path, 'r', encoding='utf-8') as f:
                content = json.load(f)

            materials = content.get('materials', {})
            tracks = content.get('tracks', [])

            scenes = self.ntp_data.get('scenes', [])
            if not scenes:
                raise ValueError("项目文件中没有找到镜头(scenes)数据！")

            # =====================================================
            # 🌟 核心修复：解析放大倍数参数
            # =====================================================
            factor_str = str(self.upscale_factor).lower()
            factor_val = 1
            if factor_str not in ["none", "null", "", "false", "0", "1", "1x"]:
                try:
                    factor_val = int(factor_str.replace("x", ""))
                except ValueError:
                    factor_val = 1

            resources_dir = os.path.join(new_draft_dir, "resources")
            if factor_val > 1 and not os.path.exists(resources_dir):
                os.makedirs(resources_dir)

            # =====================================================
            # 1. 准备项目数据 (严苛帧率计算，锁定上帝时间！)
            # =====================================================
            processed_scenes = []
            current_frame_cursor = 0

            # ✨ 核心修复：优先使用 export_manager 传入的精准计算结果
            source_images = self.images_data if self.images_data else scenes

            for s in source_images:
                img_path = s.get('path', '')
                if not img_path and 'images' in s and s['images']:
                    first_img = s['images'][0]
                    img_path = first_img.get('path', '') if isinstance(first_img, dict) else first_img
                elif 'path' in s:
                    img_path = s['path']

                if not img_path or not os.path.exists(img_path):
                    continue

                # 🌟 核心修复：执行图片放大逻辑
                if factor_val > 1 and PIL_AVAILABLE:
                    target_name = f"upscaled_{self._gen_id()}_{os.path.basename(img_path)}"
                    target_path = os.path.join(resources_dir, target_name)
                    try:
                        with Image.open(img_path) as img:
                            # 如果图片不够大，执行 Lanczos 高质量插值放大
                            if min(img.width, img.height) < 1500:
                                new_size = (img.width * factor_val, img.height * factor_val)
                                img.resize(new_size, Image.Resampling.LANCZOS).save(target_path, quality=95)
                                img_path = target_path
                            else:
                                shutil.copy2(img_path, target_path)
                                img_path = target_path
                    except Exception as e:
                        log_callback(f"⚠️ 放大图片失败: {e}，将使用原图")

                # 读取传入的精准微秒，转为帧
                raw_us = int(s.get('duration_us', s.get('duration', 3.0) * 1000000))
                clip_frames = self._us_to_frames(raw_us)
                if clip_frames < 1: clip_frames = 1

                start_us = self._get_time_at_frame(current_frame_cursor)
                end_us = self._get_time_at_frame(current_frame_cursor + clip_frames)
                duration_us = end_us - start_us

                processed_scenes.append({
                    'img_path': self._to_win_path(img_path),
                    'duration_us': duration_us,
                    'start_us': start_us,
                    'text': s.get('text', '')
                })
                current_frame_cursor += clip_frames

            # 锁定视频基准总长度 (上帝时间)
            total_video_frames = current_frame_cursor
            total_duration_us = self._get_time_at_frame(total_video_frames)
            content['duration'] = total_duration_us

            # 找主视频轨道
            main_video_track = None
            max_photo_segments = -1

            for t in tracks:
                if t['type'] == 'video':
                    photo_count = sum(
                        1 for seg in t['segments'] if self._is_photo_material(seg['material_id'], materials))
                    if photo_count > max_photo_segments:
                        max_photo_segments = photo_count
                        main_video_track = t

            if not main_video_track or not main_video_track['segments']:
                raise ValueError("未能在模板中找到有效的主视频轨道！请确保模板主轨道上有图片/视频。")

            genes = copy.deepcopy(main_video_track['segments'])
            log_callback(f"🧬 成功提取到 {len(genes)} 个视觉特效基因片段，准备循环注入...")

            # 🌟 动画剥离优化方案：建立动画材质黑名单
            anim_ids = {a['id'] for a in materials.get('material_animations', [])}

            # 重组主视频轨道
            new_segments = []
            for i, p_scene in enumerate(processed_scenes):
                gene = copy.deepcopy(genes[i % len(genes)])

                # 🌟 核心拦截：如果进入第二轮循环克隆（超出了原模板的基因数），则强制剥离所有动画
                if i >= len(genes):
                    if 'extra_material_refs' in gene:
                        gene['extra_material_refs'] = [
                            ref for ref in gene['extra_material_refs'] if ref not in anim_ids
                        ]

                new_mat_id = self._gen_id()
                new_mat = {
                    "id": new_mat_id,
                    "path": p_scene['img_path'],
                    "type": "photo",
                    "duration": 10800000000,
                    "width": 1080,
                    "height": 1920,
                    "name": os.path.basename(p_scene['img_path'])
                }
                if 'videos' not in materials: materials['videos'] = []
                materials['videos'].append(new_mat)

                gene['id'] = self._gen_id()
                gene['material_id'] = new_mat_id
                gene['target_timerange'] = {'start': p_scene['start_us'], 'duration': p_scene['duration_us']}
                gene['source_timerange'] = {'start': 0, 'duration': p_scene['duration_us']}

                if 'common_keyframes' in gene:
                    for kf_track in gene['common_keyframes']:
                        if 'keyframe_list' in kf_track and kf_track['keyframe_list']:
                            # 🌟 核心修复：强制时空锁死机制，杜绝关键帧卡在中间！

                            # 1. 强制将第一个关键帧锁定在 0 秒（绝对开头）
                            kf_track['keyframe_list'][0]['time_offset'] = 0

                            # 2. 强制将最后一个关键帧锁定在当前图片的持续时间（绝对结尾）
                            kf_track['keyframe_list'][-1]['time_offset'] = p_scene['duration_us']

                            # 3. 容错处理：如果模板中有超过2个以上的关键帧（比如中间还有缩放），按比例重新计算它们的时间
                            # 获取模板原本的总动画时长（防止分母为0）
                            orig_end_time = kf_track['keyframe_list'][-1].get('time_offset', 1) or 1
                            if len(kf_track['keyframe_list']) > 2:
                                for i in range(1, len(kf_track['keyframe_list']) - 1):
                                    # 根据当前图片的新时长，等比例缩放中间关键帧的时间点
                                    ratio = kf_track['keyframe_list'][i]['time_offset'] / orig_end_time
                                    kf_track['keyframe_list'][i]['time_offset'] = int(p_scene['duration_us'] * ratio)

                new_segments.append(gene)

            main_video_track['segments'] = new_segments

            # =====================================================
            # 2. 处理音频 (强制向视频时长看齐，一刀切断，防止尾部脱节)
            # =====================================================
            audio_path = self.ntp_data.get('audio_path', '')
            if audio_path and os.path.exists(audio_path):
                new_audio_mat_id = self._gen_id()
                materials.setdefault('audios', []).append({
                    "id": new_audio_mat_id,
                    "path": self._to_win_path(audio_path),
                    "type": "extract_music",
                    "duration": total_duration_us,
                    "name": "AI配音"
                })

                self._clean_placeholder_audio(tracks, materials)

                tracks.append({
                    "id": self._gen_id(),
                    "type": "audio",
                    "segments": [{
                        "id": self._gen_id(),
                        "material_id": new_audio_mat_id,
                        # 强行截断，杜绝脱节漂移
                        "source_timerange": {"start": 0, "duration": total_duration_us},
                        "target_timerange": {"start": 0, "duration": total_duration_us},
                        "volume": 1.0
                    }]
                })

            # 处理字幕 (传入帧数据用于磁吸对齐)
            self._process_subtitles(tracks, materials, processed_scenes, log_callback, total_duration_us,
                                    total_video_frames)

            # =====================================================
            # 🌟 核心修复：剪映调节层、特效、滤镜、贴纸 自适应铺满
            # =====================================================
            for t in tracks:
                # 常规独立轨道：特效、滤镜、贴纸、调节层
                if t['type'] in ['effect', 'filter', 'sticker', 'adjust']:
                    for seg in t['segments']:
                        # 放在最开头(小于0.5秒)的元素，自动拉伸铺满全片
                        if seg['target_timerange']['start'] < 500000:
                            seg['target_timerange']['duration'] = total_duration_us

                # 嵌套在视频轨道中的新型调节层识别
                elif t['type'] == 'video':
                    for seg in t['segments']:
                        mat_id = seg.get('material_id', '')
                        is_adjust = False

                        # 在 adjusts 字典中寻找
                        for m in materials.get('adjusts', []):
                            if m.get('id') == mat_id:
                                is_adjust = True
                                break
                        # 或者在 videos 字典中寻找 type='adjust' 的材质
                        for m in materials.get('videos', []):
                            if m.get('id') == mat_id and m.get('type') == 'adjust':
                                is_adjust = True
                                break

                        if is_adjust and seg['target_timerange'].get('start', 0) < 500000:
                            seg['target_timerange']['duration'] = total_duration_us

            # =====================================================
            # 3. 音效智能锚点对齐 & BGM 智能裁剪 (保留模板原音量)
            # =====================================================
            sfx_list = []
            for t in tracks:
                if t['type'] == 'audio':
                    valid_segments = []
                    for seg in t['segments']:
                        mat_id = seg['material_id']
                        mat_name = ""
                        for a in materials.get('audios', []):
                            if a['id'] == mat_id:
                                mat_name = a.get('name', '')
                                break

                        # 忽略刚加的配音
                        if mat_name == "AI配音":
                            valid_segments.append(seg)
                            continue

                        duration_us = seg['target_timerange']['duration']

                        # 智能区分 BGM（长）和 音效（短）
                        if duration_us > 10000000 or "bgm" in mat_name.lower() or "音乐" in mat_name:
                            # 保留原本的智能裁剪和淡出逻辑
                            start_us = seg['target_timerange']['start']
                            if start_us >= total_duration_us:
                                continue

                            if start_us + duration_us > total_duration_us:
                                keep_duration = total_duration_us - start_us
                                seg['target_timerange']['duration'] = keep_duration
                                if seg.get('source_timerange'):
                                    seg['source_timerange']['duration'] = keep_duration

                                fade_out_time = 1500000 if keep_duration > 1500000 else keep_duration
                                fade_id = self._gen_id()

                                if 'audio_fades' not in materials:
                                    materials['audio_fades'] = []

                                materials['audio_fades'].append({
                                    "id": fade_id,
                                    "type": "audio_fade",
                                    "fade_in_duration": 0,
                                    "fade_out_duration": fade_out_time
                                })

                                if 'extra_material_refs' not in seg:
                                    seg['extra_material_refs'] = []
                                seg['extra_material_refs'].append(fade_id)

                            valid_segments.append(seg)
                        else:
                            # 🔔 这是音效！先暂存在剥离列表中，准备重新锚定
                            sfx_list.append(seg)

                    t['segments'] = valid_segments

            # 4. 把刚刚暂存的音效按次序钉在新图片的开头
            if sfx_list:
                sfx_list.sort(key=lambda x: x['target_timerange']['start'])
                sfx_track = {"id": self._gen_id(), "type": "audio", "segments": []}

                for k, sfx_seg in enumerate(sfx_list):
                    # 如果音效数量比图片多，多余的音效丢弃
                    if k >= len(processed_scenes):
                        break

                    # 抓取第 k 张图片的绝对时间锚点！
                    anchor_start_us = processed_scenes[k]['start_us']
                    if anchor_start_us >= total_duration_us:
                        continue

                    # 强行改变音效在草稿里的发生时间
                    sfx_seg['target_timerange']['start'] = anchor_start_us
                    sfx_track['segments'].append(sfx_seg)

                if sfx_track['segments']:
                    tracks.append(sfx_track)

            # 提取第一张图并使用 Pillow 生成标准封面
            first_img_path = processed_scenes[0]['img_path'] if processed_scenes else ""
            cover_relative_path = ""
            if first_img_path and os.path.exists(first_img_path):
                cover_relative_path = self._generate_cover_image(first_img_path, new_draft_dir)

            # 保存草稿
            new_content_path = os.path.join(new_draft_dir, "draft_content.json")
            with open(new_content_path, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)

            now = int(time.time() * 1_000_000)
            draft_id = self._gen_id()
            meta = {
                "draft_id": draft_id,
                "draft_name": new_draft_name,
                "draft_cover": cover_relative_path,
                "tm_draft_create": now,
                "tm_draft_modified": now,
                "tm_duration": total_duration_us,
                "draft_fold_path": new_draft_dir,
                "draft_root_path": self.output_draft_dir
            }
            with open(os.path.join(new_draft_dir, "draft_meta_info.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            self._update_root_meta(meta)
            log_callback(f"✅ 成功生成矩阵草稿: {new_draft_name}\n")
            return True

        except Exception as e:
            log_callback(f"❌ 处理模板 {os.path.basename(self.template_dir)} 时出错: {str(e)}\n")
            return False

    def _is_photo_material(self, material_id, materials):
        for v in materials.get('videos', []):
            if v['id'] == material_id and v.get('type') in ['photo', 'video']:
                return True
        return False

    def _clean_placeholder_audio(self, tracks, materials):
        for t in tracks:
            if t['type'] == 'audio':
                segments_to_keep = []
                for seg in t['segments']:
                    mat_id = seg['material_id']
                    mat_name = ""
                    for a in materials.get('audios', []):
                        if a['id'] == mat_id:
                            mat_name = a.get('name', '')
                            break
                    if "配音" in mat_name or "录音" in mat_name:
                        continue
                    segments_to_keep.append(seg)
                t['segments'] = segments_to_keep

    def _process_subtitles(self, tracks, materials, scenes, log_callback, total_duration_us, total_video_frames):
        """✨ 核心修复：磁吸对齐 + 基因净化 + 强行锁死坐标"""
        text_style_gene = None
        text_segment_gene = None

        for t in tracks:
            if t['type'] == 'text':
                valid_segments = []
                for seg in t['segments']:
                    mat_id = seg['material_id']
                    mat_text = ""
                    mat_ref = None
                    for txt_mat in materials.get('texts', []):
                        if txt_mat['id'] == mat_id:
                            mat_ref = txt_mat
                            try:
                                content_obj = json.loads(txt_mat['content'])
                                mat_text = content_obj.get('text', '')
                            except:
                                pass
                            break

                    if not text_style_gene and ("字幕" in mat_text or "sub" in mat_text.lower()):
                        text_style_gene = copy.deepcopy(mat_ref)
                        text_segment_gene = copy.deepcopy(seg)
                        log_callback(f"🎯 成功锁定模板里的精准字幕锚点: '{mat_text}'")
                        continue

                    if seg['target_timerange']['start'] < 500000:
                        seg['target_timerange']['duration'] = total_duration_us

                    valid_segments.append(seg)
                t['segments'] = valid_segments

        if not text_style_gene:
            for t in tracks:
                if t['type'] == 'text' and t['segments']:
                    text_segment_gene = copy.deepcopy(t['segments'][0])
                    mat_id = text_segment_gene['material_id']
                    for txt_mat in materials.get('texts', []):
                        if txt_mat['id'] == mat_id:
                            text_style_gene = copy.deepcopy(txt_mat)
                            break
                    t['segments'].pop(0)
                    break

        if not text_style_gene or not text_segment_gene:
            log_callback("⚠️ 模板中未找到任何文本，新视频将没有字幕。")
            return

        new_text_track = {"id": self._gen_id(), "type": "text", "segments": []}
        sub_render_index = 14000

        sub_source = []
        # ✨ 完美音频对齐：优先使用由 export_manager 透传进来的精确对齐时间轴
        if self.aligned_subtitles:
            for sub in self.aligned_subtitles:
                sub_source.append({
                    'text': sub['text'],
                    'start_us': sub['start_us'],
                    'end_us': sub['end_us']
                })
        else:
            for s in scenes:
                sub_source.append({
                    'text': s['text'],
                    'start_us': s['start_us'],
                    'end_us': s['start_us'] + s['duration_us']
                })

        num_subs = len(sub_source)
        for idx, sub_info in enumerate(sub_source):
            new_text = sub_info['text'].strip()
            if not new_text: continue

            raw_start_us = int(sub_info['start_us'])
            raw_end_us = int(sub_info['end_us'])

            # =====================================================
            # ✨ 磁吸对齐逻辑 (严格按照帧数转化，无缝贴合音频)
            # =====================================================
            s_frames = self._us_to_frames(raw_start_us)
            e_frames = self._us_to_frames(raw_end_us)

            if e_frames <= s_frames: e_frames = s_frames + 1

            is_last_sub = (idx == num_subs - 1)
            if is_last_sub:
                # 磁吸：如果离结尾不到5帧，强制贴合结尾
                if abs(total_video_frames - e_frames) < 5:
                    e_frames = total_video_frames

            sub_start_us = self._get_time_at_frame(s_frames)
            sub_end_us = self._get_time_at_frame(e_frames)

            if sub_start_us >= total_duration_us: continue
            sub_duration_us = sub_end_us - sub_start_us
            if sub_duration_us <= 0: continue

            # 构建新材质
            new_txt_mat = copy.deepcopy(text_style_gene)
            new_txt_mat['id'] = self._gen_id()

            try:
                content_obj = json.loads(new_txt_mat['content'])
                content_obj['text'] = new_text

                text_len = len(new_text)
                if 'styles' in content_obj:
                    for style in content_obj['styles']:
                        if 'range' in style and len(style['range']) == 2:
                            style['range'] = [0, text_len]

                if 'inline_styles' in content_obj:
                    for inline_style in content_obj['inline_styles']:
                        if 'range' in inline_style and len(inline_style['range']) == 2:
                            inline_style['range'] = [0, text_len]

                new_txt_mat['content'] = json.dumps(content_obj, ensure_ascii=False)
            except:
                pass

            materials['texts'].append(new_txt_mat)

            # 构建新片段
            new_seg = copy.deepcopy(text_segment_gene)
            new_seg['id'] = self._gen_id()
            new_seg['material_id'] = new_txt_mat['id']
            new_seg['render_index'] = sub_render_index
            sub_render_index += 1

            # 强制套用精准时间
            new_seg['target_timerange'] = {"start": sub_start_us, "duration": sub_duration_us}
            new_seg['source_timerange'] = None

            # =====================================================
            # ✨ 净化基因与强制锁死排版坐标！杜绝文字跑到中间
            # =====================================================
            # 1. 清理捣乱的关键帧
            if 'common_keyframes' in new_seg:
                filtered_keyframes = []
                for kf_track in new_seg['common_keyframes']:
                    # 强行剔除模板里可能包含的“位置偏移”关键帧，防止字跑到中间
                    if kf_track.get('property_type') in ['KFTypePositionY', 'KFTypePositionX']:
                        continue
                    if 'keyframe_list' in kf_track and kf_track['keyframe_list']:
                        kf_track['keyframe_list'][-1]['time_offset'] = sub_duration_us
                    filtered_keyframes.append(kf_track)
                new_seg['common_keyframes'] = filtered_keyframes

            # 2. 强行覆写绝对排版坐标 (继承缩放等效果，但位置必为底部居中 -0.85)
            old_scale = new_seg.get('clip', {}).get('scale', {"x": 1.0, "y": 1.0})
            old_alpha = new_seg.get('clip', {}).get('alpha', 1.0)
            old_rotation = new_seg.get('clip', {}).get('rotation', 0.0)

            new_seg['clip'] = {
                "alpha": old_alpha,
                "flip": {"horizontal": False, "vertical": False},
                "rotation": old_rotation,
                "scale": old_scale,
                "transform": {"x": 0.0, "y": -0.85}
            }

            new_text_track['segments'].append(new_seg)

        tracks.append(new_text_track)

    def _update_root_meta(self, meta_data):
        root_meta_path = os.path.join(self.output_draft_dir, "root_meta_info.json")
        data = {"all_draft_store": []}
        if os.path.exists(root_meta_path):
            try:
                with open(root_meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except:
                pass

        if "all_draft_store" not in data:
            data["all_draft_store"] = []

        data["all_draft_store"].insert(0, meta_data)

        temp_path = root_meta_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, root_meta_path)


# =====================================================================
# 后台工作线程
# =====================================================================
class TemplateMatrixWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal()

    def __init__(self, ntp_path, templates_dirs, output_draft_root):
        super().__init__()
        self.ntp_path = ntp_path
        self.templates_dirs = templates_dirs
        self.output_draft_root = output_draft_root

    def run(self):
        try:
            self.log_signal.emit("📦 正在解析项目数据文件...")
            with open(self.ntp_path, 'r', encoding='utf-8') as f:
                ntp_data = json.load(f)

            project_name = ntp_data.get('name', '未命名推文')
            total = len(self.templates_dirs)

            for i, t_dir in enumerate(self.templates_dirs):
                self.log_signal.emit(f"----------------------------------------")
                processor = JianyingTemplateProcessor(t_dir, ntp_data, self.output_draft_root, project_name)
                processor.process(lambda msg: self.log_signal.emit(msg))
                self.progress_signal.emit(i + 1, total)

            self.log_signal.emit("🎉 所有模板裂变生成完毕！请打开剪映查看。")
        except Exception as e:
            self.log_signal.emit(f"❌ 严重错误: {e}")
        finally:
            self.finished_signal.emit()


# =====================================================================
# 外挂独立 UI 界面
# =====================================================================
class TemplateMatrixWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎬 剪映模板矩阵裂变系统")
        self.resize(750, 600)
        self.drafts_root = os.path.join(os.path.expanduser("~"), "AppData", "Local", "JianyingPro", "User Data",
                                        "Projects", "com.lveditor.draft")
        if not os.path.exists(self.drafts_root):
            self.drafts_root = r"D:\APP\剪映\JianyingPro Drafts"

        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #ffffff; font-family: "Microsoft YaHei"; }
            QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; color: #4fc3f7; font-weight: bold; }
            QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #444; border-color: #1a73e8; }
            QListWidget, QTextEdit { background-color: #252526; border: 1px solid #555; border-radius: 4px; padding: 5px; }
            QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #1a73e8; }
        """)

        main_layout = QVBoxLayout(self)

        grp_proj = QGroupBox("1. 选择小说推文项目 (.ntp)")
        lay_proj = QHBoxLayout(grp_proj)
        self.lbl_proj = QLabel("未选择任何项目")
        self.lbl_proj.setStyleSheet("color: #ccc;")
        btn_sel_proj = QPushButton("📁 浏览项目")
        btn_sel_proj.clicked.connect(self.select_project)
        lay_proj.addWidget(self.lbl_proj, stretch=1)
        lay_proj.addWidget(btn_sel_proj)
        main_layout.addWidget(grp_proj)

        grp_tpl = QGroupBox("2. 勾选需要裂变的剪映模板")
        lay_tpl = QVBoxLayout(grp_tpl)

        lay_tpl_ctrl = QHBoxLayout()
        self.lbl_root = QLabel(f"草稿目录: {self.drafts_root}")
        self.lbl_root.setStyleSheet("font-size: 11px; color: #888;")
        btn_change_root = QPushButton("⚙️ 更改草稿路径")
        btn_change_root.clicked.connect(self.change_draft_root)
        btn_refresh = QPushButton("🔄 刷新列表")
        btn_refresh.clicked.connect(self.load_templates)
        lay_tpl_ctrl.addWidget(self.lbl_root, stretch=1)
        lay_tpl_ctrl.addWidget(btn_change_root)
        lay_tpl_ctrl.addWidget(btn_refresh)
        lay_tpl.addLayout(lay_tpl_ctrl)

        self.list_tpl = QListWidget()
        lay_tpl.addWidget(self.list_tpl)
        main_layout.addWidget(grp_tpl, stretch=1)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        main_layout.addWidget(self.txt_log, stretch=1)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        main_layout.addWidget(self.progress)

        self.btn_run = QPushButton("🚀 一键生成矩阵")
        self.btn_run.setFixedHeight(45)
        self.btn_run.setStyleSheet(
            "QPushButton { background-color: #1565c0; font-size: 15px; font-weight: bold; } QPushButton:hover { background-color: #1976d2; }")
        self.btn_run.clicked.connect(self.start_matrix)
        main_layout.addWidget(self.btn_run)

        self.ntp_path = ""
        self.load_templates()

    def select_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择项目", "", "小说推文项目 (*.ntp)")
        if path:
            self.ntp_path = path
            self.lbl_proj.setText(os.path.basename(path))

    def change_draft_root(self):
        folder = QFileDialog.getExistingDirectory(self, "选择剪映草稿总目录", self.drafts_root)
        if folder:
            self.drafts_root = folder
            self.lbl_root.setText(f"草稿目录: {folder}")
            self.load_templates()

    def load_templates(self):
        self.list_tpl.clear()
        if not os.path.exists(self.drafts_root):
            self.list_tpl.addItem("未找到草稿目录，请手动更改路径...")
            return

        try:
            for d in os.listdir(self.drafts_root):
                full_path = os.path.join(self.drafts_root, d)
                if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, "draft_content.json")):
                    item = QListWidgetItem(f"📄 {d}")
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    item.setData(Qt.ItemDataRole.UserRole, full_path)
                    self.list_tpl.addItem(item)
        except Exception as e:
            self.list_tpl.addItem(f"读取失败: {e}")

    def log(self, msg):
        self.txt_log.append(msg)
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    def start_matrix(self):
        if not self.ntp_path:
            QMessageBox.warning(self, "提示", "请先选择顶部的 .ntp 项目文件！")
            return

        selected_tpls = []
        for i in range(self.list_tpl.count()):
            item = self.list_tpl.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_tpls.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected_tpls:
            QMessageBox.warning(self, "提示", "请至少勾选一个剪映模板！")
            return

        self.btn_run.setEnabled(False)
        self.txt_log.clear()
        self.progress.setMaximum(len(selected_tpls))
        self.progress.setValue(0)

        self.worker = TemplateMatrixWorker(self.ntp_path, selected_tpls, self.drafts_root)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self):
        self.btn_run.setEnabled(True)
        QMessageBox.information(self, "完成", "矩阵生成完毕，请打开剪映客户端查看效果！")


# 测试入口
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = TemplateMatrixWidget()
    window.show()
    sys.exit(app.exec())