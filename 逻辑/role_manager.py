from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QInputDialog
from 逻辑.app_workers import RoleExtractThread
import json


class RoleManager(QObject):
    roles_updated = pyqtSignal()  # 当角色列表发生变化时发射

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window  # 这里引用的是 ProjectEditor 实例
        self.thread = None

    def add_role_card(self, name="", desc="", aliases=None):
        """添加角色到数据中，支持别名查重与智能合并"""
        if aliases is None:
            aliases = []
        elif isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(',') if a.strip()]

        roles = self.main_window.data.get('role_cards', [])

        # 🌟 优化：强化查重，检查主名称或别名是否已存在于其他角色中
        for r in roles:
            existing_name = r.get('name', '')
            existing_aliases = r.get('aliases', [])
            if isinstance(existing_aliases, str):
                existing_aliases = [existing_aliases]

            is_same_person = False
            # 判断是否是同一个人
            if name == existing_name or name in existing_aliases or existing_name in aliases:
                is_same_person = True
            elif set(aliases).intersection(set(existing_aliases)):
                is_same_person = True

            if is_same_person:
                # 合并别名
                combined_aliases = list(set(existing_aliases + aliases + [name]) - {existing_name})
                r['aliases'] = combined_aliases

                # 如果新描述更长或原描述为空，则更新描述
                if desc and len(desc) > len(r.get('desc', '')):
                    r['desc'] = desc
                elif desc and not r.get('desc', ''):
                    r['desc'] = desc

                self.main_window.mark_modified()
                self.main_window.save_proj(silent=True)
                self.roles_updated.emit()
                return

        # 如果不存在，作为新角色添加
        roles.append({"name": name, "desc": desc, "aliases": aliases})
        self.main_window.data['role_cards'] = roles
        self.main_window.mark_modified()
        self.main_window.save_proj(silent=True)
        self.roles_updated.emit()

    def add_empty_role_card(self):
        """添加空角色"""
        self.add_role_card("新角色", "", [])

    def clear_roles(self):
        """清空角色数据"""
        self.main_window.data['role_cards'] = []
        self.main_window.mark_modified()
        self.main_window.save_proj(silent=True)
        self.roles_updated.emit()

    def run_extract(self):
        """执行角色提取 (线程化，防止UI卡死)"""
        text_content = ""
        scenes = self.main_window.data.get('scenes', [])

        # 优先使用分镜内容，如果为空则尝试使用原始字幕
        if scenes:
            text_content = "\n".join([s['text'] for s in scenes])
        elif hasattr(self.main_window, 'raw_data') and self.main_window.raw_data:
            text_content = "\n".join([s['text'] for s in self.main_window.raw_data])

        if not text_content:
            QMessageBox.warning(self.main_window, "提示", "没有可供分析的文本内容，请先导入字幕或生成分镜。")
            return

        if hasattr(self.main_window, 'studio_page'):
            self.main_window.studio_page.log("🚀 正在启动角色提取任务...", color="#55ffff")

        # 读取自定义指令模板
        role_template = self.main_window.data.get('role_extract_template', '')

        # 如果之前的线程还在运行，先安全停止
        self.cancel()

        self.thread = RoleExtractThread(text_content, custom_template=role_template)
        self.thread.finished_signal.connect(self.on_extract_finished)
        self.thread.error_signal.connect(self.on_extract_error)

        # 连接日志信号，增加容错防崩溃
        if hasattr(self.main_window, 'studio_page'):
            self.thread.log_signal.connect(
                lambda msg: self.main_window.studio_page.log(msg) if hasattr(self, 'main_window') else None
            )

        self.thread.start()

    def on_extract_finished(self, roles):
        """提取完成后的处理"""
        # 防崩溃检查：如果此时 UI 已经被销毁了，立刻退出
        try:
            if not hasattr(self, 'main_window') or self.main_window is None:
                return
        except Exception:
            return

        self.clear_roles()  # 先清空旧数据

        count = 0
        for r in roles:
            name = r.get('name', '').strip()
            if name:
                # 🌟 优化：提取时将 aliases 传递给添加函数
                aliases = r.get('aliases', [])
                self.add_role_card(name, r.get('desc', ''), aliases)
                count += 1

        # 刷新界面并自动保存 (增加 try-except 容错机制)
        try:
            if hasattr(self.main_window, 'studio_page'):
                self.main_window.studio_page.log(f"✅ 提取完成，共识别 {count} 个角色", color="#55ff55")
            self.main_window.save_proj(silent=True)
        except Exception:
            pass  # 如果UI刚好被关闭，吃掉异常防止崩溃

        self.thread = None

    def on_extract_error(self, err):
        """提取错误处理"""
        try:
            if hasattr(self.main_window, 'studio_page'):
                self.main_window.studio_page.log(f"❌ 角色提取失败: {err}", color="#ff5555")

            # 如果是正常取消导致的中断，不弹窗报错
            if "cancelled" not in str(err).lower():
                QMessageBox.critical(self.main_window, "提取失败", str(err))
        except Exception:
            pass

        self.thread = None

    def import_from_file(self):
        """从文件导入角色"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self.main_window, "导入角色", "", "Text (*.txt);;JSON (*.json)")
        if not path:
            return

        try:
            # 修复：统一使用 utf-8-sig 防止带 BOM 的文件读取失败/乱码
            with open(path, 'r', encoding='utf-8-sig') as f:
                content = f.read()

            count = 0
            if path.endswith(".json"):
                data = json.loads(content)
                if isinstance(data, list):
                    for r in data:
                        # 🌟 优化：支持导入带 aliases 字段的数据
                        self.add_role_card(r.get('name', ''), r.get('desc', ''), r.get('aliases', []))
                        count += 1
                elif isinstance(data, dict):
                    for k, v in data.items():
                        self.add_role_card(k, v)
                        count += 1
            else:
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line: continue

                    parts = line.split('：', 1)
                    if len(parts) < 2:
                        parts = line.split(':', 1)
                    if len(parts) == 2:
                        self.add_role_card(parts[0].strip(), parts[1].strip())
                        count += 1

            self.main_window.save_proj(silent=True)
            QMessageBox.information(self.main_window, "成功", f"成功导入 {count} 个角色并已保存")
        except Exception as e:
            QMessageBox.warning(self.main_window, "错误", f"导入失败: {e}")

    def cancel(self):
        """安全取消正在进行的角色提取任务，防卡死防崩溃"""
        if self.thread and self.thread.isRunning():
            # 1. 尝试断开所有信号，防止向已关闭的UI发送更新
            try:
                self.thread.finished_signal.disconnect()
                self.thread.error_signal.disconnect()
                self.thread.log_signal.disconnect()
            except Exception:
                pass

            # 2. 发送中断指令让线程自行退出
            self.thread.cancel()

            # 3. 【绝对不调用 wait()】，防止主界面卡死！

            try:
                if hasattr(self.main_window, 'studio_page'):
                    self.main_window.studio_page.log("🛑 角色提取任务已手动取消", color="#ffaa00")
            except Exception:
                pass

            self.thread = None