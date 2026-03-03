from google import genai
import pysrt
import json
import time
import logging  # 🌟 完美修复：引入 logging 替代 print，防止无控制台模式下闪退
import re


class GeminiLogic:
    def __init__(self, api_key):
        """
        初始化Gemini接口
        :param api_key: Google Gemini API Key
        """
        if not api_key:
            raise ValueError("API Key 不能为空")

        # 初始化新版客户端
        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-2.0-flash'  # 使用较快且效果好的模型

    def parse_subtitle(self, srt_path):
        """
        解析SRT字幕文件
        :return: 返回一个列表，包含每一句的序号、开始时间、结束时间、文本
        """
        subs = pysrt.open(srt_path)
        data = []
        for sub in subs:
            # 计算时长(秒)
            duration = sub.duration.seconds + sub.duration.milliseconds / 1000.0
            data.append({
                "index": sub.index,
                "start": sub.start.to_time(),
                "end": sub.end.to_time(),
                "duration": duration,
                "text": sub.text,
                "prompt": "",  # 待生成的提示词
                "status": "等待处理"
            })
        return data

    def analyze_character_and_scene(self, subtitle_data):
        """
        核心功能：推理分镜和提示词
        🌟 优化：采用滑动窗口批处理机制，避免长篇小说一次性发送导致大模型输出Token截断和JSON解析报错
        """

        # 🌟 核心修复：植入核心主语强制法则、完整名词法则，彻底切断吞词和变形源头
        # 🌟 并且植入【画风隔离法则】，阻断大模型自我发散写实风格描述
        system_prompt = """
        【最高指令】：你是一个毫无感情的 Stable Diffusion 提示词处理器。
        任务：
        1. 分析小说文本，提炼每一个画面的分镜描述。
        2. 为每一句字幕生成【纯英文】的画面描述提示词（Prompt）。绝对不要输出任何中文解释、[CN]、[EN]等标签前缀。
        3. 【核心主语与名词法则 - 必须严格遵守】：
           - 任何人物描述【必须】放在最开头，并包含核心主语名词。
           - 若画面有一名女性，必须写 `1girl, solo, woman`；一名男性必须写 `1boy, solo, man`；一男一女写 `1boy, 1girl, couple` 等。绝对不能省略性别主语名词！
           - 描述物品或服饰时，【必须】写出完整的名词实体（如 `red high heels` 绝不能缩写成 `red high`；`red haute couture dress` 绝不能缩写成 `red haute couture`）。
        4. 【画风隔离法则 - 绝对禁止违背】：
           - 你只需进行纯粹客观的内容和动作描述。
           - 绝对禁止在提示词中输出任何关于画风、材质、渲染方式的词汇（严禁使用如：photorealistic, realistic, 3d render, photography, cinematic lighting, real life, 8k resolution 等词汇）！画风将由外部系统统一控制。
        5. 提示词格式：核心主语名词, 人物外貌与衣着特征描述(发型,眼色,服装等), 动作描述, 环境背景描述, 灯光角度. (全部使用纯英文短语，用英文半角逗号分隔，禁止使用完整的英文句子)。
        6. 【致命警告】：
           - 绝对禁止在 prompt 中出现任何中文字符！
           - 绝对禁止产生空的主语或空的括号结构，如 `(, 25 years old)`，必须带上主语写成 `(1girl, 25 years old, woman...)`。

        请直接返回纯JSON格式，格式必须如下（不要包含任何Markdown标记如```json）：
        [
            {"index": 1, "prompt": "1boy, solo, man, short black hair, brown eyes, white shirt, dark blue jeans, tired expression, tearing over a wall at night, close-up"},
            {"index": 2, "prompt": "1girl, solo, woman, long curly dark brown hair, fair skin, red haute couture dress, red lips makeup, elegant posture, powerful aura"}
        ]
        """

        prompt_map = {}
        batch_size = 40  # 每次最多向 AI 提交 40 句话，绝对保证输出的 JSON 不会被截断
        total = len(subtitle_data)

        for i in range(0, total, batch_size):
            batch = subtitle_data[i:i + batch_size]
            batch_text = "\n".join([f"{item['index']}. {item['text']}" for item in batch])

            retry_count = 0
            while retry_count < 3:
                try:
                    # 使用新版 SDK 调用生成内容，加上当前批次的标识
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=f"{system_prompt}\n\n小说内容(批次 {i + 1} 至 {min(i + batch_size, total)}):\n{batch_text}"
                    )

                    # 清洗数据，去除可能的markdown标记
                    text_result = response.text.replace("```json", "").replace("```", "")
                    json_result = json.loads(text_result)

                    # 提取当前批次的提示词
                    for item in json_result:
                        idx = item.get('index')
                        prompt_en = item.get('prompt', '')
                        if prompt_en:
                            # 🌟 进阶正则清洗：杀掉中文，修复所有断层括号和挂空逗号
                            prompt_en = re.sub(r'[\u4e00-\u9fa5]+', '', prompt_en)  # 移除中文字符
                            prompt_en = re.sub(r'\[(?:CN|EN)\]:?', '', prompt_en, flags=re.IGNORECASE)  # 清理遗留的标签头
                            prompt_en = re.sub(r'\(\s*:?\s*\d*\.?\d*\s*\)', '', prompt_en)  # 清理空权重如 (:1.2)
                            prompt_en = re.sub(r'\(\s*,+\s*', '(', prompt_en)  # 修复括号开头的逗号如 (, 变成 (
                            prompt_en = re.sub(r'\s*,+\s*\)', ')', prompt_en)  # 修复括号结尾的逗号如 ,) 变成 )
                            prompt_en = re.sub(r',\s*,+', ',', prompt_en)  # 清理连续逗号
                            prompt_en = prompt_en.strip(' ,.')  # 清理首尾多余标点

                            prompt_map[idx] = prompt_en

                    # 成功获取本批次后跳出重试循环，处理下一批
                    break

                except Exception as e:
                    retry_count += 1
                    logging.error(
                        f"Gemini推理批次 {i + 1}-{min(i + batch_size, total)} 出错 (第{retry_count}次尝试): {e}")
                    if retry_count >= 3:
                        logging.error(f"批次 {i + 1}-{min(i + batch_size, total)} 彻底失败，将跳过该批次。")
                    time.sleep(2)  # 失败后休眠缓冲

        # 将全部分批提取并清洗完成的AI结果，回填到最初的 subtitle_data 中
        for item in subtitle_data:
            idx = item['index']
            if idx in prompt_map:
                item['prompt'] = prompt_map[idx]
                item['status'] = "提示词已生成"

        return subtitle_data


# 测试代码
if __name__ == "__main__":
    pass