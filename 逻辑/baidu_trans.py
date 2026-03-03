import hashlib
import random
import requests
import time

class BaiduTranslator:
    def __init__(self, app_id, secret_key):
        self.app_id = app_id
        self.secret_key = secret_key
        self.api_url = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    def translate(self, query, from_lang='zh', to_lang='en'):
        if not self.app_id or not self.secret_key:
            return None, "未配置百度翻译 API Key"

        salt = random.randint(32768, 65536)
        sign_str = f"{self.app_id}{query}{salt}{self.secret_key}"
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        payload = {
            'appid': self.app_id,
            'q': query,
            'from': from_lang,
            'to': to_lang,
            'salt': salt,
            'sign': sign
        }

        try:
            r = requests.post(self.api_url, params=payload, headers=headers, timeout=5)
            result = r.json()
            if "trans_result" in result:
                return result["trans_result"][0]["dst"], None
            else:
                return None, f"翻译错误: {result.get('error_msg', '未知错误')}"
        except Exception as e:
            return None, f"请求异常: {str(e)}"