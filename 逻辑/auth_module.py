# 文件名: utils/auth_module.py

import os
import sys
import uuid
import socket
import subprocess
import hashlib
import requests
import base64
import threading

# =======================================================
# 1. 核心安全配置 (已接入云端验证)
# =======================================================
# 【修复】：将 HTTP 升级为 HTTPS，防止卡密在传输过程中被抓包窃取
SERVER_URL = "https://kanhai.pythonanywhere.com/verify"
# 当前软件的标识：推文软件
APP_NAME = "app_tuiven"

# 将卡密保存到系统 AppData 目录，防止更新软件或移动文件夹后丢失
APP_DATA_DIR = os.path.join(os.getenv('LOCALAPPDATA'), 'AI_Rewrite_App')
os.makedirs(APP_DATA_DIR, exist_ok=True)
LICENSE_FILE = os.path.join(APP_DATA_DIR, "license.key")


# =======================================================
# 2. 防多开模块 (单例模式)
# =======================================================
class SingleInstance:
    """
    【优化修复】：彻底抛弃 Socket 端口监听机制。
    改用 Windows 系统的 Mutex (互斥体) 机制。
    解决端口被其他软件占用、或者软件异常崩溃后端口未释放导致的“假多开/无法启动”问题。
    """

    def __init__(self, mutex_name="Global\\AI_Rewrite_App_Mutex_Lock"):
        self.mutex_name = mutex_name
        if os.name == 'nt':
            import ctypes
            self.kernel32 = ctypes.windll.kernel32
            self.mutex = self.kernel32.CreateMutexW(None, False, self.mutex_name)
            self.last_error = self.kernel32.GetLastError()
            if self.last_error == 183:  # ERROR_ALREADY_EXISTS (183)
                print("❌ 检测到软件已在运行，禁止多开！")
                sys.exit(0)
        else:
            # 兼容 Mac/Linux 的旧版备用方案
            self.port = 56821
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.sock.bind(("127.0.0.1", self.port))
            except socket.error:
                print("❌ 检测到软件已在运行，禁止多开！")
                sys.exit(0)


# =======================================================
# 3. 授权验证管理器 (云端联网版)
# =======================================================
class AuthManager:
    # 预留给主界面的信号槽句柄
    AUTH_FAILED_SIGNAL = None

    @staticmethod
    def get_machine_code():
        """
        【深度强化】：采用多级降级获取机器码，大大增加稳定性。
        优先读取 C 盘卷标物理序列号，其次读取注册表，再使用 wmic，最后兜底 MAC。
        防止正版用户由于重置网卡、使用 VPN 或插拔 U 盘导致机器码变化而掉激活。
        """
        uuid_str = ""

        # 第一级：读取 Windows C盘 卷标物理序列号 (最稳固，不格式化 C 盘绝对不变)
        if os.name == 'nt':
            try:
                import ctypes
                volume_serial = ctypes.c_uint32(0)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p("C:\\"), None, 0, ctypes.byref(volume_serial), None, None, None, 0
                )
                if volume_serial.value:
                    uuid_str += str(volume_serial.value)
            except Exception:
                pass

        # 第二级：读取 Windows 注册表 (备用稳定性)
        if not uuid_str and os.name == 'nt':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
                uuid_str, _ = winreg.QueryValueEx(key, "MachineGuid")
                winreg.CloseKey(key)
            except Exception:
                pass

        # 第三级：使用 wmic 物理层抓取 (增加了防溢出和报错保护)
        if not uuid_str:
            try:
                creationflags = 0x08000000 if os.name == 'nt' else 0
                cmd = 'wmic csproduct get uuid'
                output = subprocess.check_output(cmd, shell=True, creationflags=creationflags).decode('utf-8',
                                                                                                      errors='ignore')
                lines = [line.strip() for line in output.split('\n') if line.strip()]
                if len(lines) > 1:
                    uuid_str = lines[1]
            except Exception:
                pass

        # 第四级：兜底使用网卡 MAC 地址
        if not uuid_str:
            uuid_str = str(uuid.getnode())

        # 统一哈希处理
        machine_code = hashlib.sha256(uuid_str.encode('utf-8')).hexdigest()[:20].upper()
        return f"NTP-{machine_code}"

    @staticmethod
    def _encrypt_key(key):
        """【深度强化】：引入与机器码深度绑定的 XOR 动态异或混淆，彻底防御抓包复制和暴力解码"""
        machine = AuthManager.get_machine_code()
        salt = machine[:8]
        raw = f"AI_REWRITE_{key}_{salt}"
        # 逐字节与机器码进行异或运算，脱离了当前电脑该密文就是废纸
        xored = bytes([ord(c) ^ ord(machine[i % len(machine)]) for i, c in enumerate(raw)])
        return base64.b64encode(xored).decode('utf-8')

    @staticmethod
    def _decrypt_key(saved_str):
        """【增强】：智能解密，并自动向下兼容老版本的弱加密以及明文卡密"""
        machine = AuthManager.get_machine_code()
        salt = machine[:8]
        prefix = "AI_REWRITE_"
        suffix = f"_{salt}"

        # 1. 尝试使用新版强加密(XOR+Base64)进行解密
        try:
            xored = base64.b64decode(saved_str.encode('utf-8'))
            raw = "".join([chr(b ^ ord(machine[i % len(machine)])) for i, b in enumerate(xored)])
            if raw.startswith(prefix) and raw.endswith(suffix):
                return raw[len(prefix):-len(suffix)]
        except Exception:
            pass

        # 2. 尝试兼容旧版本弱加密 (仅Base64无XOR)
        try:
            raw = base64.b64decode(saved_str.encode('utf-8')).decode('utf-8')
            if raw.startswith(prefix) and raw.endswith(suffix):
                return raw[len(prefix):-len(suffix)]
        except Exception:
            pass

        # 3. 如果全部失败，说明是极早期尚未加密存储的明文，直接返回
        return saved_str

    @staticmethod
    def activate_with_key(user_key):
        """客户端专用：向云端服务器发起验证，如果成功则在本地保存密文卡密"""
        user_key = user_key.strip()
        if not user_key:
            return False, "请输入激活卡密！"

        # 【新增：开发者测试后门】
        # 识别到特定测试密钥时，直接绕过云端请求，强行激活成功
        if user_key == "test8888":
            encrypted_key = AuthManager._encrypt_key(user_key)
            with open(LICENSE_FILE, 'w', encoding='utf-8') as f:
                f.write(encrypted_key)
            return True, "【开发者模式】免云端校验，测试通道激活成功！"

        machine_code = AuthManager.get_machine_code()
        payload = {
            "app_name": APP_NAME,
            "key": user_key,
            "machine_code": machine_code
        }

        try:
            response = requests.post(SERVER_URL, json=payload, timeout=10)
            data = response.json()

            if data.get("status") == "success":
                # 激活成功后，强力加密保存到本地
                encrypted_key = AuthManager._encrypt_key(user_key)
                with open(LICENSE_FILE, 'w', encoding='utf-8') as f:
                    f.write(encrypted_key)
                return True, data.get("msg", "激活成功！")
            else:
                return False, data.get("msg", "激活失败！")

        except requests.exceptions.RequestException as e:
            return False, f"无法连接到验证服务器，请检查您的网络！\n错误信息: {e}"
        except Exception as e:
            return False, f"发生未知错误：{e}"

    @staticmethod
    def load_local_license():
        """
        【深度修复】：彻底解决网络不佳导致软件启动假死的问题。
        采用“本地快验放行” + “云端异步猎杀”机制。
        """
        if not os.path.exists(LICENSE_FILE):
            return False, "未找到授权文件，请激活软件！"

        try:
            with open(LICENSE_FILE, 'r', encoding='utf-8') as f:
                saved_str = f.read().strip()

            if not saved_str:
                return False, "授权文件已损坏，请重新激活！"

            # 优先进行本地解密，只要能解开且格式正确，主界面直接秒开，不需要死等网络
            saved_key = AuthManager._decrypt_key(saved_str)

            # 【新增：开发者测试后门拦截】
            # 如果本地解密发现是测试密钥，直接放行，且【不启动】后台验卡查杀线程
            if saved_key == "test8888":
                return True, "【开发者测试通道】本地验证通过"

            # 定义后台静默猎杀线程
            def silent_cloud_verify():
                try:
                    machine_code = AuthManager.get_machine_code()
                    payload = {
                        "app_name": APP_NAME,
                        "key": saved_key,
                        "machine_code": machine_code
                    }
                    response = requests.post(SERVER_URL, json=payload, timeout=8)
                    data = response.json()

                    if data.get("status") != "success":
                        # 🌟【核心修复点】：卡密失效或判定非法时，必须将本地的过期卡密文件删除！
                        AuthManager.clear_license()

                        # 【深度漏洞修复】：放弃暴力的 os._exit(0)，改用安全信号触发优雅关闭，防止残留幽灵浏览器吃满内存
                        signal = getattr(AuthManager, 'AUTH_FAILED_SIGNAL', None)
                        msg = "您的授权已失效或检测到非法登录，为了安全起见，程序即将强制退出！\n下次打开软件将重新进入卡密激活界面。"

                        if signal:
                            # 发射给主窗口，由主窗口负责销毁浏览器并安全退出
                            signal.emit(msg)
                        else:
                            # 兜底保护：如果主窗口尚未完全建立信号连接
                            if os.name == 'nt':
                                import ctypes
                                ctypes.windll.user32.MessageBoxW(0, msg, "安全拦截", 16)
                            os._exit(0)
                except requests.exceptions.RequestException:
                    # 断网宽容模式：如果在后台验卡时根本没网，就暂时放行，不封杀
                    pass
                except Exception:
                    pass

            # 启动守护线程在后台慢慢去和服务器验卡，绝不阻碍用户看到主界面
            verify_thread = threading.Thread(target=silent_cloud_verify, daemon=True)
            verify_thread.start()

            # 如果检测到本地当前存储的是明文或旧版弱加密，顺手将其重新高强度加密覆盖
            try:
                encrypted_latest = AuthManager._encrypt_key(saved_key)
                if saved_str != encrypted_latest:
                    with open(LICENSE_FILE, 'w', encoding='utf-8') as fw:
                        fw.write(encrypted_latest)
            except Exception:
                pass

            return True, "本地验证通过"

        except Exception as e:
            return False, f"本地授权读取严重异常，请联系客服：{e}"

    @staticmethod
    def get_current_card_key():
        """获取当前绑定的卡密明文 (用于在设置页展示给用户看，或是进行解绑)"""
        if not os.path.exists(LICENSE_FILE):
            return ""
        try:
            with open(LICENSE_FILE, 'r', encoding='utf-8') as f:
                saved_str = f.read().strip()
            return AuthManager._decrypt_key(saved_str)
        except Exception:
            return ""

    @staticmethod
    def clear_license():
        """一键解绑：删除本地的卡密记录文件"""
        if os.path.exists(LICENSE_FILE):
            try:
                os.remove(LICENSE_FILE)
                return True
            except Exception:
                return False
        return True