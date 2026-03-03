import google.generativeai as genai
import json
import ast
import re  # 🌟 用于清洗幽灵提示词和无效字符


class AIPlanner:
    def __init__(self, api_key):
        """
        初始化 AI 策划模块
        """
        if not api_key:
            raise ValueError("API Key 不能为空")
        genai.configure(api_key=api_key)
        # 使用更智能的模型处理复杂逻辑
        self.model = genai.GenerativeModel('gemini-2.0-flash')

    def extract_character_info(self, full_text):
        """
        功能：提取角色、动物及关键物体信息
        """
        # 🌟 核心修复：将提取范围扩大至所有视觉主体
        prompt = f"""
        【最高指令】：你现在是一个“视觉主体特征提取器”。请阅读以下小说内容。
        任务：提取所有出场角色、关键动物（如鸽子、猫等）或具有视觉特征的重要物品。

        【极其重要的格式警告】：
        1. 总结格式必须清晰，每个主体一段。
        2. 【绝对禁止】使用完整的句子或废话！必须全部转化为视觉标签短语，用逗号隔开！
        3. 如果是动物或物品，请重点描述种类、毛色、质感、体态。

        【强制格式示例】：
        林凡：男人，29岁，黑色寸头，现代休闲装，黑色皮鞋。
        肥鸽子：雄性鸽子，3岁，灰白羽毛，黑色翅膀条纹，体态肥硕，明亮眼睛。

        小说内容：
        {full_text[:15000]} 
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"提取失败: {str(e)}"

    def infer_scene_prompts(self, subtitle_data, role_info):
        """
        功能：根据设定库和字幕，推理精准的分镜提示词
        """
        # 准备数据，简化格式以节省 Token
        full_text_list = [f"ID:{item['index']} 内容:{item['text']}" for item in subtitle_data]
        full_text_str = "\n".join(full_text_list)

        # 🌟 核心升级：注入主体包容性指令，禁止关键词污染
        prompt = f"""
        【最高指令】：你是一个顶级分镜摄影师。请根据【设定库】和【字幕内容】，为每一句字幕生成精准的画面标签。

        【设定库（包含角色、动物或关键物）】：
        {role_info}

        【任务逻辑】：
        1. **识别当前主体**：画面主体可能是人，也可能是动物（如肥鸽子）或特定物件。
        2. **禁止胡乱关联（致命警告）**：严禁输出文中未提及的分类关联词（如看到鸽子禁止输出“猫狗鸟鱼”、看到街道禁止输出“地图”、看到严肃禁止输出“间谍教授任务”）。
        3. **prompt_zh 强制公式**：
           主体（人/动/物），[主体细节特征]，[当前动作/姿态]，[景别]，背景[环境描述]，[光影氛围]

        【🌟动态景别分配规则（强制执行）】：
        - 侧重对话、表情或主体的局部细节（如鸽子的翅膀）：必须含【特写】或【近景】。
        - 侧重肢体动作或主体的完整形态：必须含【中景】。
        - 侧重宏观环境、转场或远距离观察：必须含【远景】或【全景】。

        【格式要求】：
        - 禁止使用“着、了、正在、注视、身穿”等叙事性动词。
        - 必须返回 JSON 列表。示例：[{{ "index": 1, "prompt_zh": "画面描述", "prompt_en": "Stable Diffusion Prompt" }}]

       【prompt_en 规则】：
        - **严禁中文字符**。
        - **【性别绝对隔离法则】（至关重要）**：
            1. 男性角色开头必须包含：`(1boy, male focus, masculine:1.5), (girl:0.0), (female:0.0)` —— 利用负向权重彻底屏蔽女性特征。
            2. 女性角色开头必须包含：`(1girl, female focus, feminine:1.3)`。
            3. 涉及多人同框时，必须先描述男性特征，再描述女性特征，尽可能用 `BREAK` 关键词（如果有）或简短句式隔开。
        - **特征绑定**：紧跟在性别标签后立即描述发型、发色和衣着（如 `1boy, short black hair, suit`），防止特征漂移到其他人身上。
        - **主体标识补充**：动物/物体 `(animal focus:1.2)` 或 `(object focus:1.2)`。

        【分镜字幕内容】：
        {full_text_str}
        """

        try:
            response = self.model.generate_content(prompt)
            text_result = response.text.replace("```json", "").replace("```", "").strip()

            # JSON 解析与容错
            try:
                json_result = json.loads(text_result)
            except json.JSONDecodeError:
                if text_result.startswith("[") and text_result.endswith("]"):
                    json_result = ast.literal_eval(text_result)
                else:
                    raise ValueError("API返回格式无法解析")

            # 提取双语提示词并进行物理清洗
            prompt_map = {}
            # 🌟 物理屏蔽词表：防止 AI 产生幽灵联想
            ghost_words = r'密集地图|猫狗鸟鱼|间谍教授任务|未知任务|系统提示|分类标签'

            for item in json_result:
                idx = item.get('index')
                if idx is not None:
                    prompt_zh = item.get('prompt_zh', '')
                    prompt_en = item.get('prompt_en', '')

                    # 1. 强力清洗中文：删除幽灵词、废话介词、标点
                    if prompt_zh:
                        prompt_zh = re.sub(ghost_words, '', prompt_zh)
                        prompt_zh = re.sub(r'注视着|看着|身穿|穿着|笼罩在|充斥着|带有.*?的一丝|以.*?的神情', '',
                                           prompt_zh)
                        prompt_zh = re.sub(r'。|！|？|；', ',', prompt_zh)
                        prompt_zh = re.sub(r'\s+', ',', prompt_zh)
                        prompt_zh = re.sub(r',+', ',', prompt_zh).strip(',')

                    # 2. 强力清洗英文：删除中文、空括号、多余逗号
                    if prompt_en:
                        prompt_en = re.sub(r'[\u4e00-\u9fa5]+', '', prompt_en)
                        prompt_en = re.sub(r'\([^\w]*:?\d*\.?\d*\)', '', prompt_en)
                        prompt_en = re.sub(r',\s*,+', ',', prompt_en).strip(' ,.')

                    combined_prompt = ""
                    if prompt_zh or prompt_en:
                        combined_prompt = f"[CN]: {prompt_zh}\n[EN]: {prompt_en}"

                    prompt_map[idx] = {
                        'prompt_zh': prompt_zh,
                        'prompt_en_raw': prompt_en,
                        'prompt': combined_prompt
                    }

            count = 0
            for item in subtitle_data:
                idx = item['index']
                if idx in prompt_map:
                    item['prompt_zh'] = prompt_map[idx]['prompt_zh']
                    item['prompt_en_raw'] = prompt_map[idx]['prompt_en_raw']
                    item['prompt'] = prompt_map[idx]['prompt']
                    item['status'] = "提示词已生成"
                    count += 1

            return subtitle_data, count

        except Exception as e:
            raise Exception(f"分镜推理失败: {str(e)}")