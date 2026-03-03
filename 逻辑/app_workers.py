import json
import time
import requests
import threading
import uuid
import urllib.request
import urllib.parse
import websocket
import random
import re
import os
import hashlib
import hmac
import datetime
import shutil
import configparser
import queue
import concurrent.futures
from PyQt6.QtCore import QThread, pyqtSignal

from 逻辑.ai_manager import AIManager
from 逻辑.srt_util import LocalSRTParser
from 配置.app_config import CONFIG_FILE

_global_running_threads = []

# 🌟 Bug 2 Fix: 全局项目文件读写锁，绝对防止多线程高并发时把 .ntp 项目文件写成 0KB
_ntp_file_lock = threading.Lock()


# ==========================================
# 翻译引擎基类与具体实现 (支持多平台无缝切换)
# ==========================================
class BaseTranslator:
    def translate(self, query, from_lang='zh', to_lang='en'):
        raise NotImplementedError


class BaiduTranslator(BaseTranslator):
    def __init__(self, app_id, secret_key):
        self.app_id = app_id.strip()
        self.secret_key = secret_key.strip()
        self.api_url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
        self.session = requests.Session()
        self.session.trust_env = False

    def translate(self, query, from_lang='zh', to_lang='en'):
        if not self.app_id or not self.secret_key:
            return None, "未配置 API Key"

        salt = random.randint(32768, 65536)
        sign_str = f"{self.app_id}{query}{salt}{self.secret_key}"
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        payload = {'appid': self.app_id, 'q': query, 'from': from_lang, 'to': to_lang, 'salt': salt, 'sign': sign}

        try:
            r = self.session.post(self.api_url, params=payload, headers=headers, timeout=5)
            res = r.json()
            if "trans_result" in res:
                return res["trans_result"][0]["dst"], None
            else:
                return None, res.get("error_msg", "未知错误")
        except Exception as e:
            return None, str(e)


class TencentTranslator(BaseTranslator):
    def __init__(self, secret_id, secret_key, region="ap-guangzhou"):
        self.secret_id = secret_id.strip()
        self.secret_key = secret_key.strip()
        self.region = region
        self.endpoint = "tmt.tencentcloudapi.com"

    def translate(self, query, from_lang='zh', to_lang='en'):
        try:
            action = "TextTranslate"
            version = "2018-03-21"
            algorithm = "TC3-HMAC-SHA256"
            timestamp = int(time.time())
            date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

            payload = {
                "SourceText": query,
                "Source": from_lang,
                "Target": to_lang,
                "ProjectId": 0
            }
            payload_str = json.dumps(payload)

            ct = "application/json; charset=utf-8"
            canonical_headers = f"content-type:{ct}\nhost:{self.endpoint}\n"
            signed_headers = "content-type;host"
            hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"

            credential_scope = f"{date}/tmt/tc3_request"
            hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
            string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

            def sign(key, msg):
                return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

            secret_date = sign(("TC3" + self.secret_key).encode("utf-8"), date)
            secret_service = sign(secret_date, "tmt")
            secret_signing = sign(secret_service, "tc3_request")
            signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

            authorization = f"{algorithm} Credential={self.secret_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

            headers = {
                "Authorization": authorization,
                "Content-Type": ct,
                "Host": self.endpoint,
                "X-TC-Action": action,
                "X-TC-Timestamp": str(timestamp),
                "X-TC-Version": version,
                "X-TC-Region": self.region
            }
            resp = requests.post(f"https://{self.endpoint}", headers=headers, data=payload_str, timeout=5)
            res_data = resp.json()
            if "Response" in res_data and "TargetText" in res_data["Response"]:
                return res_data["Response"]["TargetText"], None
            else:
                return None, str(res_data.get("Response", {}).get("Error", res_data))
        except Exception as e:
            return None, f"腾讯翻译异常: {str(e)}"


class VolcengineTranslator(BaseTranslator):
    def __init__(self, access_key, secret_key):
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.endpoint = "open.volcengineapi.com"
        self.region = "cn-north-1"
        self.service = "translate"

    def translate(self, query, from_lang='zh', to_lang='en'):
        try:
            action = "TranslateText"
            version = "2020-06-01"

            payload = {
                "SourceLanguage": from_lang,
                "TargetLanguage": to_lang,
                "TextList": [query]
            }
            payload_str = json.dumps(payload)
            t = datetime.datetime.utcnow()
            amz_date = t.strftime("%Y%m%dT%H%M%SZ")
            datestamp = t.strftime("%Y%m%d")

            payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            canonical_querystring = f"Action={action}&Version={version}"
            canonical_headers = f"content-type:application/json\nhost:{self.endpoint}\nx-content-sha256:{payload_hash}\nx-date:{amz_date}\n"
            signed_headers = "content-type;host;x-content-sha256;x-date"

            canonical_request = f"POST\n/\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

            algorithm = "HMAC-SHA256"
            credential_scope = f"{datestamp}/{self.region}/{self.service}/request"
            string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

            def sign(key, msg):
                return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

            k_date = sign(self.secret_key.encode('utf-8'), datestamp)
            k_region = sign(k_date, self.region)
            k_service = sign(k_region, self.service)
            k_signing = sign(k_service, "request")
            signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

            authorization_header = f"{algorithm} Credential={self.access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
            headers = {
                "Content-Type": "application/json",
                "X-Date": amz_date,
                "X-Content-Sha256": payload_hash,
                "Authorization": authorization_header
            }
            url = f"https://{self.endpoint}/?{canonical_querystring}"
            resp = requests.post(url, headers=headers, data=payload_str, timeout=5)
            res_data = resp.json()

            if "TranslationList" in res_data:
                return res_data["TranslationList"][0]["Translation"], None
            else:
                return None, str(res_data.get("ResponseMetadata", {}).get("Error", res_data))
        except Exception as e:
            return None, f"火山翻译异常: {str(e)}"


class TranslatorManager:
    def __init__(self):
        self.translators = []

    def add_translator(self, translator):
        self.translators.append(translator)

    def is_empty(self):
        return len(self.translators) == 0

    def translate(self, query, from_lang='zh', to_lang='en'):
        if self.is_empty():
            return None, "未配置任何外部翻译接口"

        errors = []
        for t in self.translators:
            # 🌟 优化：植入指数退避算法，应对百度/腾讯等大厂 API 的 QPS 限流报错
            for attempt in range(3):
                res, err = t.translate(query, from_lang, to_lang)
                if res:
                    return res, None
                if attempt < 2:
                    time.sleep(1.5 ** attempt)  # 限流避让 1s, 1.5s

            name = t.__class__.__name__.replace('Translator', '')
            errors.append(f"{name}失效({err})")

        return None, " | ".join(errors)


# ==========================================
# 原有线程定义
# ==========================================

class ConnectionTestThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, service_type, manual_url=None):
        super().__init__()
        self.service_type = service_type
        self.manual_url = manual_url

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def run(self):
        try:
            if self.service_type == "gemini":
                self.test_gemini()
            elif self.service_type == "comfy":
                self.test_comfy()
            elif self.service_type == "baidu":
                self.test_baidu()
            elif self.service_type == "tencent":
                self.test_tencent()
            elif self.service_type == "volcengine":
                self.test_volcengine()
        except Exception as e:
            self.log_signal.emit(f"❌ 测试线程发生意外异常: {str(e)}")
            self.finished_signal.emit(False)

    def test_baidu(self):
        self.log_signal.emit("正在测试百度翻译 API...")
        parts = self.manual_url.split('|')
        if len(parts) < 3:
            self.log_signal.emit("❌ 参数格式错误，请检查代码调用")
            self.finished_signal.emit(False)
            return
        appid, secret = parts[1].strip(), parts[2].strip()
        if not appid or not secret:
            self.log_signal.emit("❌ AppID 或 密钥为空")
            self.finished_signal.emit(False)
            return

        translator = BaiduTranslator(appid, secret)
        start_t = time.time()
        res, err = translator.translate("你好")
        cost = (time.time() - start_t) * 1000

        if res:
            self.log_signal.emit(f"✅ 翻译成功! 耗时: {cost:.0f}ms\n测试: '你好' -> '{res}'")
            self.finished_signal.emit(True)
        else:
            self.log_signal.emit(f"❌ 翻译失败: {err}")
            self.finished_signal.emit(False)

    def test_tencent(self):
        self.log_signal.emit("正在测试腾讯云翻译 API...")
        parts = self.manual_url.split('|')
        if len(parts) < 3:
            self.log_signal.emit("❌ 参数格式错误，请检查代码调用")
            self.finished_signal.emit(False)
            return
        secret_id, secret_key = parts[1].strip(), parts[2].strip()
        if not secret_id or not secret_key:
            self.log_signal.emit("❌ SecretId 或 SecretKey 为空")
            self.finished_signal.emit(False)
            return

        translator = TencentTranslator(secret_id, secret_key)
        start_t = time.time()
        res, err = translator.translate("你好")
        cost = (time.time() - start_t) * 1000

        if res:
            self.log_signal.emit(f"✅ 翻译成功! 耗时: {cost:.0f}ms\n测试: '你好' -> '{res}'")
            self.finished_signal.emit(True)
        else:
            self.log_signal.emit(f"❌ 翻译失败: {err}")
            self.finished_signal.emit(False)

    def test_volcengine(self):
        self.log_signal.emit("正在测试火山引擎翻译 API...")
        parts = self.manual_url.split('|')
        if len(parts) < 3:
            self.log_signal.emit("❌ 参数格式错误，请检查代码调用")
            self.finished_signal.emit(False)
            return
        access_key, secret_key = parts[1].strip(), parts[2].strip()
        if not access_key or not secret_key:
            self.log_signal.emit("❌ AccessKey 或 SecretKey 为空")
            self.finished_signal.emit(False)
            return

        translator = VolcengineTranslator(access_key, secret_key)
        start_t = time.time()
        res, err = translator.translate("你好")
        cost = (time.time() - start_t) * 1000

        if res:
            self.log_signal.emit(f"✅ 翻译成功! 耗时: {cost:.0f}ms\n测试: '你好' -> '{res}'")
            self.finished_signal.emit(True)
        else:
            if "InvalidAccessKey" in str(err):
                err += "\n💡 提示：服务器判定您的密钥无效！请千万不要用截图识别文字复制！务必去火山控制台用鼠标直接点击【复制】！"
            self.log_signal.emit(f"❌ 翻译失败: {err}")
            self.finished_signal.emit(False)

    def test_gemini(self):
        self.log_signal.emit("正在测试 LLM 连接...")
        try:
            ai = AIManager()
            start_t = time.time()
            reply = ai.generate_content("Hello, reply 'OK'.", stream=False)
            cost = (time.time() - start_t) * 1000

            if reply:
                clean_reply = reply.strip().strip('"').strip("'")
                self.log_signal.emit(f"✅ 连接成功! 耗时: {cost:.0f}ms\n回复: {clean_reply[:50]}...")
                self.finished_signal.emit(True)
            else:
                self.log_signal.emit("❌ 连接失败: 无响应内容")
                self.finished_signal.emit(False)
        except Exception as e:
            self.log_signal.emit(f"❌ 连接异常: {str(e)}")
            self.finished_signal.emit(False)

    def test_comfy(self):
        url = self.manual_url
        if not url:
            self.log_signal.emit("❌ URL 为空")
            self.finished_signal.emit(False)
            return

        url = url.strip().rstrip('/')
        if not url.startswith("http"): url = "http://" + url

        self.log_signal.emit(f"正在测试 ComfyUI: {url} ...")
        try:
            start_t = time.time()
            resp = requests.get(f"{url}/system_stats", timeout=5)
            cost = (time.time() - start_t) * 1000
            if resp.status_code == 200:
                self.log_signal.emit(f"✅ 连接成功! 耗时: {cost:.0f}ms")
                self.finished_signal.emit(True)
            else:
                self.log_signal.emit(f"❌ 连接失败: HTTP {resp.status_code}")
                self.finished_signal.emit(False)
        except Exception as e:
            self.log_signal.emit(f"❌ 连接异常: {str(e)}")
            self.finished_signal.emit(False)


class TranslationThread(QThread):
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, srt_path, target_lang="English"):
        super().__init__()
        self.srt_path = srt_path
        self.target_lang = target_lang
        self.is_cancelled = False

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def run(self):
        try:
            ai_manager = AIManager()
            subs = LocalSRTParser.parse(self.srt_path)
            total = len(subs)
            if total == 0: raise Exception("字幕文件为空或格式错误")

            self.log_signal.emit(f"开始翻译 {total} 条字幕...")
            translated_subs = []
            batch_size = 10

            for i in range(0, total, batch_size):
                if self.is_cancelled: return
                batch = subs[i:i + batch_size]
                batch_text = "\n".join([f"[{s['index']}] {s['text']}" for s in batch])
                prompt = f"You are a professional subtitle translator. Translate to {self.target_lang}. Keep format '[index] text'.\n\n{batch_text}"

                # 🌟 优化：加入大模型自动退避重试，防止偶发吞词和网络抖动
                retry_count = 0
                success_flag = False
                while retry_count < 3 and not self.is_cancelled:
                    try:
                        response = ai_manager.generate_content(prompt)
                        lines = response.strip().split('\n')
                        result_map = {}
                        for line in lines:
                            match = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
                            if match: result_map[int(match.group(1))] = match.group(2)

                        for s in batch:
                            trans = result_map.get(s['index'], s['text'])
                            translated_subs.append(
                                {"index": s['index'], "start": s['start'], "end": s['end'], "text": trans})
                        success_flag = True
                        break
                    except Exception as e:
                        retry_count += 1
                        if retry_count < 3:
                            time.sleep(2 ** retry_count)
                        else:
                            self.log_signal.emit(f"批次 {i // batch_size + 1} 失败已跳过: {e}")

                if not success_flag:
                    for s in batch: translated_subs.append(s)

                self.progress_signal.emit(min(i + batch_size, total), total)
                time.sleep(0.5)

            dir_name = os.path.dirname(self.srt_path)
            base_name = os.path.basename(self.srt_path)
            name, ext = os.path.splitext(base_name)
            new_path = os.path.join(dir_name, f"{name}_{self.target_lang}{ext}")

            LocalSRTParser.save(translated_subs, new_path)
            self.finished_signal.emit(new_path)
        except Exception as e:
            self.error_signal.emit(str(e))

    def cancel(self):
        self.is_cancelled = True


class SmartSplitThread(QThread):
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, raw_subs, threshold=30, early_min=2, early_max=3, late_min=5, late_max=8, mode='fixed'):
        super().__init__()
        self.raw_subs = raw_subs
        self.threshold = threshold
        self.early_min = early_min
        self.early_max = early_max
        self.late_min = late_min
        self.late_max = late_max
        self.mode = mode
        self.is_cancelled = False

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def run(self):
        try:
            if not self.raw_subs:
                self.error_signal.emit("字幕数据为空，请检查字幕文件是否正确加载。")
                return

            cleaned_subs = []
            for idx, sub in enumerate(self.raw_subs):
                cleaned_subs.append({
                    "index": idx + 1, "start": sub.get("start", 0), "end": sub.get("end", 0),
                    "duration": sub.get("duration", 0), "text": sub.get("text", "").strip()
                })
            self.raw_subs = cleaned_subs

            if self.mode == 'ai':
                self.run_ai_split()
            else:
                self.run_fixed_split()
        except Exception as e:
            self.error_signal.emit(f"分镜处理异常: {str(e)}")

    def _get_target_combine(self, current_scene_index):
        if current_scene_index <= self.threshold:
            return random.randint(self.early_min, self.early_max)
        else:
            return random.randint(self.late_min, self.late_max)

    def run_fixed_split(self):
        total = len(self.raw_subs)
        scenes, current_group = [], []
        current_duration, scene_index = 1, 1

        current_target_combine = self._get_target_combine(scene_index)

        for i, sub in enumerate(self.raw_subs):
            if self.is_cancelled: return
            current_group.append(sub)
            current_duration += sub['duration']
            text = sub['text']
            is_end_char = text and text[-1] in ['。', '！', '？', '.', '!', '?', '”', '"']

            current_min_break = 2 if current_target_combine <= 3 else current_target_combine // 2

            should_split = False
            if len(current_group) >= current_target_combine:
                should_split = True
            elif is_end_char and len(current_group) >= current_min_break:
                should_split = True
            elif i == total - 1:
                should_split = True

            if should_split:
                merged_text = "\n".join([s['text'] for s in current_group])
                scenes.append({
                    "index": scene_index, "text": merged_text, "duration": round(current_duration, 2),
                    "sub_ids": [s['index'] for s in current_group], "prompt": "", "status": "待处理", "images": [],
                    "roles": []
                })
                scene_index += 1
                current_group, current_duration = [], 0
                current_target_combine = self._get_target_combine(scene_index)

            self.progress_signal.emit(i + 1, total)

        if not self.is_cancelled:
            self.finished_signal.emit(scenes)

    def run_ai_split(self):
        self.log_signal.emit("🚀 正在启动 AI 语义分析引擎...")
        try:
            ai_manager = AIManager()
        except Exception as e:
            self.error_signal.emit(f"AI 初始化失败: {e}，请检查 API 设置。")
            return

        total = len(self.raw_subs)
        batch_size = 30
        scene_start_indices = {1}

        for i in range(0, total, batch_size):
            if self.is_cancelled: return
            batch = self.raw_subs[i:i + batch_size]
            batch_text = "\n".join([f"[{s['index']}] {s['text']}" for s in batch])
            prompt = (
                f"你是一位专业的电影分镜导演。请分析以下小说推文的字幕。\n"
                f"识别画面场景转换、时间跳跃、地点变更的时刻。\n"
                f"找出所有**开启新场景**的字幕行号（ID）。\n\n"
                f"【输入】：\n{batch_text}\n\n"
                f"【输出】：仅返回 JSON 格式的整数列表，如 [{batch[0]['index']}]"
            )
            self.log_signal.emit(f"🧠 AI 正在分析第 {i + 1}-{min(i + batch_size, total)} 行语义...")
            try:
                response = ai_manager.generate_content(prompt, stream=False)
                clean_json = response.replace("```json", "").replace("```", "").strip()
                match = re.search(r'\[.*\]', clean_json, re.DOTALL)
                if match:
                    for sid in json.loads(match.group()):
                        if isinstance(sid, int): scene_start_indices.add(sid)
            except Exception as e:
                self.log_signal.emit(f"⚠️ 第 {i // batch_size + 1} 批分析失败: {e}")
            self.progress_signal.emit(min(i + batch_size, total), total)
            time.sleep(0.5)

        self.log_signal.emit("✅ AI 分析完成，正在生成分镜...")
        scenes, current_group = [], []
        current_duration, scene_index = 1, 1

        current_target_combine = self._get_target_combine(scene_index)

        for i, sub in enumerate(self.raw_subs):
            sid = sub['index']

            should_split = (sid in scene_start_indices or len(current_group) >= current_target_combine) and (
                    i > 0 and len(current_group) > 0)
            if should_split:
                scenes.append({
                    "index": scene_index, "text": "\n".join([s['text'] for s in current_group]),
                    "duration": round(current_duration, 2), "sub_ids": [s['index'] for s in current_group],
                    "prompt": "", "status": "待处理", "images": [], "roles": []
                })
                scene_index += 1
                current_group, current_duration = [], 0
                current_target_combine = self._get_target_combine(scene_index)

            current_group.append(sub)
            current_duration += sub['duration']

        if current_group:
            scenes.append({
                "index": scene_index, "text": "\n".join([s['text'] for s in current_group]),
                "duration": round(current_duration, 2), "sub_ids": [s['index'] for s in current_group],
                "prompt": "", "status": "待处理", "images": [], "roles": []
            })

        if not self.is_cancelled:
            self.finished_signal.emit(scenes)

    def cancel(self):
        self.is_cancelled = True


class RoleExtractThread(QThread):
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, text, custom_template=""):
        super().__init__()
        self.text = text
        self.custom_template = custom_template
        self.is_cancelled = False

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def run(self):
        try:
            ai_manager = AIManager()
            CHUNK_SIZE = 3000
            chunks = [self.text[i: i + CHUNK_SIZE] for i in range(0, len(self.text), CHUNK_SIZE)] if len(
                self.text) > CHUNK_SIZE else [self.text]
            all_roles_raw = []

            # 🌟 优化：强化识别别名、尊称的系统指令
            system_guardrail = (
                "\n\n【系统级护栏指令 - 极度严格】：无论上文要求是什么，你必须且只能返回纯 JSON 列表格式！\n"
                "禁止包含任何 markdown 标签或多余的解释文字。\n"
                "【致命格式警告】：`desc` 字段【绝对禁止】写完整的句子！必须全部转化为名词短语，用逗号隔开！\n"
                "【强制脑补补充指令】：即使文中没有描写角色的外貌，你也必须强制为其补充：年龄、性别、发型、发色、具体服装款式及颜色！\n"
                "字段必须严格包含：`name` (主要称呼), `aliases` (别名数组，必须包含文中对他的所有尊称、外号、别称等), `desc` (严格逗号分隔的外貌短语)。"
            )

            for i, chunk in enumerate(chunks):
                if self.is_cancelled: return
                self.log_signal.emit(f"🧠 正在分析第 {i + 1}/{len(chunks)} 部分文本...")

                if self.custom_template and "{TEXT}" in self.custom_template:
                    prompt = self.custom_template.replace("{TEXT}", chunk) + system_guardrail
                else:
                    prompt = (
                            f"你是一位电影美术指导。\n请提取主要角色，并智能识别同一个人在不同场景下的不同称呼（如别名、尊称、外号，放入 aliases 数组中）。\n\n"
                            f"【内容】：\n{chunk}"
                            + system_guardrail
                    )

                try:
                    response = ai_manager.generate_content(prompt, stream=False)
                    cleaned_resp = response.replace("```json", "").replace("```", "").strip()
                    roles_list = []

                    try:
                        roles_list = json.loads(cleaned_resp)
                    except json.JSONDecodeError:
                        match = re.search(r'\[.*\]', cleaned_resp, re.DOTALL)
                        if match:
                            try:
                                roles_list = json.loads(match.group())
                            except:
                                pass

                    if isinstance(roles_list, list):
                        all_roles_raw.extend([r for r in roles_list if isinstance(r, dict) and 'name' in r])
                except Exception as e:
                    pass
                time.sleep(0.5)

            merged_roles = []
            for r in all_roles_raw:
                name = r['name'].strip()
                if not name: continue

                aliases = r.get('aliases')
                if not aliases:
                    aliases = []
                elif isinstance(aliases, str):
                    aliases = [aliases]
                elif not isinstance(aliases, list):
                    aliases = []
                aliases = [str(a).strip() for a in aliases if str(a).strip()]

                found_match = False
                for existing in merged_roles:
                    existing_name = existing['name']
                    existing_aliases = existing.get('aliases', [])

                    is_same_person = False
                    if name == existing_name or name in existing_aliases or existing_name in aliases:
                        is_same_person = True
                    elif set(aliases).intersection(set(existing_aliases)):
                        is_same_person = True

                    if is_same_person:
                        found_match = True
                        combined_aliases = list(set(existing_aliases + aliases + [name]) - {existing_name})
                        existing['aliases'] = combined_aliases
                        if len(r.get('desc', '')) > len(existing.get('desc', '')):
                            existing['desc'] = r.get('desc', '')
                        break

                if not found_match:
                    r['aliases'] = aliases
                    merged_roles.append(r)

            if not self.is_cancelled:
                self.finished_signal.emit(merged_roles)
        except Exception as e:
            if not self.is_cancelled:
                self.error_signal.emit(f"角色提取失败: {str(e)}")

    def cancel(self):
        self.is_cancelled = True


class PromptWorker(QThread):
    log_signal = pyqtSignal(str, str, str)
    sys_log_signal = pyqtSignal(str, str, str)
    data_signal = pyqtSignal(str, str, list)
    finished_signal = pyqtSignal(str, str)

    def __init__(self, session_id, project_path, scenes_list, role_cards, custom_template, baidu_appid="",
                 baidu_secret=""):
        super().__init__()
        self.session_id = session_id
        self.project_path = project_path
        self.scenes_list = scenes_list
        self.role_cards = role_cards
        self.custom_template = custom_template
        self.is_running = True

        self.infer_thread_count = 5
        self.infer_batch_size = 5

        self.translator_manager = TranslatorManager()
        if baidu_appid and baidu_secret:
            self.translator_manager.add_translator(BaiduTranslator(baidu_appid, baidu_secret))

        try:
            cfg = configparser.ConfigParser()
            for encoding in ['utf-8', 'utf-8-sig', 'gbk']:
                try:
                    cfg.read(CONFIG_FILE, encoding=encoding)
                    break
                except Exception:
                    continue
            if 'DEFAULT' in cfg:
                if 'infer_thread_count' in cfg['DEFAULT']:
                    self.infer_thread_count = int(cfg['DEFAULT']['infer_thread_count'])
                if 'infer_batch_size' in cfg['DEFAULT']:
                    self.infer_batch_size = int(cfg['DEFAULT']['infer_batch_size'])

                t_id = cfg['DEFAULT'].get('tencent_secret_id', '').strip()
                t_key = cfg['DEFAULT'].get('tencent_secret_key', '').strip()
                if t_id and t_key:
                    self.translator_manager.add_translator(TencentTranslator(t_id, t_key))

                v_ak = cfg['DEFAULT'].get('volc_access_key', '').strip()
                v_sk = cfg['DEFAULT'].get('volc_secret_key', '').strip()
                if v_ak and v_sk:
                    self.translator_manager.add_translator(VolcengineTranslator(v_ak, v_sk))
        except Exception:
            pass

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def _has_chinese(self, text):
        return any('\u4e00' <= char <= '\u9fff' for char in text)

    def run(self):
        try:
            ai_manager = AIManager()
        except Exception as e:
            self.sys_log_signal.emit(self.session_id, self.project_path, f"❌ 工作线程初始化 AI 失败: {e}")
            return

        self.translated_roles_map = {}
        for rc in self.role_cards:
            r_name = rc.get('name', '').strip()
            r_desc = rc.get('desc', '').strip()
            if not r_name or not r_desc:
                continue

            trans_desc = None

            if not self.translator_manager.is_empty() and self._has_chinese(r_desc):
                trans_desc, trans_err = self.translator_manager.translate(r_desc, from_lang='zh', to_lang='en')
                if trans_err:
                    self.sys_log_signal.emit(self.session_id, self.project_path,
                                             f"⚠️ 所有外部翻译API已失效，正切换大模型兜底: {trans_err}")

            if not trans_desc and self._has_chinese(r_desc):
                self.sys_log_signal.emit(self.session_id, self.project_path,
                                         f"🧠 启动大模型智能翻译角色设定: [{r_name}]...")
                try:
                    ai_prompt = f"请将以下角色外貌描述翻译为适合 Stable Diffusion 生图的纯英文提示词（只需返回纯英文逗号分隔的短语，严禁包含任何多余解释、完整句子或 Markdown 格式）：\n{r_desc}"
                    resp = ai_manager.generate_content(ai_prompt, stream=False)
                    if resp:
                        trans_desc = resp.replace('```', '').replace('\n', ', ').strip(' .')
                except Exception as e:
                    self.sys_log_signal.emit(self.session_id, self.project_path, f"❌ 大模型翻译角色[{r_name}]失败: {e}")

            if trans_desc:
                trans_desc = re.sub(r'[\u4e00-\u9fa5]+', '', trans_desc).strip(' ,')
                self.translated_roles_map[r_name] = trans_desc
            else:
                self.translated_roles_map[r_name] = r_desc

        batch_size = self.infer_batch_size

        pending_scenes = []
        for scene in self.scenes_list:
            en_raw = scene.get('prompt_en_raw', '').strip()
            text_raw = scene.get('text', '').strip()
            if en_raw and en_raw != text_raw and len(en_raw) > 5:
                pass
            else:
                pending_scenes.append(scene)

        skipped_count = len(self.scenes_list) - len(pending_scenes)
        if skipped_count > 0:
            self.sys_log_signal.emit(self.session_id, self.project_path,
                                     f"⚡ 断点续传激活：自动跳过 {skipped_count} 个已生成镜头。")

        if not pending_scenes:
            if self.is_running:
                self.finished_signal.emit(self.session_id, self.project_path)
            return

        batches = [pending_scenes[i:i + batch_size] for i in range(0, len(pending_scenes), batch_size)]

        self.sys_log_signal.emit(self.session_id, self.project_path,
                                 f"🚀 启动滑动窗口并发池，并发线程式: {self.infer_thread_count}，剩余批次: {len(batches)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.infer_thread_count) as executor:
            future_to_batch = {}
            for batch in batches:
                if not self.is_running:
                    break
                future = executor.submit(self._process_batch, batch, ai_manager, self.translator_manager)
                future_to_batch[future] = batch

            for future in concurrent.futures.as_completed(future_to_batch):
                if not self.is_running:
                    break
                batch_info = future_to_batch[future]
                try:
                    batch_updates = future.result()
                    if batch_updates and self.is_running:
                        self.data_signal.emit(self.session_id, self.project_path, batch_updates)
                        self._save_updates_to_ntp(batch_updates)
                except Exception as e:
                    self.sys_log_signal.emit(self.session_id, self.project_path,
                                             f"❌ 批次 {batch_info[0]['index']} 发生异常: {e}")

        if self.is_running:
            self.finished_signal.emit(self.session_id, self.project_path)

    def _save_updates_to_ntp(self, batch_updates):
        if not self.project_path or not os.path.exists(self.project_path):
            return

        with _ntp_file_lock:
            try:
                with open(self.project_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)

                scenes_data = project_data.get('scenes', [])
                if not scenes_data:
                    return

                update_map = {u['scene_index']: u['data'] for u in batch_updates}
                modified = False

                for s in scenes_data:
                    idx = s.get('index')
                    if idx in update_map:
                        new_data = update_map[idx]
                        s['prompt'] = new_data.get('prompt', '')
                        s['prompt_en_raw'] = new_data.get('prompt_en_raw', '')
                        s['prompt_zh_raw'] = new_data.get('prompt_zh_raw', '')
                        s['prompt_zh_display'] = new_data.get('prompt_zh_display', '')
                        s['roles'] = new_data.get('roles', [])
                        s['status'] = "提示词已生成"
                        modified = True

                if modified:
                    with open(self.project_path, 'w', encoding='utf-8') as f:
                        json.dump(project_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                pass

    def _process_batch(self, batch_scenes, ai_manager, translator_manager):
        if not self.is_running:
            return []

        # 🌟 优化：在发送给 AI 进行生图推理时，一并把别名/尊称带上
        roles_desc_list = []
        for r in self.role_cards:
            n = r.get('name', '')
            aliases = r.get('aliases', [])
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(',') if a.strip()]
            elif not isinstance(aliases, list):
                aliases = []
            alias_str = f" (别称/尊称: {', '.join(aliases)})" if aliases else ""
            roles_desc_list.append(f"- {n}{alias_str}: {r.get('desc', '')}")

        roles_desc = "\n".join(roles_desc_list) or "无特定角色。"
        scene_texts = "\n".join([f"镜头ID {s['index']}: {s['text']}" for s in batch_scenes])

        system_guardrail = (
            "\n\n【系统级护栏指令 - 极度严格】：无论上方提示词要求如何，你最终返回的必须是**纯 JSON 数组格式**，"
            "禁止包含任何 markdown 标签（如 ```json）或解释文字！\n"
            "【致命格式警告】：`prompt_zh` 字段【绝对禁止】写完整的句子、主谓宾结构、形容词堆砌！必须转化为名词或短语，用逗号隔开！\n"
            "【🎬电影级镜头与主体原则】：\n"
            "  1. 🎯【确立C位与动作】：仔细分析文案，找出该镜头的【唯一核心主角】及其【核心动作/表情】。绝不能生成所有人呆立排排站的群像大合照！\n"
            "  2. 👥【主次分明】：将出现的核心角色全部放入 roles 数组中，且【务必把最核心的主角放在 roles 数组的第 1 位】！\n"
            "  3. 🧠【深度上下文推断性别】：填入 'm'(男) 或 'f'(女) 或 'u'(未知) 的字符串数组。\n"
            "  4. ⚠️【防缝合与一致性】：【绝对禁止】自己发明衣服！严格遵守已知角色设定！多角色同框时必须用明确的量词和特征隔开。\n"
            "  5. 【姓名抹除法则】：`prompt_zh` 和 `prompt_en` 中【绝对禁止】出现角色的中英文原始姓名！必须替换为该角色的纯外貌描写！\n"
            "  6. 🌟【AI直出英文外貌与动作强制令】：你**必须亲自**将【角色设定】中对应角色的所有外貌细节，连同他/她正在做的【动作、表情】准确翻译为英文，写在 `prompt_en` 中！(如: 1boy, 24 years old, short orange hair, stunned expression, holding ribs)。\n"
            "  7. 🛑【防污染绝杀令】：JSON结构中的 `roles` 数组【绝对禁止】填入外貌描述！必须且只能填入角色的原始纯姓名（例如 [\"许清远\"]，绝不能是 [\"一名24岁男性...\"]），这是系统底层的识别锚点！\n"
            "【🌟动态景别分配规则】：\n"
            "  1. 若该镜头侧重对话或面部表情，必须加入【特写】或【近景】(close-up)。\n"
            "  2. 若该镜头侧重环境或转场，必须加入【远景】或【全景】(wide shot)。\n"
            "  3. 若该镜头侧重肢体动作，必须加入【中景】(medium shot)。\n"
            "数组中每个对象必须严格包含：\n"
            "\"index\": 镜头整数ID\n"
            "\"roles\": 字符串数组，列出该镜头出现的所有核心角色\n"
            "\"genders\": 字符串数组，对应 roles 中角色的性别，如 ['m', 'f']\n"
            "\"prompt_zh\": 必填！中文画面描述（仅词组，绝不可为空！）\n"
            "\"prompt_en\": 英文 Stable Diffusion 提示词"
        )

        if self.custom_template and "{ROLES}" in self.custom_template and "{SCENES}" in self.custom_template:
            prompt_content = self.custom_template.replace("{ROLES}", roles_desc).replace("{SCENES}",
                                                                                         scene_texts) + system_guardrail
        else:
            prompt_content = (
                    f"你是一个 Stable Diffusion 提示词专家。\n【角色设定】\n{roles_desc}\n\n【待处理镜头】\n{scene_texts}\n\n"
                    f"请为每个镜头生成提示词，务必包含所有传入的镜头ID，绝不可遗漏！\n"
                    + system_guardrail
            )

        retry_count = 0
        while retry_count < 3 and self.is_running:
            if retry_count == 0:
                self.log_signal.emit(self.session_id, self.project_path,
                                     f"正在并发请求镜头批次 {batch_scenes[0]['index']}~{batch_scenes[-1]['index']} ...")
            else:
                self.sys_log_signal.emit(self.session_id, self.project_path,
                                         f"⚠️ 批次 {batch_scenes[0]['index']} 接口异常，进行第 {retry_count} 次重试...")

            try:
                resp = ai_manager.generate_content(prompt_content, stream=False)

                if not self.is_running: return []

                cleaned = resp.replace("```json", "").replace("```", "").strip()
                parsed_data = None

                try:
                    parsed_data = json.loads(cleaned)
                except json.JSONDecodeError:
                    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                    if match:
                        try:
                            parsed_data = json.loads(match.group())
                        except:
                            pass

                if parsed_data and isinstance(parsed_data, list):
                    result_map = {}
                    for r in parsed_data:
                        if isinstance(r, dict) and 'index' in r:
                            try:
                                result_map[int(r['index'])] = r
                            except ValueError:
                                pass

                    batch_updates = []
                    for scene in batch_scenes:
                        res = result_map.get(scene['index'])
                        if res:
                            en_raw = res.get('prompt_en', '').strip()
                            zh_raw = res.get('prompt_zh', '').strip()

                            active_roles = res.get('roles', [])
                            if isinstance(active_roles, str):
                                active_roles = [active_roles]
                            elif not isinstance(active_roles, list):
                                active_roles = []

                            ai_genders = res.get('genders', [])
                            if isinstance(ai_genders, str):
                                ai_genders = [ai_genders.strip().lower()]
                            elif not isinstance(ai_genders, list):
                                ai_genders = []

                            missing_features = []
                            zh_missing_features = []
                            m_total = 0
                            f_total = 0

                            # 🌟 优化：自动将 AI 提取的“别名/尊称”映射回“主角色名”，保证生图特征统一
                            unified_active_roles = []

                            for i, role in enumerate(active_roles):
                                role = role.strip()
                                found_gender = None
                                r_desc = ""
                                unified_role_name = role

                                for rc in self.role_cards:
                                    rc_name = rc.get('name', '').strip()
                                    rc_aliases = rc.get('aliases', [])
                                    if isinstance(rc_aliases, str):
                                        rc_aliases = [a.strip() for a in rc_aliases.split(',') if a.strip()]
                                    elif not isinstance(rc_aliases, list):
                                        rc_aliases = []

                                    if role == rc_name or role in rc_aliases:
                                        unified_role_name = rc_name  # 统一修改为主名
                                        r_desc = rc.get('desc', '').strip()
                                        if '女' in r_desc or 'girl' in r_desc.lower() or 'woman' in r_desc.lower() or '妹' in r_desc or '姐' in r_desc:
                                            found_gender = 'f'
                                        elif '男' in r_desc or 'boy' in r_desc.lower() or 'man' in r_desc.lower() or '哥' in r_desc or '弟' in r_desc:
                                            found_gender = 'm'
                                        break

                                unified_active_roles.append(unified_role_name)

                                if not found_gender and i < len(ai_genders):
                                    if ai_genders[i] == 'm':
                                        found_gender = 'm'
                                    elif ai_genders[i] == 'f':
                                        found_gender = 'f'

                                if found_gender == 'm': m_total += 1
                                if found_gender == 'f': f_total += 1

                                weight = "1.25" if i == 0 else "0.8"
                                zh_weight_mark = "【主体】" if i == 0 else "【背景】"

                                gender_tag_en = "1boy, male focus" if found_gender == 'm' else (
                                    "1girl, female focus" if found_gender == 'f' else "")
                                gender_tag_zh = "1男" if found_gender == 'm' else ("1女" if found_gender == 'f' else "")

                                en_desc = self.translated_roles_map.get(unified_role_name, '')
                                if self._has_chinese(en_desc) or not en_desc:
                                    en_desc = r_desc if not self._has_chinese(r_desc) else ""

                                en_desc = en_desc.strip(' ,.')
                                r_desc = r_desc.strip(' ,.')

                                final_en_desc = f"{gender_tag_en}, {en_desc}".strip(' ,') if gender_tag_en else en_desc
                                final_zh_desc = f"{gender_tag_zh}, {r_desc}".strip(' ,') if gender_tag_zh else r_desc

                                final_en_desc = re.sub(r',\s*,+', ',', final_en_desc)
                                final_zh_desc = re.sub(r',\s*,+', ',', final_zh_desc)

                                if final_en_desc:
                                    missing_features.append(f"({final_en_desc}:{weight})")
                                if final_zh_desc:
                                    zh_missing_features.append(f"[{zh_weight_mark}{unified_role_name}:{final_zh_desc}]")

                            gender_lock_parts = []
                            zh_gender_lock_parts = []

                            if m_total > 0:
                                gender_lock_parts.append(f"{m_total}boys" if m_total > 1 else "1boy")
                                zh_gender_lock_parts.append(f"{m_total}男" if m_total > 1 else "1男")
                            if f_total > 0:
                                gender_lock_parts.append(f"{f_total}girls" if f_total > 1 else "1girl")
                                zh_gender_lock_parts.append(f"{f_total}女" if f_total > 1 else "1女")

                            gender_lock = ""
                            zh_gender_lock = ""
                            if gender_lock_parts:
                                gender_lock = "(" + ", ".join(gender_lock_parts) + ":1.2)"
                                zh_gender_lock = "[" + ",".join(zh_gender_lock_parts) + "]"

                            if missing_features:
                                features_str = " BREAK ".join(missing_features)
                                if gender_lock:
                                    en_raw = f"{gender_lock}, {features_str} BREAK {en_raw}"
                                else:
                                    en_raw = f"{features_str} BREAK {en_raw}"
                            elif gender_lock:
                                en_raw = f"{gender_lock}, {en_raw}"

                            if zh_missing_features:
                                zh_features_str = " | ".join(zh_missing_features)
                                if zh_gender_lock:
                                    zh_raw = f"{zh_gender_lock} | {zh_features_str} | {zh_raw}"
                                else:
                                    zh_raw = f"{zh_features_str} | {zh_raw}"
                            elif zh_gender_lock:
                                zh_raw = f"{zh_gender_lock} | {zh_raw}"

                            if en_raw:
                                en_raw = re.sub(r"\s*'s\b", "", en_raw)

                                if m_total > 0 and f_total == 0:
                                    en_raw = re.sub(r'\b(1girl|girl|woman|female|breasts|skirt|dress)\b', '', en_raw,
                                                    flags=re.IGNORECASE)

                                if f_total > 0 and m_total == 0:
                                    en_raw = re.sub(r'\b(1boy|boy|man|male|beard|mustache)\b', '', en_raw,
                                                    flags=re.IGNORECASE)

                                en_raw = re.sub(r'[\u4e00-\u9fa5]+', '', en_raw)
                                en_raw = re.sub(r'\([^\w]*:?\d*\.?\d*\)', '', en_raw)
                                en_raw = re.sub(r',\s*,+', ',', en_raw).strip(' ,.')

                            combined_prompt = f"[CN]: {zh_raw}\n[EN]: {en_raw}" if zh_raw or en_raw else ""

                            batch_updates.append({
                                'scene_index': scene['index'],
                                'data': {
                                    "prompt": combined_prompt,
                                    "prompt_en_raw": en_raw,
                                    "prompt_zh_raw": zh_raw,
                                    "prompt_zh_display": zh_raw,
                                    "roles": list(dict.fromkeys(unified_active_roles))  # 去重后保存统一的角色名
                                }
                            })
                        else:
                            fallback_text = scene['text']
                            safe_en = ""
                            if not translator_manager.is_empty():
                                trans_res, _ = translator_manager.translate(fallback_text, from_lang='zh', to_lang='en')
                                if trans_res: safe_en = trans_res

                            if not safe_en:
                                safe_en = "masterpiece, best quality, cinematic light"

                            combined_prompt = f"[CN]: (AI漏写兜底) {fallback_text}\n[EN]: {safe_en}"
                            batch_updates.append({
                                'scene_index': scene['index'],
                                'data': {
                                    "prompt": combined_prompt,
                                    "prompt_en_raw": safe_en,
                                    "prompt_zh_raw": fallback_text,
                                    "prompt_zh_display": fallback_text,
                                    "roles": []
                                }
                            })

                    return batch_updates

                else:
                    raise ValueError("API返回格式错误，未能解析出标准的列表数据")

            except Exception as e:
                if not self.is_running: return []
                retry_count += 1
                if retry_count >= 3:
                    self.sys_log_signal.emit(self.session_id, self.project_path,
                                             f"❌ 批次 {batch_scenes[0]['index']} 彻底失败跳过: {e}")
                    batch_updates = []
                    for scene in batch_scenes:
                        fallback_text = scene['text']
                        safe_en = ""
                        if not translator_manager.is_empty():
                            trans_res, _ = translator_manager.translate(fallback_text, from_lang='zh', to_lang='en')
                            if trans_res: safe_en = trans_res

                        if not safe_en:
                            safe_en = "masterpiece, best quality, cinematic light"

                        combined_prompt = f"[CN]: (接口超时兜底) {fallback_text}\n[EN]: {safe_en}"
                        batch_updates.append({
                            'scene_index': scene['index'],
                            'data': {
                                "prompt": combined_prompt,
                                "prompt_en_raw": safe_en,
                                "prompt_zh_raw": fallback_text,
                                "prompt_zh_display": fallback_text,
                                "roles": []
                            }
                        })
                    return batch_updates

                sleep_time = 2 ** retry_count
                for _ in range(int(sleep_time * 10)):
                    if not self.is_running: return []
                    time.sleep(0.1)
        return []


class ImageGenThread(QThread):
    log_signal = pyqtSignal(str)
    image_ready_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, node_list, scenes, target_list=None, role_map=None, translator=None, resolution="16:9"):
        super().__init__()
        self.node_list = node_list
        self.scenes = scenes
        self.target_list = target_list
        self.role_map = role_map if role_map else {}
        self.translator = translator
        self.is_interrupted = False

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def requestInterruption(self):
        self.is_interrupted = True

    def run(self):
        try:
            temp_dir = os.path.join(os.getcwd(), "temp_gen")
            if os.path.exists(temp_dir):
                now = time.time()
                for f_name in os.listdir(temp_dir):
                    f_path = os.path.join(temp_dir, f_name)
                    if os.path.isfile(f_path) and now - os.path.getmtime(f_path) > 86400:
                        try:
                            os.remove(f_path)
                        except:
                            pass
        except Exception:
            pass

        try:
            if not self.node_list:
                self.error_signal.emit("没有可用的 ComfyUI 节点或未配置工作流文件，请检查系统设置！")
                return

            tasks = [s for s in self.scenes if self.target_list is None or s['index'] in self.target_list]
            total = len(tasks)

            for i, scene in enumerate(tasks):
                if self.is_interrupted: break
                self.log_signal.emit(f"正在处理镜头 {scene['index']} ({i + 1}/{total})...")

                current_client_id = str(uuid.uuid4())

                full_prompt = scene.get('prompt', '') or scene.get('text', '')
                real_prompt = scene.get('prompt_en_raw', '').strip()
                if not real_prompt and "[EN]:" in full_prompt:
                    parts = full_prompt.split("[EN]:")
                    if len(parts) > 1:
                        real_prompt = parts[1].strip()
                if not real_prompt:
                    real_prompt = full_prompt

                real_prompt = re.sub(r'[\u4e00-\u9fa5]+', '', real_prompt)
                real_prompt = re.sub(r'\[(?:CN|EN)\]:?', '', real_prompt, flags=re.IGNORECASE)
                real_prompt = re.sub(r',\s*,+', ',', real_prompt).strip(' ,.')

                success = False
                available_nodes = list(self.node_list)
                random.shuffle(available_nodes)

                for node_info in available_nodes:
                    if self.is_interrupted: break

                    url = node_info.get('url', '').strip().rstrip('/')
                    if not url.startswith("http"): url = "http://" + url
                    wf_file = node_info.get('workflow', '')
                    node_name = node_info.get('name', '未命名节点')

                    try:
                        with open(wf_file, 'r', encoding='utf-8') as f:
                            workflow_template = json.loads(f.read())
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ {node_name} 工作流加载失败，尝试下一个。")
                        continue

                    prompt_payload = json.loads(json.dumps(workflow_template))

                    self._inject_prompt(prompt_payload, real_prompt)

                    ws_url = url.replace("http", "ws").replace("https", "wss") + f"/ws?clientId={current_client_id}"
                    ws = websocket.WebSocket()

                    try:
                        ws.connect(ws_url, timeout=5)
                        ws.settimeout(1.0)

                        p = {"prompt": prompt_payload, "client_id": current_client_id}
                        req = urllib.request.Request(f"{url}/prompt", data=json.dumps(p).encode('utf-8'))
                        with urllib.request.urlopen(req, timeout=15) as response:
                            prompt_id = json.loads(response.read()).get('prompt_id')

                        output_images = []
                        start_wait_time = time.time()

                        while True:
                            if self.is_interrupted: break

                            if time.time() - start_wait_time > 600:
                                self.log_signal.emit(f"⚠️ {node_name} 生图超时 (超过10分钟未响应)，强制放弃当前节点...")
                                break

                            try:
                                out = ws.recv()
                                if isinstance(out, str):
                                    message = json.loads(out)
                                    if message['type'] == 'executing' and message['data']['node'] is None and \
                                            message['data']['prompt_id'] == prompt_id:
                                        break
                                    elif message['type'] == 'executed' and message['data']['prompt_id'] == prompt_id:
                                        for _, imgs in message['data']['output'].items():
                                            output_images.extend(imgs)
                            except websocket.WebSocketTimeoutException:
                                continue

                        ws.close()

                        if self.is_interrupted: break

                        if output_images:
                            is_download_ok = self._download_and_save(output_images[0], scene['index'], url)
                            if is_download_ok:
                                success = True
                                self.log_signal.emit(f"🔌 {node_name} 极速生成并下载成功。")
                                break
                            else:
                                self.log_signal.emit(f"⚠️ {node_name} 图片生成但本地下载失败，准备切节点重试...")
                        else:
                            self.log_signal.emit(f"⚠️ {node_name} 未返回图片或超时退出，正在切换备用节点...")

                    except Exception as e:
                        self.log_signal.emit(f"⚠️ {node_name} 连接异常，正在切换备用节点...")
                        try:
                            ws.close()
                        except:
                            pass

                if not success and not self.is_interrupted:
                    self.log_signal.emit(f"❌ 镜头 {scene['index']} 致命错误：所有可用节点均尝试失败！")

            if not self.is_interrupted: self.finished_signal.emit()

        except Exception as e:
            self.error_signal.emit("生图引擎发生意外崩溃")

    def _inject_prompt(self, workflow, prompt_text):
        replaced_prompt = False
        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            if "inputs" in node_data:
                inputs = node_data["inputs"]
                for seed_key in ["seed", "noise_seed", "control_net_seed"]:
                    if seed_key in inputs and isinstance(inputs[seed_key], (int, float)):
                        inputs[seed_key] = random.randint(1, 10 ** 15)
                for k, v in inputs.items():
                    if isinstance(v, str):
                        if "{SCENES}" in v:
                            inputs[k] = v.replace("{SCENES}", prompt_text)
                            replaced_prompt = True

        if not replaced_prompt:
            for node_id, node_data in workflow.items():
                class_type = node_data.get("class_type", "")
                if "CLIPTextEncode" in class_type and "inputs" in node_data and "text" in node_data["inputs"]:
                    original = node_data["inputs"]["text"]
                    title = node_data.get("_meta", {}).get("title", "").lower()
                    is_negative = "neg" in title or "negative" in original.lower() or "low quality" in original.lower()

                    if not is_negative:
                        node_data["inputs"]["text"] = prompt_text

    def _download_and_save(self, img_info, scene_idx, base_url):
        dl_url = f"{base_url}/view?" + urllib.parse.urlencode(
            {'filename': img_info['filename'], 'subfolder': img_info['subfolder'], 'type': img_info['type']})
        try:
            temp_dir = os.path.join(os.getcwd(), "temp_gen")
            os.makedirs(temp_dir, exist_ok=True)
            local_path = os.path.abspath(os.path.join(temp_dir, f"shot_{scene_idx}_{uuid.uuid4().hex[:8]}.png"))

            with urllib.request.urlopen(dl_url, timeout=20) as response, open(local_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)

            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                self.log_signal.emit(f"✅ 镜头 {scene_idx} 图片下载成功")
                self.image_ready_signal.emit(scene_idx, local_path)
                return True
            else:
                raise Exception("文件大小为 0KB 或未落盘")

        except Exception as e:
            self.log_signal.emit(f"❌ 镜头 {scene_idx} 图片下载失败: {e}")
            return False


class ExportThread(QThread):
    finished_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    batch_finished_signal = pyqtSignal()

    def __init__(self, exporter, audio_path, images, subtitles=None, bgm_path=None, bgm_volume=0.2,
                 subtitle_effect_id="", resolution_mode="16:9"):
        super().__init__()
        self.exporter = exporter
        self.audio_path = audio_path
        self.images = images
        self.subtitles = subtitles
        self.bgm_path = bgm_path
        self.bgm_volume = bgm_volume
        self.subtitle_effect_id = subtitle_effect_id
        self.resolution_mode = resolution_mode

        _global_running_threads.append(self)
        self.finished.connect(self._cleanup_ref)

    def _cleanup_ref(self):
        if self in _global_running_threads:
            _global_running_threads.remove(self)

    def run(self):
        try:
            p = self.exporter.generate_draft(self.audio_path, self.images, self.subtitles, bgm_path=self.bgm_path,
                                             bgm_volume=self.bgm_volume, subtitle_effect_id=self.subtitle_effect_id,
                                             resolution_mode=self.resolution_mode)
            self.finished_signal.emit(p)
            self.batch_finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))
            self.batch_finished_signal.emit()