import pysrt
import json
import time
import configparser
import os
import requests
import logging  # 🌟 完美修复：引入 logging 替代 print，彻底免疫无控制台环境崩溃
import re  # 🌟 新增：引入正则表达式模块用于清洗幽灵提示词
import threading
import random
from requests.exceptions import ProxyError, InvalidProxyURL
from urllib.parse import urlparse

from 配置.app_config import CONFIG_FILE

# 🌟 终极架构第一阶段：全局防封锁与令牌桶（跨越所有类和实例共享）
_GLOBAL_API_LOCK = threading.Lock()
_LAST_API_REQUEST_TIME = 0.0
_API_MIN_INTERVAL = 0.35  # 限制全局发包间隔至少 0.35 秒 (即控制在最高约 2.8 QPS以内，极度安全)


def _wait_for_global_token():
    """全局令牌桶限流器：确保网络发包平滑过渡，绝对防踩踏和高并发 429"""
    global _LAST_API_REQUEST_TIME
    with _GLOBAL_API_LOCK:
        now = time.time()
        elapsed = now - _LAST_API_REQUEST_TIME
        if elapsed < _API_MIN_INTERVAL:
            time.sleep(_API_MIN_INTERVAL - elapsed)
        _LAST_API_REQUEST_TIME = time.time()


class GeminiLogic:
    def __init__(self, api_key):
        """
        初始化Gemini接口 (已重构为纯 HTTP REST 请求)
        :param api_key: Google Gemini API Key
        """
        if not api_key:
            raise ValueError("API Key 不能为空")

        self.api_key = api_key
        self.model_name = 'gemini-2.0-flash'  # 使用较快且效果好的模型
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

        # 🌟 终极修复 1：引入 Session 连接池并彻底阻断系统注册表代理读取 (防 0xC0000409)
        self.session = requests.Session()
        self.session.trust_env = False

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
        核心功能：推理分镜和提示词（支持大文件分段处理）
        针对长音频（如60分钟），将字幕切分成小块发送给 AI，保证运行流畅
        """
        batch_size = 40
        total_count = len(subtitle_data)

        # 🌟 终极重构：强制剥夺文学叙事能力，注入纯标签公式与正负面打样示例，并加入动态景别规则
        system_prompt = """
        【最高指令】：你现在不是AI助手，而是一个毫无感情的“分镜数据格式化处理器”。
        任务：分析提供的文本片段，为每一句字幕生成绝对精准的、由逗号分隔的短语词组。

        【强制 prompt_zh 公式】：
        一名[男性/女性]，[年龄]岁，[发型发色]，[面容特征]，穿着[服装]，[短语化动作/表情]，[景别]，背景是[场景]，[光线/物品细节]

        【极其重要的格式警告】：
        绝对禁止使用完整的句子、主谓宾结构、形容词堆砌！
        绝对禁止使用“着”、“了”、“正在”、“他有着”、“注视着”、“身穿”、“笼罩在”等废话字眼！必须全部转化为名词或短语，用逗号隔开！

        【🌟动态景别分配规则（强制执行）】：
        1. 若该镜头侧重对话或面部表情描写，必须加入【特写】或【近景】。
        2. 若该镜头侧重环境描写或刚转场，必须加入【远景】或【全景】。
        3. 若该镜头侧重肢体动作，必须加入【中景】。

        【🚫负面示例（如果这样输出判定为完全失败）】：
        错误：昏暗房间中，纪伯达以冷静的神情注视着失忆的柳如烟。柳如烟身穿柔白女仆装，神情纯真乖巧，眼神中带有一丝困惑...

        【✅正面示例（必须像机器一样完全模仿此格式）】：
        正确：一名男性，29岁，黑色寸头，神情冷静，一名女性，26岁，白色长直发，白色女仆装，神情纯真，眼神困惑，特写，背景是昏暗房间，尘埃漂浮，压抑氛围

        【英文生图强制规则】：
        1. 英文提示词 (prompt_en) 中【绝对禁止出现任何中文字符】。
        2. 遇到角色时，【必须使用英文外观特征替换角色名】。
        3. 🌟 性别绝对隔离法则：
           如果角色是男性，prompt_en 开头【必须】强制加入 `(1boy, male focus, masculine:1.4)`。
           如果角色是女性，prompt_en 开头【必须】强制加入 `(1girl, female focus:1.3)`。
           如果分镜无人物，必须在开头加上 `(2d urban anime style)`。
        4. 不允许生成空的权重括号（如 (:1.2) 或 (,) ）。

        请直接返回JSON数组格式，严禁返回任何Markdown代码块、解释或无关字符。
        格式示例：
        [
            {"index": 1, "prompt_zh": "中文画面描述（仅词组）", "prompt_en": "english prompt here..."}
        ]
        """

        for i in range(0, total_count, batch_size):
            batch = subtitle_data[i: i + batch_size]
            batch_text = "\n".join([f"{item['index']}. {item['text']}" for item in batch])

            try:
                url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
                headers = {"Content-Type": "application/json"}
                # 🌟 修复: 强制注入 safetySettings 以突破大模型对打斗、亲密接触等剧情的过滤拦截
                payload = {
                    "contents": [{
                        "parts": [{"text": f"{system_prompt}\n\n当前小说内容片段:\n{batch_text}"}]
                    }],
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                    ]
                }

                # 🌟 强制通过全局限流器发包
                _wait_for_global_token()
                # 使用线程安全的 session 发起请求
                response = self.session.post(url, headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                res_json = response.json()

                if "candidates" in res_json and res_json["candidates"]:
                    text_result = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    raise Exception("API 返回异常，未包含 candidates 数据")

                if text_result.startswith("```json"):
                    text_result = text_result.replace("```json", "", 1)
                if text_result.endswith("```"):
                    text_result = text_result.rsplit("```", 1)[0]
                text_result = text_result.strip()

                try:
                    json_result = json.loads(text_result)

                    # 🌟 优化：解析出双语字段，并使用正则强力清洗幽灵提示词
                    prompt_map = {}
                    for item in json_result:
                        idx = item.get('index')
                        if idx is not None:
                            prompt_zh = item.get('prompt_zh', '')
                            prompt_en = item.get('prompt_en', '')

                            # 🌟 新增：对中文 prompt 进行二次强制清洗，过滤掉容易残留的动作介词
                            if prompt_zh:
                                prompt_zh = re.sub(r'注视着|看着|身穿|穿着|笼罩在|充斥着', '', prompt_zh)
                                prompt_zh = re.sub(r'\s+', ',', prompt_zh)  # 把空格也替换成逗号
                                prompt_zh = re.sub(r',+', ',', prompt_zh).strip(',')  # 清理多余逗号

                            if prompt_en:
                                # 1. 强制剔除所有漏网的中文字符
                                prompt_en = re.sub(r'[\u4e00-\u9fa5]+', '', prompt_en)
                                # 2. 强制剔除只包含标点和权重的空括号，例如 (, . :1.2)
                                prompt_en = re.sub(r'\([^\w]*:?\d*\.?\d*\)', '', prompt_en)
                                # 3. 清理残留的连续逗号，并去除首尾多余空格和逗号
                                prompt_en = re.sub(r',\s*,+', ',', prompt_en).strip(' ,.')

                            combined_prompt = f"[CN]: {prompt_zh}\n[EN]: {prompt_en}" if prompt_zh or prompt_en else ""
                            prompt_map[idx] = {
                                'prompt_zh': prompt_zh,
                                'prompt_en_raw': prompt_en,
                                'prompt': combined_prompt
                            }

                    for item in batch:
                        idx = item['index']
                        if idx in prompt_map:
                            item['prompt_zh'] = prompt_map[idx]['prompt_zh']
                            item['prompt_en_raw'] = prompt_map[idx]['prompt_en_raw']
                            item['prompt'] = prompt_map[idx]['prompt']
                            item['status'] = "提示词已生成"
                        else:
                            item['status'] = "AI返回格式有误"
                except json.JSONDecodeError:
                    # 🌟 完美修复：安全记录日志替代 print
                    logging.warning(f"Batch {i // batch_size + 1} JSON 解析失败，跳过。")
                    for item in batch:
                        item['status'] = "解析失败"

                if i + batch_size < total_count:
                    time.sleep(1)

            except Exception as e:
                # 🌟 完美修复：安全记录日志替代 print
                logging.error(f"Gemini推理段落 {i // batch_size + 1} 出错: {e}")
                for item in batch:
                    item['status'] = f"请求错误: {str(e)}"

        return subtitle_data


class AIManager:
    """
    统一AI接口管理器，兼容现有代码中的 AIManager 调用
    从配置文件读取API密钥等信息，提供 generate_content 方法
    """

    def __init__(self):
        self.cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            for encoding in ['utf-8', 'utf-8-sig', 'gbk']:
                try:
                    self.cfg.read(CONFIG_FILE, encoding=encoding)
                    break
                except Exception:
                    continue

        if 'DEFAULT' not in self.cfg:
            self.cfg['DEFAULT'] = {}

        keys_raw = self.cfg['DEFAULT'].get('gemini_key', '').strip()
        # 🌟 终极架构第一阶段：支持多 Key 轮询池 (兼容逗号、分号或换行分隔)
        self.api_keys = [k.strip() for k in re.split(r'[,;|\n]+', keys_raw) if k.strip()]
        if not self.api_keys:
            self.api_keys = ['']  # 默认占位防崩

        self.current_key_index = 0

        self.base_url = self.cfg['DEFAULT'].get('base_url', '').strip()
        self.model_name = self.cfg['DEFAULT'].get('model_name', 'gpt-3.5-turbo').strip()
        self.api_type = self.cfg['DEFAULT'].get('api_type', 'openai').strip().lower()
        self.proxy_url = self.cfg['DEFAULT'].get('proxy_url', '').strip()

        if not self.base_url:
            if self.api_type == 'google':
                self.base_url = "https://generativelanguage.googleapis.com/v1beta"
            else:
                self.base_url = "https://api.openai.com/v1"

        if self.base_url.endswith('/'):
            self.base_url = self.base_url[:-1]

        # 🌟 终极修复 1：为管理器绑定线程安全且禁用系统环境的 HTTP Session
        self.session = requests.Session()
        self.session.trust_env = False

        self._init_client()

    def _init_client(self):
        self.client = None

    def _build_proxies(self):
        if not self.proxy_url:
            return None

        proxy = self.proxy_url.strip()
        parsed = urlparse(proxy)
        if not parsed.scheme:
            proxy = 'http://' + proxy
            parsed = urlparse(proxy)

        if not parsed.hostname:
            logging.warning("警告: 代理 URL 格式无效，缺少主机名，将不使用代理。")
            return None

        proxies = {
            'http': proxy,
            'https': proxy
        }
        return proxies

    def _get_current_key(self):
        return self.api_keys[self.current_key_index]

    def _rotate_key(self):
        """当遇到 429 报错或限额时，自动无缝切换到下一个 API Key"""
        if len(self.api_keys) > 1:
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            logging.warning(f"🔄 API 触发风控或限额，已自动轮询切换至第 {self.current_key_index + 1} 个 Key。")
            return True
        return False

    def generate_content(self, prompt, stream=False, **kwargs):
        """
        统一生成内容接口 (含智能重试与多 Key 轮询防封盾)
        :param prompt: 提示词
        :param stream: 是否流式输出
        :return: 生成的文本内容（字符串）
        """
        # 至少保障能把所有的 Key 都试一遍以上，单 Key 默认给 3 次重试容错
        max_retries = max(3, len(self.api_keys) * 2)
        last_error = None

        for attempt in range(max_retries):
            # 🌟 绝对屏障：发包前必须排队通过全局限流器
            _wait_for_global_token()
            current_key = self._get_current_key()

            if self.api_type == 'google':
                if stream:
                    url = f"{self.base_url}/models/{self.model_name}:streamGenerateContent?key={current_key}"
                else:
                    url = f"{self.base_url}/models/{self.model_name}:generateContent?key={current_key}"

                headers = {"Content-Type": "application/json"}
                # 🌟 修复: 强制注入 safetySettings 以突破大模型对各类小说剧情的审查拦截
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                    ]
                }
                proxies = self._build_proxies()

                try:
                    if stream:
                        response = self.session.post(url, headers=headers, json=payload, proxies=proxies, stream=True, timeout=60)
                        response.raise_for_status()
                        collected = []
                        for line in response.iter_lines():
                            if line:
                                line = line.decode('utf-8')
                                if line.startswith('data: '):
                                    line = line[6:]
                                try:
                                    chunk = json.loads(line)
                                    if "candidates" in chunk and chunk["candidates"]:
                                        content = chunk["candidates"][0]["content"]["parts"][0].get("text", "")
                                        if content:
                                            collected.append(content)
                                except json.JSONDecodeError:
                                    continue
                        return ''.join(collected)
                    else:
                        response = self.session.post(url, headers=headers, json=payload, proxies=proxies, timeout=60)
                        response.raise_for_status()
                        result = response.json()
                        if "candidates" in result and result["candidates"]:
                            return result["candidates"][0]["content"]["parts"][0]["text"]
                        else:
                            raise Exception("API 返回格式错误: " + json.dumps(result))

                except requests.exceptions.ProxyError as e:
                    raise Exception(f"代理错误: {str(e)}。请检查代理设置。")
                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response is not None else 0
                    # 429 频率限制, 403 额度不足/禁言, 5xx 服务器崩溃
                    if status_code in (429, 403, 500, 502, 503, 504):
                        if status_code in (429, 403):
                            self._rotate_key()
                        # 加入防踩踏带抖动的指数退避
                        jitter = random.uniform(0.5, 1.5)
                        time.sleep((2 ** attempt) * jitter)
                        last_error = e
                        continue
                    else:
                        raise Exception(f"Gemini 请求失败 (HTTP {status_code}): {e.response.text if e.response else str(e)}")
                except requests.exceptions.Timeout as e:
                    jitter = random.uniform(0.5, 1.5)
                    time.sleep((2 ** attempt) * jitter)
                    last_error = e
                    continue
                except requests.exceptions.RequestException as e:
                    raise Exception(f"Gemini 请求彻底失败: {str(e)}")

            else:
                # OPENAI COMPATIBLE API
                url = f"{self.base_url}/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {current_key}"
                }
                data = {
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": stream
                }
                data.update(kwargs)
                proxies = self._build_proxies()

                try:
                    if stream:
                        response = self.session.post(url, headers=headers, json=data, proxies=proxies, stream=True, timeout=60)
                        response.raise_for_status()
                        collected = []
                        for line in response.iter_lines():
                            if line:
                                line = line.decode('utf-8')
                                if line.startswith('data: '):
                                    line = line[6:]
                                if line == '[DONE]':
                                    break
                                try:
                                    chunk = json.loads(line)
                                    if 'choices' in chunk and chunk['choices']:
                                        delta = chunk['choices'][0].get('delta', {})
                                        content = delta.get('content', '')
                                        if content:
                                            collected.append(content)
                                except json.JSONDecodeError:
                                    continue
                        return ''.join(collected)
                    else:
                        response = self.session.post(url, headers=headers, json=data, proxies=proxies, timeout=60)
                        response.raise_for_status()
                        result = response.json()
                        if 'choices' in result and result['choices']:
                            return result['choices'][0]['message']['content']
                        else:
                            raise Exception("API 返回格式错误: " + json.dumps(result))

                except requests.exceptions.ProxyError as e:
                    raise Exception(f"代理错误: {str(e)}。请检查代理设置。")
                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response is not None else 0
                    if status_code in (429, 403, 500, 502, 503, 504):
                        if status_code in (429, 403):
                            self._rotate_key()
                        jitter = random.uniform(0.5, 1.5)
                        time.sleep((2 ** attempt) * jitter)
                        last_error = e
                        continue
                    else:
                        raise Exception(f"OpenAI 请求失败 (HTTP {status_code}): {e.response.text if e.response else str(e)}")
                except requests.exceptions.Timeout as e:
                    jitter = random.uniform(0.5, 1.5)
                    time.sleep((2 ** attempt) * jitter)
                    last_error = e
                    continue
                except requests.exceptions.RequestException as e:
                    raise Exception(f"OpenAI 兼容 API 请求彻底失败: {str(e)}")

        # 如果穷举了所有的重试次数依旧失败，则抛出最终异常
        raise Exception(f"API 请求被服务器拒绝，已耗尽所有重试与轮询防线。最后错误: {str(last_error)}")