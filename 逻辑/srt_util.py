import re
from datetime import time

# --- 辅助工具：本地SRT解析器 ---
class LocalSRTParser:
    @staticmethod
    def parse(filepath):
        """
        解析SRT文件，返回包含完整时间信息的列表。
        每个元素包含：index, start, end, duration, text, prompt, status, images, selected_image_index, roles
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(filepath, 'r', encoding='gbk') as f:
                    content = f.read()
            except:
                raise ValueError("无法读取文件，请确保编码为 UTF-8 或 GBK")

        content = content.replace('\r\n', '\n')
        pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\n\d+\n|$)',
                             re.DOTALL)
        matches = pattern.findall(content.strip() + '\n\n')

        result = []
        for m in matches:
            idx = int(m[0])
            start_str = m[1]
            end_str = m[2]
            text = m[3].replace('\n', ' ').strip()

            # 将字符串时间转换为 datetime.time 对象
            def str_to_time(t_str):
                h, m, s_ms = t_str.split(':')
                s, ms = s_ms.split(',')
                return time(int(h), int(m), int(s), int(ms) * 1000)  # 微秒

            start_time = str_to_time(start_str)
            end_time = str_to_time(end_str)

            # 计算时长（秒）
            def time_to_seconds(t):
                return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000.0

            dur = max(0.1, time_to_seconds(end_time) - time_to_seconds(start_time))

            result.append({
                "index": idx,
                "start": start_time,          # datetime.time 对象
                "end": end_time,              # datetime.time 对象
                "duration": round(dur, 2),
                "text": text,
                "prompt": "",
                "status": "等待处理",
                "images": [],
                "selected_image_index": -1,
                "roles": []
            })

        if not result:
            raise ValueError("字幕格式有误，未找到有效的对话内容")
        return result