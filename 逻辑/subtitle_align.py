import os
from datetime import time
from PIL import Image


# ==========================================
# 辅助函数
# ==========================================
def time_to_us(t: time) -> int:
    """将 datetime.time 对象转换为微秒数"""
    return (t.hour * 3600 + t.minute * 60 + t.second) * 1_000_000 + t.microsecond


def prepare_export_data(raw_data, scenes, project_dir, canvas_size=(1920, 1080)):
    """
    数据准备：基于镜头(Scene)生成导出列表。

    核心逻辑：
    1. 抛弃旧的“帧对齐”复杂计算，回归时间轴本质。
    2. 1个Scene = 1个视频片段。
    3. 片段时长 = 下一个镜头的开始时间 - 当前镜头的开始时间。
       (自动填补空隙，确保画面连贯)
    """
    if not raw_data:
        raise ValueError("原始字幕数据为空，无法导出")

    # 1. 准备占位图
    placeholder_path = os.path.join(project_dir, "placeholder.png")
    if not os.path.exists(placeholder_path):
        try:
            img = Image.new('RGB', canvas_size, color='black')
            img.save(placeholder_path)
        except Exception:
            pass

    # 2. 建立映射：字幕ID -> 原始字幕数据
    raw_map = {item['index']: item for item in raw_data}

    # 3. 整理镜头数据 (Scene Nodes)
    # 我们只关心镜头的“开始时间”和“对应的图片”
    scene_nodes = []

    for scene in scenes:
        sub_ids = scene.get('sub_ids', [])
        if not sub_ids:
            continue

        # 获取该镜头下的所有字幕
        current_subs = [raw_map.get(sid) for sid in sub_ids if raw_map.get(sid)]
        if not current_subs:
            continue

        # 排序以找到最早开始时间
        current_subs.sort(key=lambda x: time_to_us(x['start']))

        # 镜头的开始时间 = 第一句字幕的开始时间
        start_us = time_to_us(current_subs[0]['start'])

        # 镜头的结束时间（暂时记录最后一句字幕的结束，用于处理最后一个镜头）
        last_sub_end_us = time_to_us(current_subs[-1]['end'])

        # 获取图片
        imgs = scene.get('images', [])
        sel = scene.get('selected_image_index', -1)
        if imgs and 0 <= sel < len(imgs) and os.path.exists(imgs[sel]):
            img_path = imgs[sel]
        else:
            img_path = placeholder_path

        scene_nodes.append({
            'start_us': start_us,
            'fallback_end_us': last_sub_end_us,
            'img_path': img_path
        })

    # 4. 按时间排序（防止乱序）
    scene_nodes.sort(key=lambda x: x['start_us'])

    # 5. 生成最终的视频片段列表 (Images)
    images = []

    for i, node in enumerate(scene_nodes):
        # 计算当前片段的持续时长
        current_start = node['start_us']

        if i < len(scene_nodes) - 1:
            # 如果后面还有镜头，持续时长 = 下一个镜头的开始 - 当前镜头的开始
            next_start = scene_nodes[i + 1]['start_us']
            duration_us = next_start - current_start
        else:
            # 如果是最后一个镜头，持续到字幕结束 + 1秒缓冲
            duration_us = (node['fallback_end_us'] - current_start) + 1_000_000

        # 容错：防止极短片段
        if duration_us < 100000:  # 小于0.1秒
            duration_us = 100000

        images.append({
            'path': node['img_path'],
            'duration_us': duration_us,  # 传递精确微秒时长
            'start_us': current_start  # 记录绝对开始时间，供调试参考
        })

    # 6. 生成字幕列表 (Subtitles) - 原样返回，带微秒时间
    subtitles = []
    sorted_raw = sorted(raw_data, key=lambda x: time_to_us(x['start']))
    for raw in sorted_raw:
        subtitles.append({
            'start_us': time_to_us(raw['start']),
            'end_us': time_to_us(raw['end']),
            'text': raw['text'].replace('\n', ' ').strip()
        })

    # 返回结果
    return images, subtitles, 0