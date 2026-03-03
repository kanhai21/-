# config.py
# 用于存放全局配置和默认设置

import os

# 默认的ComfyUI地址 (本地默认端口)
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"

# 临时图片保存路径
IMAGE_OUTPUT_DIR = os.path.join(os.getcwd(), "output_images")

# 确保输出目录存在
if not os.path.exists(IMAGE_OUTPUT_DIR):
    os.makedirs(IMAGE_OUTPUT_DIR)

# 剪映草稿的默认保存位置 (Windows默认)
# 注意：你需要根据实际情况修改用户名
JIANYING_DRAFT_DIR = r"C:\Users\YourUserName\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"