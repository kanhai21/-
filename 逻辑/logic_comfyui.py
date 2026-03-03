import json
import urllib.request
import urllib.parse
import uuid
import websocket  # pip install websocket-client
import time
import os
import random

from 配置.app_config import get_global_style_settings


class ComfyUILogic:
    def __init__(self, server_address):
        """
        :param server_address: ComfyUI地址，例如 "http://127.0.0.1:8188"
        """
        # 统一清洗地址格式
        self.server_address = server_address.replace("http://", "").replace("https://", "").strip("/")
        self.client_id = str(uuid.uuid4())
        self.ws = None

    def find_positive_prompt_node(self, workflow):
        """
        智能查找正向提示词节点 ID
        策略：找到 KSampler -> 顺藤摸瓜找到 positive 输入对应的 CLIPTextEncode
        """
        ksampler_id = None
        # 1. 先找 KSampler
        for node_id, node_data in workflow.items():
            if "KSampler" in node_data.get("class_type", ""):
                ksampler_id = node_id
                break

        if not ksampler_id:
            # 备用方案：直接找第一个 CLIPTextEncode
            for node_id, node_data in workflow.items():
                if node_data.get("class_type") == "CLIPTextEncode":
                    return node_id
            return None

        # 2. 找连接到 positive 的节点
        try:
            # KSampler 的 inputs 里的 positive 通常是一个列表 [node_id, slot_index]
            positive_link = workflow[ksampler_id]["inputs"].get("positive")
            if isinstance(positive_link, list):
                return positive_link[0]
        except:
            pass

        return None

    def find_negative_prompt_node(self, workflow):
        """
        智能查找负向提示词节点 ID
        """
        ksampler_id = None
        for node_id, node_data in workflow.items():
            if "KSampler" in node_data.get("class_type", ""):
                ksampler_id = node_id
                break

        if not ksampler_id: return None

        try:
            negative_link = workflow[ksampler_id]["inputs"].get("negative")
            if isinstance(negative_link, list):
                return negative_link[0]
        except:
            pass
        return None

    def queue_prompt(self, prompt_workflow):
        """发送任务到队列"""
        p = {"prompt": prompt_workflow, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        url = f"http://{self.server_address}/prompt"
        req = urllib.request.Request(url, data=data)
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read())
        except Exception as e:
            print(f"[ComfyUI Error] Queue Prompt Failed: {e}")
            raise e

    def get_image(self, filename, subfolder, folder_type):
        """下载图片数据"""
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        url = f"http://{self.server_address}/view?{url_values}"
        try:
            with urllib.request.urlopen(url) as response:
                return response.read()
        except Exception as e:
            print(f"[ComfyUI Error] Download Image Failed: {e}")
            return None

    def get_history(self, prompt_id):
        url = f"http://{self.server_address}/history/{prompt_id}"
        try:
            with urllib.request.urlopen(url) as response:
                return json.loads(response.read())
        except Exception as e:
            print(f"[ComfyUI Error] Get History Failed: {e}")
            return {}

    def generate_image(self, prompt_text, output_path, workflow_template):
        """
        核心生图函数
        :param prompt_text: AI推理出的提示词
        :param output_path: 图片保存绝对路径
        :param workflow_template: 工作流字典(JSON)
        """
        # 1. 深度复制工作流，避免修改原板
        workflow = json.loads(json.dumps(workflow_template))

        # 🌟 读取全局画风设置
        style_cfg = get_global_style_settings()
        global_pos = style_cfg.get("pos_prompt", "").strip()
        global_neg = style_cfg.get("neg_prompt", "").strip()

        # 🌟 【核心修复 1】：拼装正向词，把全局画风放在最前面并加高权重(1.3)强制生效
        if global_pos:
            final_pos_prompt = f"({global_pos}:1.3), {prompt_text}".strip(", ")
        else:
            final_pos_prompt = prompt_text

        # 2. 【关键修复】将 final_pos_prompt 填入工作流正向节点
        target_node_id = self.find_positive_prompt_node(workflow)

        if target_node_id and target_node_id in workflow:
            inputs = workflow[target_node_id].get("inputs", {})
            if "text" in inputs:
                inputs["text"] = final_pos_prompt
            elif "text_g" in inputs:  # SDXL 节点
                inputs["text_g"] = final_pos_prompt
                if "text_l" in inputs: inputs["text_l"] = final_pos_prompt
            else:
                inputs["text"] = final_pos_prompt
            print(f"[ComfyUI] 已将提示词注入节点 [{target_node_id}]")
        else:
            print("[ComfyUI Warning] 未能智能识别正向提示词节点，尝试暴力搜索 CLIPTextEncode...")
            for nid, node in workflow.items():
                if node.get("class_type") == "CLIPTextEncode":
                    current_text = node["inputs"].get("text", "")
                    if "negative" not in current_text.lower() and "low quality" not in current_text.lower():
                        node["inputs"]["text"] = final_pos_prompt
                        print(f"[ComfyUI] 已注入节点 {nid}")
                        break

        # 🌟 3. 【核心修复 2】：注入全局负面提示词，同样放在最前面并加权重压制写实
        if global_neg:
            neg_node_id = self.find_negative_prompt_node(workflow)
            if neg_node_id and neg_node_id in workflow:
                inputs = workflow[neg_node_id].get("inputs", {})
                orig_neg = inputs.get("text", "") or inputs.get("text_g", "")

                final_neg = f"({global_neg}:1.3), {orig_neg}".strip(", ") if orig_neg else f"({global_neg}:1.3)"

                if "text" in inputs:
                    inputs["text"] = final_neg
                elif "text_g" in inputs:
                    inputs["text_g"] = final_neg
                    if "text_l" in inputs: inputs["text_l"] = final_neg
                else:
                    inputs["text"] = final_neg
                print(f"[ComfyUI] 已注入全局负面提示词节点 [{neg_node_id}]")
            else:
                # 暴力搜索负向节点
                for nid, node in workflow.items():
                    if node.get("class_type") == "CLIPTextEncode":
                        current_text = node["inputs"].get("text", "")
                        if "negative" in current_text.lower() or "low quality" in current_text.lower():
                            final_neg = f"({global_neg}:1.3), {current_text}".strip(
                                ", ") if current_text else f"({global_neg}:1.3)"
                            node["inputs"]["text"] = final_neg
                            print(f"[ComfyUI] 暴力注入全局负面节点 {nid}")
                            break

        # 4. 建立 WebSocket 连接监听进度
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(f"ws://{self.server_address}/ws?clientId={self.client_id}")
        except Exception as e:
            return False, f"WebSocket连接失败: {str(e)}"

        # 5. 提交任务
        try:
            prompt_res = self.queue_prompt(workflow)
            if not prompt_res:
                return False, "提交任务失败，请检查 ComfyUI 控制台"
            prompt_id = prompt_res['prompt_id']
        except Exception as e:
            return False, f"提交任务异常: {e}"

        # 6. 监听 WebSocket 等待执行完成
        print(f"[ComfyUI] 任务已提交 ID: {prompt_id}，等待生成...")
        while True:
            try:
                out = self.ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    if message['type'] == 'executing':
                        data = message['data']
                        if data['node'] is None and data['prompt_id'] == prompt_id:
                            # 执行结束
                            break
            except Exception as e:
                print(f"[ComfyUI] WebSocket 接收异常 (可能已完成): {e}")
                break  # 尝试去取结果

        # 7. 获取结果并下载
        history = self.get_history(prompt_id)
        if prompt_id not in history:
            return False, "未找到任务历史，可能生成失败"

        outputs = history[prompt_id].get('outputs', {})

        # 遍历所有节点寻找图片输出
        for node_id in outputs:
            node_output = outputs[node_id]
            if 'images' in node_output:
                for image in node_output['images']:
                    # 只要保存第一张图
                    img_data = self.get_image(image['filename'], image['subfolder'], image['type'])
                    if img_data:
                        # 确保目录存在
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        with open(output_path, 'wb') as f:
                            f.write(img_data)
                        self.ws.close()
                        return True, "Success"

        self.ws.close()
        return False, "未在输出中找到图片数据"