import asyncio
import threading
import json
import os
import time as time_module
import csv
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import customtkinter as ctk

try:
    from plyer import notification as plyer_notif
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

from telethon import TelegramClient, events
from telethon.tl.functions.account import CheckUsernameRequest
from telethon.tl.types import ChatBannedRights
from telethon.tl.functions.channels import EditBannedRequest
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# ── CustomTkinter 主题 ────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── 颜色常量（Telegram 深色风格）─────────────────────────────────────────────
BG      = "#17212b"
PANEL   = "#1c2733"
SIDEBAR = "#232e3c"
ACCENT  = "#2AABEE"
ACCENT2 = "#1a7abf"
TEXT    = "#e8f1f8"
MUTED   = "#708fa0"
SUCCESS = "#4dcd5e"
ERROR   = "#f05454"
WARN    = "#f5a623"
INPUT   = "#242f3d"
BORDER  = "#2b3d53"
BTN_BG  = "#2b5278"

CONFIG_FILE = "config.json"


# ── 彩色日志控件 ──────────────────────────────────────────────────────────────
class DarkLog(ctk.CTkTextbox):
    """基于 CTkTextbox 的彩色日志控件。"""
    def __init__(self, parent, **kw):
        super().__init__(
            parent,
            fg_color="#0d1520",
            text_color=TEXT,
            font=("Consolas", 9),
            state="disabled",
            wrap="word",
            **kw,
        )
        self._textbox.tag_config("ok",   foreground=SUCCESS)
        self._textbox.tag_config("err",  foreground=ERROR)
        self._textbox.tag_config("warn", foreground=WARN)
        self._textbox.tag_config("info", foreground=ACCENT)
        self._textbox.tag_config("time", foreground=MUTED)

    def append(self, msg):
        self.configure(state="normal")
        ts = f"[{datetime.now().strftime('%H:%M:%S')}] "
        self._textbox.insert("end", ts, "time")
        if msg.startswith("✅"):
            self._textbox.insert("end", msg + "\n", "ok")
        elif msg.startswith("❌"):
            self._textbox.insert("end", msg + "\n", "err")
        elif msg.startswith("🔔") or msg.startswith("⚠"):
            self._textbox.insert("end", msg + "\n", "warn")
        else:
            self._textbox.insert("end", msg + "\n")
        self._textbox.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


# ── 右下角 Toast 通知 ─────────────────────────────────────────────────────────
class Toast:
    def __init__(self, root, message, duration=3000, color=SUCCESS):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=SIDEBAR)
        w, h = 320, 54
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 64}")
        tk.Label(
            self.win, text=message, bg=SIDEBAR, fg=color,
            font=("微软雅黑", 9), wraplength=295, justify="left",
            padx=14, pady=12,
        ).pack(fill="both", expand=True)
        self.win.after(duration, self._dismiss)

    def _dismiss(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ── 主应用 ────────────────────────────────────────────────────────────────────
class TelegramTool:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("TG 多功能工具  v2.0  |  by 岁岁 @qqfaka")
        self.root.configure(fg_color=BG)
        self.root.resizable(True, True)

        self.config   = self._load_config()
        self.client   = None
        self.loop     = asyncio.new_event_loop()

        # 多账号
        self.accounts            = self.config.get("accounts", [])
        self.current_account_idx = -1

        # 模板库
        self.templates = self.config.get("templates", [])

        # 成员缓存（群组 + 批量私信共用）
        self._members_cache: list = []

        # 任务状态
        self.forwarding_active        = False
        self.monitoring_active        = False
        self.username_checking_active = False
        self.bulkpm_active            = False
        self.scheduled_jobs: list     = []
        self._usernames_to_check: list = []

        # 恢复窗口大小
        geo = self.config.get("window_geometry", "1040x720")
        try:
            self.root.geometry(geo)
        except Exception:
            self.root.geometry("1040x720")
        self.root.bind("<Configure>", self._on_resize)

        threading.Thread(target=self._run_loop,         daemon=True).start()
        threading.Thread(target=self._scheduler_thread, daemon=True).start()

        self._build_ui()
        self._restore_config()
        self._switch_tab("login")

    # ── 窗口尺寸记忆 ──────────────────────────────────────────────────────────
    def _on_resize(self, event):
        if event.widget == self.root:
            if hasattr(self, "_resize_job"):
                self.root.after_cancel(self._resize_job)
            self._resize_job = self.root.after(
                800, lambda: self.config.update(
                    {"window_geometry": self.root.geometry()}
                ) or self._save_config()
            )

    # ── 事件循环 ──────────────────────────────────────────────────────────────
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _ui(self, fn, *args, **kwargs):
        self.root.after(0, lambda: fn(*args, **kwargs))

    # ── 配置 ──────────────────────────────────────────────────────────────────
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config(self):
        self.config["accounts"]  = self.accounts
        self.config["templates"] = self.templates
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    # ── 通知 ──────────────────────────────────────────────────────────────────
    def _notify(self, title, message):
        if HAS_PLYER:
            try:
                plyer_notif.notify(title=title, message=message, timeout=8)
                return
            except Exception:
                pass
        self._ui(messagebox.showinfo, title, message)

    def _toast(self, message, color=SUCCESS):
        self._ui(lambda: Toast(self.root, message, color=color))

    # ── 日志 ──────────────────────────────────────────────────────────────────
    def _log(self, widget, msg):
        if widget:
            self._ui(widget.append, msg)

    # ── 状态栏任务计数 ────────────────────────────────────────────────────────
    def _update_task_count(self):
        n = sum([
            self.forwarding_active,
            self.monitoring_active,
            self.username_checking_active,
            self.bulkpm_active,
            bool(self.scheduled_jobs),
        ])
        text  = f"运行中任务: {n}" if n else "无运行任务"
        color = WARN if n else MUTED
        if hasattr(self, "task_label"):
            self._ui(self.task_label.configure, text=text, text_color=color)

    # ════════════════════════════════════════════════════════════════════════
    # 主界面构建
    # ════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── 顶部标题栏
        header = ctk.CTkFrame(self.root, fg_color=SIDEBAR, height=52, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="✈  TG 多功能工具",
            text_color=ACCENT, font=("微软雅黑", 14, "bold"),
            fg_color="transparent",
        ).pack(side="left", padx=20, pady=10)

        # 右侧状态区
        sr = ctk.CTkFrame(header, fg_color="transparent")
        sr.pack(side="right", padx=14)

        self.task_label = ctk.CTkLabel(
            sr, text="无运行任务", text_color=MUTED,
            font=("微软雅黑", 8), fg_color="transparent",
        )
        self.task_label.pack(side="right", padx=(10, 0))

        self.status_dot = ctk.CTkLabel(
            sr, text="● 未登录", text_color=ERROR,
            font=("微软雅黑", 9), fg_color="transparent",
        )
        self.status_dot.pack(side="right", padx=(10, 0))

        # 账号快速切换
        self.account_var = ctk.StringVar(value="切换账号")
        self.account_menu = ctk.CTkOptionMenu(
            sr,
            variable=self.account_var,
            values=self._get_account_names() or ["暂无账号"],
            command=self._switch_account,
            fg_color=BTN_BG, button_color=ACCENT2,
            text_color=TEXT, font=("微软雅黑", 8),
            width=120, height=26, corner_radius=4,
        )
        self.account_menu.pack(side="right")

        # ── 主体
        body = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        # ── 左侧导航栏
        self.sidebar = ctk.CTkFrame(body, fg_color=SIDEBAR, width=150, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._tab_btns = {}
        nav_items = [
            ("login",     "🔑  登  录"),
            ("forward",   "📨  消息转发"),
            ("group",     "👥  群组管理"),
            ("schedule",  "⏰  定时发送"),
            ("monitor",   "👁  账号监控"),
            ("username",  "🔍  用户名监听"),
            ("templates", "📝  消息模板"),
            ("bulkpm",    "📤  批量私信"),
        ]

        ctk.CTkFrame(self.sidebar, fg_color="transparent", height=12).pack()
        for key, label in nav_items:
            btn = ctk.CTkLabel(
                self.sidebar, text=label,
                fg_color="transparent", text_color=MUTED,
                font=("微软雅黑", 9), anchor="w",
                cursor="hand2", padx=16, pady=10,
            )
            btn.pack(fill="x")
            btn.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
            btn.bind("<Enter>",    lambda e, b=btn:       b.configure(text_color=TEXT)
                                   if b.cget("text_color") == MUTED else None)
            btn.bind("<Leave>",    lambda e, b=btn, k2=key:
                                   b.configure(text_color=MUTED)
                                   if self._current_tab != k2 else None)
            self._tab_btns[key] = btn

        # ── 内容区
        self.content = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)

        self._pages = {}
        for key, _ in nav_items:
            self._pages[key] = ctk.CTkFrame(self.content, fg_color=PANEL, corner_radius=0)

        self._tab_login(self._pages["login"])
        self._tab_forward(self._pages["forward"])
        self._tab_group(self._pages["group"])
        self._tab_schedule(self._pages["schedule"])
        self._tab_monitor(self._pages["monitor"])
        self._tab_username(self._pages["username"])
        self._tab_templates(self._pages["templates"])
        self._tab_bulkpm(self._pages["bulkpm"])

        self._current_tab = None

        # ── 底部版权栏
        footer = ctk.CTkFrame(self.root, fg_color=SIDEBAR, height=28, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkLabel(
            footer,
            text="© 2025  岁岁  |  Telegram: @qqfaka  |  All rights reserved.",
            text_color=MUTED, font=("微软雅黑", 8), fg_color="transparent",
        ).pack(side="left", padx=16, pady=4)
        ctk.CTkLabel(
            footer, text="v2.0",
            text_color=MUTED, font=("微软雅黑", 8), fg_color="transparent",
        ).pack(side="right", padx=16)

    def _switch_tab(self, key):
        if self._current_tab:
            self._pages[self._current_tab].pack_forget()
            self._tab_btns[self._current_tab].configure(
                fg_color="transparent", text_color=MUTED)
        self._current_tab = key
        self._pages[key].pack(fill="both", expand=True, padx=18, pady=14)
        self._tab_btns[key].configure(fg_color=ACCENT2, text_color=TEXT)

    def _restore_config(self):
        self.v_api_id.set(self.config.get("api_id", ""))
        self.v_api_hash.set(self.config.get("api_hash", ""))
        self.v_phone.set(self.config.get("phone", ""))
        self._refresh_account_list()
        self._refresh_templates_list()

    # ── 通用组件工厂 ──────────────────────────────────────────────────────────
    def _section_title(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            text_color=ACCENT, font=("微软雅黑", 11, "bold"),
            fg_color="transparent", anchor="w",
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkFrame(parent, fg_color=BORDER, height=1, corner_radius=0).pack(
            fill="x", pady=(0, 10))

    def _form_row(self, parent, label, var=None, show=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(
            row, text=label, text_color=MUTED,
            font=("微软雅黑", 8), fg_color="transparent",
            width=170, anchor="w",
        ).pack(side="left")
        v = var or tk.StringVar()
        ctk.CTkEntry(
            row, textvariable=v, show=show,
            fg_color=INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=("微软雅黑", 9), height=30, corner_radius=4,
        ).pack(side="left", fill="x", expand=True)
        return v

    def _form_row_grid(self, parent, label, row, var=None, show=""):
        ctk.CTkLabel(
            parent, text=label, text_color=MUTED,
            font=("微软雅黑", 8), fg_color="transparent",
            width=100, anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=3)
        v = var or tk.StringVar()
        ctk.CTkEntry(
            parent, textvariable=v, show=show,
            fg_color=BG, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=("微软雅黑", 9), height=28, corner_radius=4,
        ).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
        return v

    def _btn(self, parent, text, command, color=BTN_BG, hover=ACCENT, width=120):
        return ctk.CTkButton(
            parent, text=text, command=command,
            fg_color=color, hover_color=hover,
            text_color=TEXT, font=("微软雅黑", 9),
            width=width, height=30, corner_radius=4,
        )

    def _listbox(self, parent, height=6):
        frame = ctk.CTkFrame(parent, fg_color=INPUT, corner_radius=4)
        frame.pack(fill="x", pady=4)
        lb = tk.Listbox(
            frame, bg=INPUT, fg=TEXT,
            selectbackground=BTN_BG, selectforeground=TEXT,
            relief="flat", font=("Consolas", 9),
            highlightthickness=0, activestyle="none",
            height=height,
        )
        sb = tk.Scrollbar(frame, bg=SIDEBAR, troughcolor=INPUT, command=lb.yview)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        sb.pack(side="right", fill="y")
        return lb

    def _check_login(self):
        if not self.client:
            messagebox.showwarning("未登录", "请先在「登录」页完成登录")
            return False
        return True

    def _get_account_names(self):
        return [a["name"] for a in self.accounts] or ["暂无账号"]

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 ── 登录 + 多账号管理
    # ════════════════════════════════════════════════════════════════════════
    def _tab_login(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        # ── 账号档案
        self._section_title(scroll, "🔑  账号登录")

        card = ctk.CTkFrame(scroll, fg_color=INPUT, corner_radius=6)
        card.pack(fill="x", pady=(0, 8))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        inner.columnconfigure(1, weight=1)

        ctk.CTkLabel(inner, text="账号名称", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent",
                     width=100, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self.v_acc_name = tk.StringVar()
        ctk.CTkEntry(inner, textvariable=self.v_acc_name,
                     fg_color=BG, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), height=28,
                     corner_radius=4).grid(row=0, column=1, sticky="ew",
                                           padx=(8, 0), pady=3)

        self.v_api_id   = self._form_row_grid(inner, "API ID",          1)
        self.v_api_hash = self._form_row_grid(inner, "API Hash",         2)
        self.v_phone    = self._form_row_grid(inner, "手机号（含 +区号）", 3)

        ctk.CTkLabel(inner,
                     text="获取 API：my.telegram.org → App configuration",
                     text_color=MUTED, font=("微软雅黑", 7),
                     fg_color="transparent").grid(row=4, column=0,
                                                  columnspan=2, sticky="w",
                                                  pady=(4, 0))

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", pady=8)
        self.btn_login = self._btn(btn_row, "  登录 / 连接  ", self._do_login,
                                   color=ACCENT, hover=ACCENT2, width=130)
        self.btn_login.pack(side="left", padx=(0, 8))
        self._btn(btn_row, "  保存账号  ", self._save_account,
                  width=100).pack(side="left", padx=(0, 8))
        self._btn(btn_row, "  删除账号  ", self._delete_account,
                  color="#6b2222", hover=ERROR, width=100).pack(side="left")

        # ── 已保存账号列表
        self._section_title(scroll, "💾  已保存账号")
        self.acc_listbox = self._listbox(scroll, height=4)
        self.acc_listbox.bind("<Double-1>", lambda e: self._load_account_profile())
        ctk.CTkLabel(scroll, text="双击账号可加载到表单",
                     text_color=MUTED, font=("微软雅黑", 7),
                     fg_color="transparent").pack(anchor="w", pady=(0, 8))

        # ── 运行日志
        self._section_title(scroll, "📋  运行日志")
        self.login_log = DarkLog(scroll, height=200)
        self.login_log.pack(fill="both", expand=True)

    # ── 账号管理方法 ──────────────────────────────────────────────────────────
    def _save_account(self):
        name     = self.v_acc_name.get().strip()
        api_id   = self.v_api_id.get().strip()
        api_hash = self.v_api_hash.get().strip()
        phone    = self.v_phone.get().strip()
        if not all([name, api_id, api_hash, phone]):
            messagebox.showwarning("提示", "请填写账号名称、API ID、API Hash 和手机号")
            return
        session = f"session_{name.replace(' ', '_')}"
        for acc in self.accounts:
            if acc["name"] == name:
                acc.update({"api_id": api_id, "api_hash": api_hash,
                             "phone": phone, "session": session})
                self._save_config()
                self._refresh_account_list()
                self._toast(f"✅ 账号 [{name}] 已更新")
                return
        self.accounts.append({"name": name, "api_id": api_id,
                               "api_hash": api_hash, "phone": phone,
                               "session": session})
        self._save_config()
        self._refresh_account_list()
        self._toast(f"✅ 账号 [{name}] 已保存")

    def _delete_account(self):
        name = self.v_acc_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请先填写或选择要删除的账号名称")
            return
        self.accounts = [a for a in self.accounts if a["name"] != name]
        self._save_config()
        self._refresh_account_list()
        self._toast(f"已删除账号 [{name}]", color=WARN)

    def _load_account_profile(self):
        sel = self.acc_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.accounts):
            return
        acc = self.accounts[idx]
        self.v_acc_name.set(acc["name"])
        self.v_api_id.set(acc["api_id"])
        self.v_api_hash.set(acc["api_hash"])
        self.v_phone.set(acc["phone"])
        self.current_account_idx = idx

    def _refresh_account_list(self):
        if hasattr(self, "acc_listbox"):
            self.acc_listbox.delete(0, "end")
            for acc in self.accounts:
                self.acc_listbox.insert("end",
                    f"  {acc['name']:<18} {acc['phone']}")
        names = self._get_account_names()
        if hasattr(self, "account_menu"):
            self.account_menu.configure(values=names)

    def _switch_account(self, name):
        for acc in self.accounts:
            if acc["name"] == name:
                self.v_acc_name.set(acc["name"])
                self.v_api_id.set(acc["api_id"])
                self.v_api_hash.set(acc["api_hash"])
                self.v_phone.set(acc["phone"])
                self._switch_tab("login")
                self._log(self.login_log,
                           f"已加载账号 [{name}]，点击「登录 / 连接」以切换")
                return

    # ── 登录逻辑 ──────────────────────────────────────────────────────────────
    def _do_login(self):
        api_id   = self.v_api_id.get().strip()
        api_hash = self.v_api_hash.get().strip()
        phone    = self.v_phone.get().strip()
        if not (api_id and api_hash and phone):
            messagebox.showwarning("提示", "请填写 API ID、API Hash 和手机号")
            return
        name         = self.v_acc_name.get().strip() or "default"
        session_file = f"session_{name.replace(' ', '_')}"
        self.config.update({"api_id": api_id, "api_hash": api_hash, "phone": phone})
        self._save_config()
        self.btn_login.configure(state="disabled")
        self._log(self.login_log, "正在连接 Telegram...")
        self._async(self._connect(int(api_id), api_hash, phone, session_file))

    async def _connect(self, api_id, api_hash, phone,
                       session_file="tg_tool_session"):
        try:
            if self.client:
                await self.client.disconnect()
            self.client = TelegramClient(session_file, api_id, api_hash,
                                         loop=self.loop)
            await self.client.connect()
            if not await self.client.is_user_authorized():
                await self.client.send_code_request(phone)
                self._log(self.login_log, "验证码已发送，请查收")
                self._ui(self._ask_code, phone)
            else:
                me = await self.client.get_me()
                self._log(self.login_log,
                          f"✅ 已登录：{me.first_name}  @{me.username or me.id}")
                self._ui(self.status_dot.configure,
                         text=f"● {me.first_name}", text_color=SUCCESS)
                self._ui(self.btn_login.configure, state="normal")
                self._toast(f"✅ 登录成功：{me.first_name}")
        except Exception as e:
            self._log(self.login_log, f"❌ 连接失败：{e}")
            self._ui(self.btn_login.configure, state="normal")

    def _ask_code(self, phone):
        code = simpledialog.askstring(
            "验证码", "输入 Telegram 发送的验证码：", parent=self.root)
        if code:
            self._async(self._sign_in(phone, code.strip()))

    async def _sign_in(self, phone, code):
        try:
            await self.client.sign_in(phone, code)
            me = await self.client.get_me()
            self._log(self.login_log, f"✅ 登录成功：{me.first_name}")
            self._ui(self.status_dot.configure,
                     text=f"● {me.first_name}", text_color=SUCCESS)
            self._toast(f"✅ 登录成功：{me.first_name}")
        except SessionPasswordNeededError:
            self._ui(self._ask_2fa)
        except Exception as e:
            self._log(self.login_log, f"❌ 登录失败：{e}")
        finally:
            self._ui(self.btn_login.configure, state="normal")

    def _ask_2fa(self):
        pwd = simpledialog.askstring(
            "两步验证", "输入两步验证密码：", show="*", parent=self.root)
        if pwd:
            self._async(self._sign_in_2fa(pwd))

    async def _sign_in_2fa(self, pwd):
        try:
            await self.client.sign_in(password=pwd)
            me = await self.client.get_me()
            self._log(self.login_log, f"✅ 登录成功：{me.first_name}")
            self._ui(self.status_dot.configure,
                     text=f"● {me.first_name}", text_color=SUCCESS)
            self._toast(f"✅ 两步验证成功：{me.first_name}")
        except Exception as e:
            self._log(self.login_log, f"❌ 两步验证失败：{e}")
        finally:
            self._ui(self.btn_login.configure, state="normal")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 ── 消息转发
    # ════════════════════════════════════════════════════════════════════════
    def _tab_forward(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "📨  消息转发")

        self.v_fw_src = self._form_row(scroll, "来源  (用户名 / ID)")
        self.v_fw_dst = self._form_row(scroll, "目标  (用户名 / ID)")
        self.v_fw_kw  = self._form_row(scroll, "关键词过滤（空 = 转发全部）")

        bf = ctk.CTkFrame(scroll, fg_color="transparent")
        bf.pack(fill="x", pady=8)
        self.btn_fw_start = self._btn(bf, "  ▶  开始转发  ", self._start_forward,
                                      color=ACCENT, hover=ACCENT2)
        self.btn_fw_stop  = self._btn(bf, "  ■  停止转发  ", self._stop_forward,
                                      color=BTN_BG, hover=ERROR)
        self.btn_fw_start.pack(side="left", padx=(0, 8))
        self.btn_fw_stop.pack(side="left")
        self.btn_fw_stop.configure(state="disabled")

        ctk.CTkFrame(scroll, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", pady=8)
        ctk.CTkLabel(scroll, text="转发日志", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(anchor="w")
        self.fw_log = DarkLog(scroll, height=300)
        self.fw_log.pack(fill="both", expand=True, pady=4)

    def _start_forward(self):
        if not self._check_login(): return
        src = self.v_fw_src.get().strip()
        dst = self.v_fw_dst.get().strip()
        if not (src and dst):
            messagebox.showwarning("提示", "请填写来源和目标"); return
        self.forwarding_active = True
        self.btn_fw_start.configure(state="disabled")
        self.btn_fw_stop.configure(state="normal")
        kw = self.v_fw_kw.get().strip()
        self._log(self.fw_log,
                  f"开始转发  {src} → {dst}  关键词: {kw or '无限制'}")
        self._async(self._forward_loop(src, dst, kw))
        self._update_task_count()

    def _stop_forward(self):
        self.forwarding_active = False
        self.btn_fw_start.configure(state="normal")
        self.btn_fw_stop.configure(state="disabled")
        self._log(self.fw_log, "⚠ 已停止转发")
        self._update_task_count()

    async def _forward_loop(self, src, dst, keyword):
        try:
            src_e = await self.client.get_entity(src)
            dst_e = await self.client.get_entity(dst)
            self._log(self.fw_log, f"✅ 来源：{getattr(src_e, 'title', None) or src}")
            self._log(self.fw_log, f"✅ 目标：{getattr(dst_e, 'title', None) or dst}")
            self._log(self.fw_log, "👂 正在监听新消息，等待转发...")

            @self.client.on(events.NewMessage(chats=src_e))
            async def handler(event):
                if not self.forwarding_active:
                    self.client.remove_event_handler(handler)
                    return
                text = event.message.text or ""
                if keyword and keyword.lower() not in text.lower():
                    return
                await self.client.forward_messages(dst_e, event.message)
                self._log(self.fw_log, f"✅ 已转发: {text[:60]}")

            while self.forwarding_active:
                await asyncio.sleep(1)
            self.client.remove_event_handler(handler)
        except Exception as e:
            self._log(self.fw_log, f"❌ 错误: {e}")
            self._ui(self._stop_forward)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 3 ── 群组管理
    # ════════════════════════════════════════════════════════════════════════
    def _tab_group(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "👥  群组管理")
        self.v_grp = self._form_row(scroll, "群组  (用户名 / ID)")

        bf = ctk.CTkFrame(scroll, fg_color="transparent")
        bf.pack(fill="x", pady=8)
        for label, cmd, color, hover in [
            ("  加载成员  ", self._load_members,      BTN_BG,   ACCENT),
            ("  导出 CSV  ", self._export_members_csv, BTN_BG,   SUCCESS),
            ("  发公告    ", self._send_announce,      BTN_BG,   ACCENT),
            ("  踢出成员  ", self._kick_member,        "#6b2222", ERROR),
            ("  设欢迎语  ", self._set_welcome,        BTN_BG,   ACCENT),
        ]:
            self._btn(bf, label, cmd, color=color, hover=hover,
                      width=100).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(scroll, text="成员列表", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(6, 2))
        self.grp_list = self._listbox(scroll, height=7)

        ctk.CTkLabel(scroll, text="操作日志", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(6, 2))
        self.grp_log = DarkLog(scroll, height=160)
        self.grp_log.pack(fill="both", pady=4)

    def _load_members(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        if not group: messagebox.showwarning("提示", "请填写群组"); return
        self._async(self._fetch_members(group))

    async def _fetch_members(self, group):
        try:
            entity = await self.client.get_entity(group)
            self._log(self.grp_log, "正在获取成员，大群可能需要一两分钟...")
            self._ui(self.grp_list.delete, 0, "end")
            self._members_cache = []
            parts = await self.client.get_participants(entity, aggressive=True)
            self._members_cache = parts
            for p in parts:
                name  = f"{p.first_name or ''} {p.last_name or ''}".strip()
                uname = f"@{p.username}" if p.username else f"ID:{p.id}"
                self._ui(self.grp_list.insert, "end", f"  {name:<22} {uname}")
            self._log(self.grp_log, f"✅ 已加载 {len(parts)} 名成员")
            self._toast(f"✅ 已加载 {len(parts)} 名成员")
        except Exception as e:
            self._log(self.grp_log, f"❌ {e}")

    def _export_members_csv(self):
        if not self._members_cache:
            messagebox.showwarning("提示", "请先加载成员列表"); return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            title="导出成员列表",
            initialfile="members.csv",
        )
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "用户名", "姓名", "是否Bot"])
                for p in self._members_cache:
                    name = f"{p.first_name or ''} {p.last_name or ''}".strip()
                    writer.writerow([p.id, p.username or "",
                                     name, getattr(p, "bot", False)])
            self._log(self.grp_log,
                      f"✅ 已导出 {len(self._members_cache)} 名成员 → "
                      f"{os.path.basename(path)}")
            self._toast("✅ CSV 导出成功")
        except Exception as e:
            self._log(self.grp_log, f"❌ 导出失败：{e}")

    def _send_announce(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        msg   = simpledialog.askstring("发公告", "输入公告内容：", parent=self.root)
        if msg and group:
            self._async(self._send_to(group, msg, self.grp_log))

    async def _send_to(self, target, msg, log_widget):
        try:
            entity = await self.client.get_entity(target)
            await self.client.send_message(entity, msg)
            self._log(log_widget, f"✅ 消息已发送：{msg[:40]}")
        except Exception as e:
            self._log(log_widget, f"❌ {e}")

    def _kick_member(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        user  = simpledialog.askstring(
            "踢出成员", "输入用户名 (@xxx) 或 ID：", parent=self.root)
        if user and group:
            self._async(self._kick(group, user.strip()))

    async def _kick(self, group, user):
        try:
            g = await self.client.get_entity(group)
            u = await self.client.get_entity(user)
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await self.client(EditBannedRequest(g, u, rights))
            self._log(self.grp_log, f"✅ 已踢出：{user}")
        except Exception as e:
            self._log(self.grp_log, f"❌ 踢出失败：{e}")

    def _set_welcome(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        msg   = simpledialog.askstring(
            "欢迎语", "输入欢迎新成员的消息（支持 {name}）：", parent=self.root)
        if msg and group:
            self.config[f"welcome_{group}"] = msg
            self._save_config()
            self._async(self._register_welcome(group, msg))
            self._log(self.grp_log, f"✅ 欢迎语已设置：{msg}")

    async def _register_welcome(self, group, template):
        try:
            entity = await self.client.get_entity(group)

            @self.client.on(events.ChatAction(chats=entity))
            async def handler(event):
                if event.user_joined or event.user_added:
                    user = await event.get_user()
                    name = getattr(user, "first_name", None) or "新成员"
                    await self.client.send_message(
                        entity, template.replace("{name}", name))
        except Exception as e:
            self._log(self.grp_log, f"❌ {e}")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 4 ── 定时发送
    # ════════════════════════════════════════════════════════════════════════
    def _tab_schedule(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "⏰  定时发送")

        self.v_sch_target = self._form_row(scroll, "目标  (用户名 / ID)")
        self.v_sch_msg    = self._form_row(scroll, "消息内容")

        tf = ctk.CTkFrame(scroll, fg_color="transparent")
        tf.pack(fill="x", pady=6)
        ctk.CTkLabel(tf, text="发送时间 HH:MM", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(side="left")
        self.v_sch_time = tk.StringVar()
        ctk.CTkEntry(tf, textvariable=self.v_sch_time,
                     fg_color=INPUT, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), width=80, height=28,
                     corner_radius=4).pack(side="left", padx=8)
        self.v_sch_repeat = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            tf, text="每天重复", variable=self.v_sch_repeat,
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color=TEXT, font=("微软雅黑", 9),
        ).pack(side="left", padx=8)

        self._btn(scroll, "  +  添加任务  ", self._add_job,
                  color=ACCENT, hover=ACCENT2).pack(anchor="w", pady=6)

        ctk.CTkLabel(scroll, text="任务列表", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(6, 2))
        self.job_list = self._listbox(scroll, height=4)

        self._btn(scroll, "  删除选中任务  ", self._remove_job,
                  color=BTN_BG, hover=ERROR, width=130).pack(anchor="w", pady=4)

        ctk.CTkLabel(scroll, text="操作日志", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(6, 2))
        self.sch_log = DarkLog(scroll, height=200)
        self.sch_log.pack(fill="both", expand=True, pady=4)

    def _add_job(self):
        if not self._check_login(): return
        target = self.v_sch_target.get().strip()
        msg    = self.v_sch_msg.get().strip()
        t_str  = self.v_sch_time.get().strip()
        repeat = self.v_sch_repeat.get()
        if not (target and msg and t_str):
            messagebox.showwarning("提示", "请填写所有字段"); return
        try:
            h, m = map(int, t_str.split(":"))
        except ValueError:
            messagebox.showwarning("格式错误", "时间格式应为 HH:MM"); return
        job = {"target": target, "msg": msg, "hour": h, "minute": m,
               "repeat": repeat, "fired": False}
        self.scheduled_jobs.append(job)
        label = f"  {'每天' if repeat else '一次'}  {t_str}  →  {target}: {msg[:25]}"
        self.job_list.insert("end", label)
        self._log(self.sch_log, f"✅ 已添加任务: {label.strip()}")
        self._update_task_count()

    def _remove_job(self):
        sel = self.job_list.curselection()
        if sel:
            idx = sel[0]
            self.scheduled_jobs.pop(idx)
            self.job_list.delete(idx)
            self._update_task_count()

    def _scheduler_thread(self):
        while True:
            now = datetime.now()
            for job in self.scheduled_jobs:
                if job["fired"]: continue
                if now.hour == job["hour"] and now.minute == job["minute"]:
                    log = self.sch_log if hasattr(self, "sch_log") else None
                    self._async(self._send_to(job["target"], job["msg"], log))
                    job["fired"] = True
                    if job["repeat"]:
                        threading.Timer(
                            61, lambda j=job: j.update({"fired": False})
                        ).start()
            time_module.sleep(20)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 5 ── 账号监控
    # ════════════════════════════════════════════════════════════════════════
    def _tab_monitor(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "👁  账号监控")

        self.v_mon_chat = self._form_row(scroll, "监控聊天 / 群 / 频道")
        self.v_mon_kw   = self._form_row(scroll, "关键词（逗号分隔，空 = 全部）")
        self.v_mon_user = self._form_row(scroll, "仅监控指定用户（可选 @xxx）")

        bf = ctk.CTkFrame(scroll, fg_color="transparent")
        bf.pack(fill="x", pady=8)
        self.btn_mon_start = self._btn(bf, "  ▶  开始监控  ",
                                       self._start_monitor,
                                       color=ACCENT, hover=ACCENT2)
        self.btn_mon_stop  = self._btn(bf, "  ■  停止监控  ",
                                       self._stop_monitor,
                                       color=BTN_BG, hover=ERROR)
        self.btn_mon_start.pack(side="left", padx=(0, 8))
        self.btn_mon_stop.pack(side="left")
        self.btn_mon_stop.configure(state="disabled")

        ctk.CTkFrame(scroll, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", pady=8)
        ctk.CTkLabel(scroll, text="监控日志（触发时桌面弹窗提醒）",
                     text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent").pack(anchor="w")
        self.mon_log = DarkLog(scroll, height=340)
        self.mon_log.pack(fill="both", expand=True, pady=4)

    def _start_monitor(self):
        if not self._check_login(): return
        chat = self.v_mon_chat.get().strip()
        if not chat: messagebox.showwarning("提示", "请填写监控对象"); return
        kws  = [k.strip() for k in self.v_mon_kw.get().split(",") if k.strip()]
        user = self.v_mon_user.get().strip().lstrip("@")
        self.monitoring_active = True
        self.btn_mon_start.configure(state="disabled")
        self.btn_mon_stop.configure(state="normal")
        self._log(self.mon_log,
                  f"开始监控 {chat}  关键词:{kws or '全部'}  用户:{user or '全部'}")
        self._async(self._monitor_loop(chat, kws, user))
        self._update_task_count()

    def _stop_monitor(self):
        self.monitoring_active = False
        self.btn_mon_start.configure(state="normal")
        self.btn_mon_stop.configure(state="disabled")
        self._log(self.mon_log, "⚠ 已停止监控")
        self._update_task_count()

    async def _monitor_loop(self, chat, keywords, target_user):
        try:
            entity = await self.client.get_entity(chat)

            @self.client.on(events.NewMessage(chats=entity))
            async def handler(event):
                if not self.monitoring_active:
                    self.client.remove_event_handler(handler)
                    return
                sender = await event.get_sender()
                uname  = getattr(sender, "username", "") or ""
                if target_user and target_user != uname:
                    return
                text = event.message.text or ""
                if keywords and not any(k.lower() in text.lower()
                                        for k in keywords):
                    return
                preview = f"@{uname}: {text[:60]}"
                self._log(self.mon_log, f"🔔 {preview}")
                self._notify("Telegram 监控提醒", preview)
        except Exception as e:
            self._log(self.mon_log, f"❌ {e}")
            self._ui(self._stop_monitor)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 6 ── 用户名监听
    # ════════════════════════════════════════════════════════════════════════
    def _tab_username(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "🔍  用户名监听")

        af = ctk.CTkFrame(scroll, fg_color="transparent")
        af.pack(fill="x", pady=6)
        ctk.CTkLabel(af, text="用户名", text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent", width=70).pack(side="left")
        self.v_uname = tk.StringVar()
        ctk.CTkEntry(af, textvariable=self.v_uname,
                     fg_color=INPUT, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), width=160, height=28,
                     corner_radius=4).pack(side="left", padx=8)
        self._btn(af, "  +  添加  ", self._add_uname,
                  color=ACCENT, hover=ACCENT2, width=80).pack(side="left")
        ctk.CTkLabel(af, text="   间隔(秒)", text_color=MUTED,
                     font=("微软雅黑", 8),
                     fg_color="transparent").pack(side="left", padx=(16, 4))
        self.v_uname_interval = tk.StringVar(value="60")
        ctk.CTkEntry(af, textvariable=self.v_uname_interval,
                     fg_color=INPUT, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), width=70, height=28,
                     corner_radius=4).pack(side="left")

        bf = ctk.CTkFrame(scroll, fg_color="transparent")
        bf.pack(fill="x", pady=6)
        self._btn(bf, "  删除选中  ", self._del_uname,
                  color=BTN_BG, hover=ERROR, width=90).pack(side="left",
                                                             padx=(0, 6))
        self.btn_un_start = self._btn(bf, "  ▶  开始监听  ",
                                      self._start_uname_check,
                                      color=ACCENT, hover=ACCENT2)
        self.btn_un_stop  = self._btn(bf, "  ■  停止监听  ",
                                      self._stop_uname_check,
                                      color=BTN_BG, hover=ERROR)
        self.btn_un_start.pack(side="left", padx=(0, 6))
        self.btn_un_stop.pack(side="left")
        self.btn_un_stop.configure(state="disabled")

        ctk.CTkLabel(scroll, text="监听列表", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(6, 2))
        self.uname_list = self._listbox(scroll, height=4)

        ctk.CTkLabel(scroll, text="检测日志（可用时桌面弹窗提醒）",
                     text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent").pack(anchor="w", pady=(6, 2))
        self.uname_log = DarkLog(scroll, height=260)
        self.uname_log.pack(fill="both", expand=True, pady=4)

    def _add_uname(self):
        uname = self.v_uname.get().strip().lstrip("@")
        if not uname: return
        if uname not in self._usernames_to_check:
            self._usernames_to_check.append(uname)
            self.uname_list.insert("end", f"  @{uname:<20} ⏳ 等待检查")
            self._log(self.uname_log, f"已添加：@{uname}")
        self.v_uname.set("")

    def _del_uname(self):
        sel = self.uname_list.curselection()
        if sel:
            idx = sel[0]
            self._usernames_to_check.pop(idx)
            self.uname_list.delete(idx)

    def _start_uname_check(self):
        if not self._check_login(): return
        if not self._usernames_to_check:
            messagebox.showwarning("提示", "请先添加要监听的用户名"); return
        try:
            interval = max(30, int(self.v_uname_interval.get()))
        except ValueError:
            interval = 60
        self.username_checking_active = True
        self.btn_un_start.configure(state="disabled")
        self.btn_un_stop.configure(state="normal")
        self._log(self.uname_log, f"开始监听，每 {interval} 秒检查一次")
        self._async(self._uname_check_loop(interval))
        self._update_task_count()

    def _stop_uname_check(self):
        self.username_checking_active = False
        self.btn_un_start.configure(state="normal")
        self.btn_un_stop.configure(state="disabled")
        self._log(self.uname_log, "⚠ 已停止监听")
        self._update_task_count()

    async def _uname_check_loop(self, interval):
        while self.username_checking_active:
            for i, uname in enumerate(list(self._usernames_to_check)):
                if not self.username_checking_active: break
                try:
                    available = await self.client(CheckUsernameRequest(uname))
                    status = "✅ 可注册！" if available else "❌ 已占用"
                    self._log(self.uname_log, f"@{uname}  {status}")
                    if available:
                        self._notify("🎉 用户名可注册！",
                                     f"@{uname} 现在可以注册了！请立即前往 Telegram 抢注。")
                        self._toast(f"🎉 @{uname} 可以注册了！")

                    def _upd(idx=i, s=status, u=uname):
                        try:
                            self.uname_list.delete(idx)
                            self.uname_list.insert(idx, f"  @{u:<20} {s}")
                        except Exception:
                            pass
                    self._ui(_upd)
                except FloodWaitError as e:
                    self._log(self.uname_log, f"⚠ 频率限制，等待 {e.seconds} 秒")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    self._log(self.uname_log, f"❌ @{uname} 检查失败：{e}")
                await asyncio.sleep(3)
            await asyncio.sleep(interval)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 7 ── 消息模板库  (新功能)
    # ════════════════════════════════════════════════════════════════════════
    def _tab_templates(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "📝  消息模板库")

        # ── 编辑区
        edit_card = ctk.CTkFrame(scroll, fg_color=INPUT, corner_radius=6)
        edit_card.pack(fill="x", pady=(0, 8))
        ei = ctk.CTkFrame(edit_card, fg_color="transparent")
        ei.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(ei, text="模板名称", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(anchor="w")
        self.v_tpl_name = tk.StringVar()
        ctk.CTkEntry(ei, textvariable=self.v_tpl_name,
                     fg_color=BG, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), height=28,
                     corner_radius=4).pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(ei, text="模板内容", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(anchor="w")
        self.tpl_content = ctk.CTkTextbox(
            ei, fg_color=BG, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=("微软雅黑", 9), height=90, corner_radius=4,
        )
        self.tpl_content.pack(fill="x", pady=(2, 8))

        btn_row = ctk.CTkFrame(ei, fg_color="transparent")
        btn_row.pack(fill="x")
        self._btn(btn_row, "  保存模板  ", self._save_template,
                  color=ACCENT, hover=ACCENT2, width=100).pack(side="left",
                                                               padx=(0, 6))
        self._btn(btn_row, "  删除选中  ", self._delete_template,
                  color="#6b2222", hover=ERROR, width=100).pack(side="left")

        # ── 模板列表
        ctk.CTkLabel(scroll, text="已保存模板  （单击预览，双击编辑）",
                     text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent").pack(anchor="w", pady=(8, 2))
        self.tpl_listbox = self._listbox(scroll, height=7)
        self.tpl_listbox.bind("<<ListboxSelect>>", self._on_template_select)

        # ── 快速发送
        ctk.CTkFrame(scroll, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", pady=10)
        self._section_title(scroll, "🚀  快速发送")

        qcard = ctk.CTkFrame(scroll, fg_color=INPUT, corner_radius=6)
        qcard.pack(fill="x", pady=(0, 8))
        qi = ctk.CTkFrame(qcard, fg_color="transparent")
        qi.pack(fill="x", padx=14, pady=10)

        self.v_tpl_send_target = self._form_row(qi, "发送目标  (用户名 / ID)")
        self._btn(qi, "  使用选中模板发送  ", self._send_template,
                  color=ACCENT, hover=ACCENT2, width=160).pack(anchor="w",
                                                               pady=(6, 0))

    def _save_template(self):
        name    = self.v_tpl_name.get().strip()
        content = self.tpl_content.get("1.0", "end").strip()
        if not (name and content):
            messagebox.showwarning("提示", "请填写模板名称和内容"); return
        for tpl in self.templates:
            if tpl["name"] == name:
                tpl["content"] = content
                self._save_config()
                self._refresh_templates_list()
                self._toast(f"✅ 模板 [{name}] 已更新")
                return
        self.templates.append({"name": name, "content": content})
        self._save_config()
        self._refresh_templates_list()
        self._toast(f"✅ 模板 [{name}] 已保存")
        self.v_tpl_name.set("")
        self.tpl_content.delete("1.0", "end")

    def _delete_template(self):
        sel = self.tpl_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self.templates):
            name = self.templates[idx]["name"]
            self.templates.pop(idx)
            self._save_config()
            self._refresh_templates_list()
            self._toast(f"已删除模板 [{name}]", color=WARN)

    def _on_template_select(self, _event):
        sel = self.tpl_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self.templates):
            tpl = self.templates[idx]
            self.v_tpl_name.set(tpl["name"])
            self.tpl_content.delete("1.0", "end")
            self.tpl_content.insert("1.0", tpl["content"])

    def _refresh_templates_list(self):
        if hasattr(self, "tpl_listbox"):
            self.tpl_listbox.delete(0, "end")
            for tpl in self.templates:
                preview = tpl["content"][:45].replace("\n", " ")
                self.tpl_listbox.insert("end",
                    f"  [{tpl['name']}]  {preview}")

    def _send_template(self):
        if not self._check_login(): return
        sel = self.tpl_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个模板"); return
        idx = sel[0]
        if idx >= len(self.templates): return
        target = self.v_tpl_send_target.get().strip()
        if not target:
            messagebox.showwarning("提示", "请填写发送目标"); return
        content = self.templates[idx]["content"]
        self._async(self._send_to(target, content,
                                   getattr(self, "sch_log", None)))
        self._toast(f"✅ 模板已发送到 {target}")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 8 ── 批量私信  (新功能)
    # ════════════════════════════════════════════════════════════════════════
    def _tab_bulkpm(self, f):
        scroll = ctk.CTkScrollableFrame(f, fg_color=PANEL,
                                        scrollbar_button_color=SIDEBAR)
        scroll.pack(fill="both", expand=True)

        self._section_title(scroll, "📤  批量私信")

        ctk.CTkLabel(
            scroll,
            text="⚠  频繁私信可能触发 Telegram 限流或封号，"
                 "建议发送间隔 ≥ 30 秒",
            text_color=WARN, font=("微软雅黑", 8),
            fg_color="transparent", wraplength=700, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # ── 来源群组
        self.v_bpm_group = self._form_row(scroll, "来源群组（获取成员）")

        bf = ctk.CTkFrame(scroll, fg_color="transparent")
        bf.pack(fill="x", pady=6)
        self._btn(bf, "  加载成员  ", self._bpm_load_members,
                  color=BTN_BG, hover=ACCENT, width=100).pack(side="left",
                                                              padx=(0, 6))
        self._btn(bf, "  清空列表  ", self._bpm_clear_targets,
                  color=BTN_BG, hover=WARN, width=100).pack(side="left")

        # ── 目标列表
        ctk.CTkLabel(scroll,
                     text="目标用户列表（每行一个 @用户名 或 ID）",
                     text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent").pack(anchor="w", pady=(8, 2))
        self.bpm_target_box = ctk.CTkTextbox(
            scroll, fg_color=INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=("Consolas", 9), height=100, corner_radius=4,
        )
        self.bpm_target_box.pack(fill="x", pady=4)

        # ── 私信内容
        ctk.CTkLabel(scroll,
                     text="私信内容（支持 {name} 替换为用户昵称）",
                     text_color=MUTED, font=("微软雅黑", 8),
                     fg_color="transparent").pack(anchor="w", pady=(8, 2))
        self.bpm_msg_box = ctk.CTkTextbox(
            scroll, fg_color=INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=("微软雅黑", 9), height=90, corner_radius=4,
        )
        self.bpm_msg_box.pack(fill="x", pady=4)

        # ── 参数行
        pf = ctk.CTkFrame(scroll, fg_color="transparent")
        pf.pack(fill="x", pady=6)
        ctk.CTkLabel(pf, text="发送间隔（秒）", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(side="left")
        self.v_bpm_interval = tk.StringVar(value="30")
        ctk.CTkEntry(pf, textvariable=self.v_bpm_interval,
                     fg_color=INPUT, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), width=70, height=28,
                     corner_radius=4).pack(side="left", padx=8)
        ctk.CTkLabel(pf, text="发送上限（0 = 无限制）", text_color=MUTED,
                     font=("微软雅黑", 8),
                     fg_color="transparent").pack(side="left", padx=(16, 4))
        self.v_bpm_limit = tk.StringVar(value="0")
        ctk.CTkEntry(pf, textvariable=self.v_bpm_limit,
                     fg_color=INPUT, text_color=TEXT,
                     border_color=BORDER, border_width=1,
                     font=("微软雅黑", 9), width=70, height=28,
                     corner_radius=4).pack(side="left")

        # ── 控制按钮
        cf = ctk.CTkFrame(scroll, fg_color="transparent")
        cf.pack(fill="x", pady=8)
        self.btn_bpm_start = self._btn(cf, "  ▶  开始发送  ",
                                       self._start_bulkpm,
                                       color=ACCENT, hover=ACCENT2)
        self.btn_bpm_stop  = self._btn(cf, "  ■  停止发送  ",
                                       self._stop_bulkpm,
                                       color=BTN_BG, hover=ERROR)
        self.btn_bpm_start.pack(side="left", padx=(0, 8))
        self.btn_bpm_stop.pack(side="left")
        self.btn_bpm_stop.configure(state="disabled")

        # ── 进度条
        self.bpm_progress_label = ctk.CTkLabel(
            scroll, text="待发送",
            text_color=MUTED, font=("微软雅黑", 8), fg_color="transparent",
        )
        self.bpm_progress_label.pack(anchor="w", pady=(4, 0))
        self.bpm_progress = ctk.CTkProgressBar(
            scroll, fg_color=INPUT, progress_color=ACCENT,
            height=8, corner_radius=4,
        )
        self.bpm_progress.set(0)
        self.bpm_progress.pack(fill="x", pady=(2, 8))

        # ── 日志
        ctk.CTkLabel(scroll, text="发送日志", text_color=MUTED,
                     font=("微软雅黑", 8), fg_color="transparent").pack(
            anchor="w", pady=(4, 2))
        self.bpm_log = DarkLog(scroll, height=220)
        self.bpm_log.pack(fill="both", expand=True, pady=4)

    def _bpm_load_members(self):
        if not self._check_login(): return
        group = self.v_bpm_group.get().strip()
        if not group: messagebox.showwarning("提示", "请填写群组"); return
        self._async(self._bpm_fetch(group))

    async def _bpm_fetch(self, group):
        try:
            entity = await self.client.get_entity(group)
            self._log(self.bpm_log, "正在获取成员...")
            parts  = await self.client.get_participants(entity, aggressive=True)
            users  = [p for p in parts
                      if not getattr(p, "bot", False) and p.username]
            lines  = "\n".join(f"@{p.username}" for p in users)
            self._ui(self.bpm_target_box.delete, "1.0", "end")
            self._ui(self.bpm_target_box.insert, "1.0", lines)
            self._log(self.bpm_log,
                      f"✅ 已加载 {len(users)} 名可私信用户（已排除机器人）")
        except Exception as e:
            self._log(self.bpm_log, f"❌ {e}")

    def _bpm_clear_targets(self):
        self.bpm_target_box.delete("1.0", "end")

    def _start_bulkpm(self):
        if not self._check_login(): return
        targets_text = self.bpm_target_box.get("1.0", "end").strip()
        msg_template = self.bpm_msg_box.get("1.0", "end").strip()
        if not targets_text:
            messagebox.showwarning("提示", "请填写目标用户列表"); return
        if not msg_template:
            messagebox.showwarning("提示", "请填写私信内容"); return
        targets = [t.strip() for t in targets_text.splitlines() if t.strip()]
        try:
            interval = max(5, int(self.v_bpm_interval.get()))
        except ValueError:
            interval = 30
        try:
            limit = int(self.v_bpm_limit.get())
        except ValueError:
            limit = 0
        if limit > 0:
            targets = targets[:limit]
        self.bulkpm_active = True
        self.btn_bpm_start.configure(state="disabled")
        self.btn_bpm_stop.configure(state="normal")
        self.bpm_progress.set(0)
        self._log(self.bpm_log,
                  f"开始批量私信  目标数: {len(targets)}  间隔: {interval}s")
        self._async(self._bulkpm_loop(targets, msg_template, interval))
        self._update_task_count()

    def _stop_bulkpm(self):
        self.bulkpm_active = False
        self.btn_bpm_start.configure(state="normal")
        self.btn_bpm_stop.configure(state="disabled")
        self._log(self.bpm_log, "⚠ 已停止批量私信")
        self._update_task_count()

    async def _bulkpm_loop(self, targets, msg_template, interval):
        total   = len(targets)
        success = 0
        failed  = 0
        for i, target in enumerate(targets):
            if not self.bulkpm_active:
                break
            try:
                entity = await self.client.get_entity(target)
                name   = (getattr(entity, "first_name", None)
                          or getattr(entity, "username", target)
                          or target)
                msg    = msg_template.replace("{name}", name)
                await self.client.send_message(entity, msg)
                success += 1
                self._log(self.bpm_log,
                          f"✅ [{i+1}/{total}] 已发送给 {target}")
            except FloodWaitError as e:
                self._log(self.bpm_log,
                          f"⚠ 频率限制，等待 {e.seconds} 秒")
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                failed += 1
                self._log(self.bpm_log,
                          f"❌ [{i+1}/{total}] {target} 失败：{e}")

            progress = (i + 1) / total
            self._ui(self.bpm_progress.set, progress)
            self._ui(self.bpm_progress_label.configure,
                     text=f"进度: {i+1}/{total}  ✅ {success}  ❌ {failed}")

            if i < total - 1 and self.bulkpm_active:
                await asyncio.sleep(interval)

        self._log(self.bpm_log,
                  f"✅ 批量私信完成  成功: {success}  失败: {failed}")
        self._toast(f"批量私信完成  成功 {success} / 失败 {failed}",
                    color=SUCCESS if failed == 0 else WARN)
        self._ui(self._stop_bulkpm)


# ── 入口 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = ctk.CTk()
    app  = TelegramTool(root)
    root.mainloop()
