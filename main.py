import asyncio
import threading
import json
import os
import time as time_module
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog

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

# ── 颜色主题（Telegram 深色风格）─────────────────────────────────────────────
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
BTN_HOV = "#2AABEE"
SEL_BG  = "#2b5278"

CONFIG_FILE  = "config.json"
SESSION_FILE = "tg_tool_session"


# ── 自定义控件 ────────────────────────────────────────────────────────────────

class FlatButton(tk.Label):
    """扁平风格按钮，支持悬停变色。"""
    def __init__(self, parent, text, command=None,
                 bg=BTN_BG, fg=TEXT, active_bg=ACCENT,
                 padx=16, pady=6, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=("微软雅黑", 9), cursor="hand2",
                         padx=padx, pady=pady, **kw)
        self._bg = bg
        self._active_bg = active_bg
        self._cmd = command
        self._enabled = True
        self.bind("<Enter>",    lambda e: self._hover(True))
        self.bind("<Leave>",    lambda e: self._hover(False))
        self.bind("<Button-1>", lambda e: self._click())

    def _hover(self, on):
        if self._enabled:
            self.config(bg=self._active_bg if on else self._bg)

    def _click(self):
        if self._enabled and self._cmd:
            self._cmd()

    def set_state(self, state):
        self._enabled = (state == "normal")
        self.config(fg=TEXT if self._enabled else MUTED,
                    bg=self._bg)

    def config_text(self, text):
        self.config(text=text)


class DarkEntry(tk.Entry):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=INPUT, fg=TEXT,
                         insertbackground=ACCENT,
                         relief="flat", font=("微软雅黑", 9),
                         highlightthickness=1,
                         highlightcolor=ACCENT,
                         highlightbackground=BORDER, **kw)


class DarkLabel(tk.Label):
    def __init__(self, parent, text, fg=TEXT, font_size=9, bold=False, **kw):
        font = ("微软雅黑", font_size, "bold" if bold else "normal")
        super().__init__(parent, text=text, bg=PANEL, fg=fg,
                         font=font, **kw)


class SectionTitle(tk.Label):
    def __init__(self, parent, text, **kw):
        super().__init__(parent, text=text, bg=PANEL, fg=ACCENT,
                         font=("微软雅黑", 10, "bold"), **kw)


class DarkListbox(tk.Listbox):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=INPUT, fg=TEXT,
                         selectbackground=SEL_BG, selectforeground=TEXT,
                         relief="flat", font=("Consolas", 9),
                         highlightthickness=1,
                         highlightcolor=ACCENT,
                         highlightbackground=BORDER,
                         activestyle="none", **kw)


class DarkLog(scrolledtext.ScrolledText):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg="#0d1520", fg=TEXT,
                         insertbackground=ACCENT,
                         relief="flat", font=("Consolas", 9),
                         state="disabled", wrap=tk.WORD,
                         highlightthickness=1,
                         highlightcolor=BORDER,
                         highlightbackground=BORDER, **kw)
        self.tag_config("ok",   foreground=SUCCESS)
        self.tag_config("err",  foreground=ERROR)
        self.tag_config("warn", foreground=WARN)
        self.tag_config("info", foreground=ACCENT)
        self.tag_config("time", foreground=MUTED)

    def append(self, msg):
        self.config(state="normal")
        ts = f"[{datetime.now().strftime('%H:%M:%S')}] "
        self.insert(tk.END, ts, "time")
        if msg.startswith("✅"):
            self.insert(tk.END, msg + "\n", "ok")
        elif msg.startswith("❌"):
            self.insert(tk.END, msg + "\n", "err")
        elif msg.startswith("🔔") or msg.startswith("⚠"):
            self.insert(tk.END, msg + "\n", "warn")
        else:
            self.insert(tk.END, msg + "\n")
        self.see(tk.END)
        self.config(state="disabled")


# ── 主应用 ────────────────────────────────────────────────────────────────────

class TelegramTool:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TG 多功能工具  |  by 岁岁 @qqfaka")
        self.root.geometry("960x660")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        self.client = None
        self.loop   = asyncio.new_event_loop()
        self.config = self._load_config()

        self.forwarding_active        = False
        self.monitoring_active        = False
        self.username_checking_active = False
        self.scheduled_jobs           = []
        self._usernames_to_check      = []

        threading.Thread(target=self._run_loop,        daemon=True).start()
        threading.Thread(target=self._scheduler_thread, daemon=True).start()

        self._build_ui()
        self._restore_config()
        self._switch_tab("login")

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

    # ── 日志 ──────────────────────────────────────────────────────────────────

    def _log(self, widget, msg):
        if widget:
            self._ui(widget.append, msg)

    # ── 主界面构建 ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── 顶部标题栏
        header = tk.Frame(self.root, bg=SIDEBAR, height=52)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(header, text="✈  TG 多功能工具",
                 bg=SIDEBAR, fg=ACCENT,
                 font=("微软雅黑", 14, "bold")).pack(side=tk.LEFT, padx=20, pady=10)

        self.status_dot = tk.Label(header, text="● 未登录",
                                   bg=SIDEBAR, fg=ERROR,
                                   font=("微软雅黑", 9))
        self.status_dot.pack(side=tk.RIGHT, padx=20)

        # ── 主体区域
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        # ── 左侧导航
        self.sidebar = tk.Frame(body, bg=SIDEBAR, width=140)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        self._tab_btns = {}
        nav_items = [
            ("login",    "🔑  登  录"),
            ("forward",  "📨  消息转发"),
            ("group",    "👥  群组管理"),
            ("schedule", "⏰  定时发送"),
            ("monitor",  "👁  账号监控"),
            ("username", "🔍  用户名监听"),
        ]
        tk.Frame(self.sidebar, bg=SIDEBAR, height=12).pack()
        for key, label in nav_items:
            btn = tk.Label(self.sidebar, text=label,
                           bg=SIDEBAR, fg=MUTED,
                           font=("微软雅黑", 9),
                           anchor="w", padx=16, pady=10,
                           cursor="hand2")
            btn.pack(fill=tk.X)
            btn.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
            btn.bind("<Enter>", lambda e, b=btn: b.config(fg=TEXT) if b.cget("fg") == MUTED else None)
            btn.bind("<Leave>", lambda e, b=btn, k2=key: b.config(fg=MUTED) if self._current_tab != k2 else None)
            self._tab_btns[key] = btn

        # ── 内容区
        self.content = tk.Frame(body, bg=PANEL)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._pages = {}
        for key, _ in nav_items:
            page = tk.Frame(self.content, bg=PANEL)
            self._pages[key] = page

        self._tab_login(self._pages["login"])
        self._tab_forward(self._pages["forward"])
        self._tab_group(self._pages["group"])
        self._tab_schedule(self._pages["schedule"])
        self._tab_monitor(self._pages["monitor"])
        self._tab_username(self._pages["username"])

        self._current_tab = None

        # ── 底部版权栏
        footer = tk.Frame(self.root, bg=SIDEBAR, height=28)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        tk.Label(footer,
                 text="© 2025  岁岁  |  Telegram: @qqfaka  |  All rights reserved.",
                 bg=SIDEBAR, fg=MUTED, font=("微软雅黑", 8)).pack(side=tk.LEFT, padx=16, pady=4)
        tk.Label(footer, text="v1.0",
                 bg=SIDEBAR, fg=MUTED, font=("微软雅黑", 8)).pack(side=tk.RIGHT, padx=16)

    def _switch_tab(self, key):
        if self._current_tab:
            self._pages[self._current_tab].pack_forget()
            self._tab_btns[self._current_tab].config(
                bg=SIDEBAR, fg=MUTED, relief="flat")
        self._current_tab = key
        self._pages[key].pack(fill=tk.BOTH, expand=True, padx=18, pady=14)
        self._tab_btns[key].config(bg=ACCENT2, fg=TEXT)

    def _restore_config(self):
        self.v_api_id.set(self.config.get("api_id", ""))
        self.v_api_hash.set(self.config.get("api_hash", ""))
        self.v_phone.set(self.config.get("phone", ""))

    # ── 通用组件 ──────────────────────────────────────────────────────────────

    def _form_row(self, parent, label, row, var=None, show=None, width=36):
        DarkLabel(parent, label, fg=MUTED, font_size=8).grid(
            row=row, column=0, sticky="w", pady=(10, 2), padx=(0, 10))
        v = var or tk.StringVar()
        e = DarkEntry(parent, textvariable=v, width=width, show=show or "")
        e.grid(row=row, column=1, sticky="ew", pady=(10, 2))
        return v

    def _separator(self, parent, row):
        tk.Frame(parent, bg=BORDER, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8)

    def _section(self, parent, title, row):
        SectionTitle(parent, title).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(12, 4))

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 ── 登录
    # ════════════════════════════════════════════════════════════════════════

    def _tab_login(self, f):
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "🔑  账号登录").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.v_api_id   = self._form_row(inner, "API ID",          2)
        self.v_api_hash = self._form_row(inner, "API Hash",         3)
        self.v_phone    = self._form_row(inner, "手机号（含 + 区号）", 4)

        DarkLabel(inner, "获取 API：my.telegram.org → App configuration",
                  fg=MUTED, font_size=8).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 10))

        self.btn_login = FlatButton(inner, "  登录 / 连接  ",
                                    command=self._do_login,
                                    bg=ACCENT, active_bg=ACCENT2)
        self.btn_login.grid(row=6, column=0, columnspan=2, pady=8, sticky="w")

        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(4, 8))

        DarkLabel(inner, "运行日志", fg=MUTED, font_size=8).grid(
            row=8, column=0, columnspan=2, sticky="w")
        self.login_log = DarkLog(inner, height=10)
        self.login_log.grid(row=9, column=0, columnspan=2, sticky="nsew", pady=4)
        inner.rowconfigure(9, weight=1)

    def _do_login(self):
        api_id   = self.v_api_id.get().strip()
        api_hash = self.v_api_hash.get().strip()
        phone    = self.v_phone.get().strip()
        if not (api_id and api_hash and phone):
            messagebox.showwarning("提示", "请填写 API ID、API Hash 和手机号")
            return
        self.config.update({"api_id": api_id, "api_hash": api_hash, "phone": phone})
        self._save_config()
        self.btn_login.set_state("disabled")
        self._log(self.login_log, "正在连接 Telegram...")
        self._async(self._connect(int(api_id), api_hash, phone))

    async def _connect(self, api_id, api_hash, phone):
        try:
            self.client = TelegramClient(SESSION_FILE, api_id, api_hash, loop=self.loop)
            await self.client.connect()
            if not await self.client.is_user_authorized():
                await self.client.send_code_request(phone)
                self._log(self.login_log, "验证码已发送，请查收")
                self._ui(self._ask_code, phone)
            else:
                me = await self.client.get_me()
                self._log(self.login_log, f"✅ 已登录：{me.first_name}  @{me.username or me.id}")
                self._ui(self.status_dot.config, text=f"● {me.first_name}", fg=SUCCESS)
                self._ui(self.btn_login.set_state, "normal")
        except Exception as e:
            self._log(self.login_log, f"❌ 连接失败：{e}")
            self._ui(self.btn_login.set_state, "normal")

    def _ask_code(self, phone):
        code = simpledialog.askstring("验证码", "输入 Telegram 发送的验证码：", parent=self.root)
        if code:
            self._async(self._sign_in(phone, code.strip()))

    async def _sign_in(self, phone, code):
        try:
            await self.client.sign_in(phone, code)
            me = await self.client.get_me()
            self._log(self.login_log, f"✅ 登录成功：{me.first_name}")
            self._ui(self.status_dot.config, text=f"● {me.first_name}", fg=SUCCESS)
        except SessionPasswordNeededError:
            self._ui(self._ask_2fa)
        except Exception as e:
            self._log(self.login_log, f"❌ 登录失败：{e}")
        finally:
            self._ui(self.btn_login.set_state, "normal")

    def _ask_2fa(self):
        pwd = simpledialog.askstring("两步验证", "输入两步验证密码：", show="*", parent=self.root)
        if pwd:
            self._async(self._sign_in_2fa(pwd))

    async def _sign_in_2fa(self, pwd):
        try:
            await self.client.sign_in(password=pwd)
            me = await self.client.get_me()
            self._log(self.login_log, f"✅ 登录成功：{me.first_name}")
            self._ui(self.status_dot.config, text=f"● {me.first_name}", fg=SUCCESS)
        except Exception as e:
            self._log(self.login_log, f"❌ 两步验证失败：{e}")
        finally:
            self._ui(self.btn_login.set_state, "normal")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 ── 消息转发
    # ════════════════════════════════════════════════════════════════════════

    def _tab_forward(self, f):
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "📨  消息转发").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.v_fw_src = self._form_row(inner, "来源  (用户名 / ID)", 2)
        self.v_fw_dst = self._form_row(inner, "目标  (用户名 / ID)", 3)
        self.v_fw_kw  = self._form_row(inner, "关键词过滤（空 = 转发全部）", 4)

        bf = tk.Frame(inner, bg=PANEL)
        bf.grid(row=5, column=0, columnspan=2, sticky="w", pady=12)
        self.btn_fw_start = FlatButton(bf, "  ▶  开始转发  ", command=self._start_forward,
                                       bg=ACCENT, active_bg=ACCENT2)
        self.btn_fw_stop  = FlatButton(bf, "  ■  停止转发  ", command=self._stop_forward,
                                       bg=BTN_BG, active_bg=ERROR)
        self.btn_fw_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_fw_stop.pack(side=tk.LEFT)
        self.btn_fw_stop.set_state("disabled")

        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        DarkLabel(inner, "转发日志", fg=MUTED, font_size=8).grid(
            row=7, column=0, columnspan=2, sticky="w")
        self.fw_log = DarkLog(inner, height=12)
        self.fw_log.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=4)
        inner.rowconfigure(8, weight=1)

    def _start_forward(self):
        if not self._check_login(): return
        src = self.v_fw_src.get().strip()
        dst = self.v_fw_dst.get().strip()
        if not (src and dst):
            messagebox.showwarning("提示", "请填写来源和目标"); return
        self.forwarding_active = True
        self.btn_fw_start.set_state("disabled")
        self.btn_fw_stop.set_state("normal")
        kw = self.v_fw_kw.get().strip()
        self._log(self.fw_log, f"开始转发  {src} → {dst}  关键词: {kw or '无限制'}")
        self._async(self._forward_loop(src, dst, kw))

    def _stop_forward(self):
        self.forwarding_active = False
        self.btn_fw_start.set_state("normal")
        self.btn_fw_stop.set_state("disabled")
        self._log(self.fw_log, "⚠ 已停止转发")

    async def _forward_loop(self, src, dst, keyword):
        try:
            src_e = await self.client.get_entity(src)
            dst_e = await self.client.get_entity(dst)
            src_name = getattr(src_e, "title", None) or getattr(src_e, "username", src)
            dst_name = getattr(dst_e, "title", None) or getattr(dst_e, "username", dst)
            self._log(self.fw_log, f"✅ 来源确认：{src_name}")
            self._log(self.fw_log, f"✅ 目标确认：{dst_name}")
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

            # 保持协程存活，持续接收事件
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
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "👥  群组管理").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.v_grp = self._form_row(inner, "群组  (用户名 / ID)", 2)

        bf = tk.Frame(inner, bg=PANEL)
        bf.grid(row=3, column=0, columnspan=2, sticky="w", pady=10)
        for label, cmd, color in [
            ("  加载成员  ", self._load_members, BTN_BG),
            ("  发公告    ", self._send_announce, BTN_BG),
            ("  踢出成员  ", self._kick_member,  "#6b2222"),
            ("  设欢迎语  ", self._set_welcome,  BTN_BG),
        ]:
            FlatButton(bf, label, command=cmd, bg=color,
                       active_bg=ACCENT).pack(side=tk.LEFT, padx=(0, 6))

        DarkLabel(inner, "成员列表", fg=MUTED, font_size=8).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 2))
        lf = tk.Frame(inner, bg=INPUT, highlightthickness=1,
                      highlightbackground=BORDER)
        lf.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=4)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.grp_list = DarkListbox(lf, height=7)
        sb = tk.Scrollbar(lf, bg=SIDEBAR, troughcolor=INPUT,
                          command=self.grp_list.yview)
        self.grp_list.config(yscrollcommand=sb.set)
        self.grp_list.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        DarkLabel(inner, "操作日志", fg=MUTED, font_size=8).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.grp_log = DarkLog(inner, height=5)
        self.grp_log.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        inner.rowconfigure(5, weight=1)

    def _load_members(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        if not group: messagebox.showwarning("提示", "请填写群组"); return
        self._async(self._fetch_members(group))

    async def _fetch_members(self, group):
        try:
            entity = await self.client.get_entity(group)
            parts  = await self.client.get_participants(entity, limit=200)
            self._ui(self.grp_list.delete, 0, tk.END)
            for p in parts:
                name  = f"{p.first_name or ''} {p.last_name or ''}".strip()
                uname = f"@{p.username}" if p.username else f"ID:{p.id}"
                self._ui(self.grp_list.insert, tk.END,
                         f"  {name:<22} {uname}")
            self._log(self.grp_log, f"✅ 已加载 {len(parts)} 名成员")
        except Exception as e:
            self._log(self.grp_log, f"❌ {e}")

    def _send_announce(self):
        if not self._check_login(): return
        group = self.v_grp.get().strip()
        msg = simpledialog.askstring("发公告", "输入公告内容：", parent=self.root)
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
        user  = simpledialog.askstring("踢出成员", "输入用户名 (@xxx) 或 ID：", parent=self.root)
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
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "⏰  定时发送").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.v_sch_target = self._form_row(inner, "目标  (用户名 / ID)", 2)
        self.v_sch_msg    = self._form_row(inner, "消息内容", 3)

        tf = tk.Frame(inner, bg=PANEL)
        tf.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
        DarkLabel(tf, "发送时间 HH:MM", fg=MUTED, font_size=8).pack(side=tk.LEFT)
        self.v_sch_time = tk.StringVar()
        DarkEntry(tf, textvariable=self.v_sch_time, width=8).pack(side=tk.LEFT, padx=8)
        self.v_sch_repeat = tk.BooleanVar(value=False)
        tk.Checkbutton(tf, text="每天重复", variable=self.v_sch_repeat,
                       bg=PANEL, fg=TEXT, selectcolor=INPUT,
                       activebackground=PANEL, activeforeground=ACCENT,
                       font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=8)

        FlatButton(inner, "  +  添加任务  ", command=self._add_job,
                   bg=ACCENT, active_bg=ACCENT2).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=6)

        DarkLabel(inner, "任务列表", fg=MUTED, font_size=8).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(6, 2))
        jf = tk.Frame(inner, bg=INPUT, highlightthickness=1,
                      highlightbackground=BORDER)
        jf.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        jf.columnconfigure(0, weight=1)
        self.job_list = DarkListbox(jf, height=4)
        sb = tk.Scrollbar(jf, bg=SIDEBAR, troughcolor=INPUT,
                          command=self.job_list.yview)
        self.job_list.config(yscrollcommand=sb.set)
        self.job_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        FlatButton(inner, "  删除选中任务  ", command=self._remove_job,
                   bg=BTN_BG, active_bg=ERROR).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=4)

        DarkLabel(inner, "操作日志", fg=MUTED, font_size=8).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.sch_log = DarkLog(inner, height=5)
        self.sch_log.grid(row=10, column=0, columnspan=2, sticky="nsew", pady=4)
        inner.rowconfigure(10, weight=1)

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
        self.job_list.insert(tk.END, label)
        self._log(self.sch_log, f"✅ 已添加任务: {label.strip()}")

    def _remove_job(self):
        sel = self.job_list.curselection()
        if sel:
            idx = sel[0]
            self.scheduled_jobs.pop(idx)
            self.job_list.delete(idx)

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
                        threading.Timer(61, lambda j=job: j.update({"fired": False})).start()
            time_module.sleep(20)

    # ════════════════════════════════════════════════════════════════════════
    # TAB 5 ── 账号监控
    # ════════════════════════════════════════════════════════════════════════

    def _tab_monitor(self, f):
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "👁  账号监控").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.v_mon_chat = self._form_row(inner, "监控聊天 / 群 / 频道", 2)
        self.v_mon_kw   = self._form_row(inner, "关键词（逗号分隔，空 = 全部）", 3)
        self.v_mon_user = self._form_row(inner, "仅监控指定用户（可选 @xxx）", 4)

        bf = tk.Frame(inner, bg=PANEL)
        bf.grid(row=5, column=0, columnspan=2, sticky="w", pady=12)
        self.btn_mon_start = FlatButton(bf, "  ▶  开始监控  ",
                                        command=self._start_monitor,
                                        bg=ACCENT, active_bg=ACCENT2)
        self.btn_mon_stop  = FlatButton(bf, "  ■  停止监控  ",
                                        command=self._stop_monitor,
                                        bg=BTN_BG, active_bg=ERROR)
        self.btn_mon_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_mon_stop.pack(side=tk.LEFT)
        self.btn_mon_stop.set_state("disabled")

        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        DarkLabel(inner, "监控日志（触发时桌面弹窗提醒）",
                  fg=MUTED, font_size=8).grid(
            row=7, column=0, columnspan=2, sticky="w")
        self.mon_log = DarkLog(inner, height=14)
        self.mon_log.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=4)
        inner.rowconfigure(8, weight=1)

    def _start_monitor(self):
        if not self._check_login(): return
        chat = self.v_mon_chat.get().strip()
        if not chat: messagebox.showwarning("提示", "请填写监控对象"); return
        kws  = [k.strip() for k in self.v_mon_kw.get().split(",") if k.strip()]
        user = self.v_mon_user.get().strip().lstrip("@")
        self.monitoring_active = True
        self.btn_mon_start.set_state("disabled")
        self.btn_mon_stop.set_state("normal")
        self._log(self.mon_log, f"开始监控 {chat}  关键词:{kws or '全部'}  用户:{user or '全部'}")
        self._async(self._monitor_loop(chat, kws, user))

    def _stop_monitor(self):
        self.monitoring_active = False
        self.btn_mon_start.set_state("normal")
        self.btn_mon_stop.set_state("disabled")
        self._log(self.mon_log, "⚠ 已停止监控")

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
                if keywords and not any(k.lower() in text.lower() for k in keywords):
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
        f.configure(bg=PANEL)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill=tk.BOTH, expand=True)
        inner.columnconfigure(1, weight=1)

        SectionTitle(inner, "🔍  用户名监听").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        tk.Frame(inner, bg=BORDER, height=1).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        af = tk.Frame(inner, bg=PANEL)
        af.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        DarkLabel(af, "用户名", fg=MUTED, font_size=8).pack(side=tk.LEFT)
        self.v_uname = tk.StringVar()
        DarkEntry(af, textvariable=self.v_uname, width=20).pack(side=tk.LEFT, padx=8)
        FlatButton(af, "  +  添加  ", command=self._add_uname,
                   bg=ACCENT, active_bg=ACCENT2).pack(side=tk.LEFT)
        DarkLabel(af, "   间隔(秒)", fg=MUTED, font_size=8).pack(side=tk.LEFT, padx=(16, 4))
        self.v_uname_interval = tk.StringVar(value="60")
        DarkEntry(af, textvariable=self.v_uname_interval, width=6).pack(side=tk.LEFT)

        bf = tk.Frame(inner, bg=PANEL)
        bf.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
        FlatButton(bf, "  删除选中  ", command=self._del_uname,
                   bg=BTN_BG, active_bg=ERROR).pack(side=tk.LEFT, padx=(0, 6))
        self.btn_un_start = FlatButton(bf, "  ▶  开始监听  ",
                                       command=self._start_uname_check,
                                       bg=ACCENT, active_bg=ACCENT2)
        self.btn_un_stop  = FlatButton(bf, "  ■  停止监听  ",
                                       command=self._stop_uname_check,
                                       bg=BTN_BG, active_bg=ERROR)
        self.btn_un_start.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_un_stop.pack(side=tk.LEFT)
        self.btn_un_stop.set_state("disabled")

        DarkLabel(inner, "监听列表", fg=MUTED, font_size=8).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 2))
        lf = tk.Frame(inner, bg=INPUT, highlightthickness=1,
                      highlightbackground=BORDER)
        lf.grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)
        lf.columnconfigure(0, weight=1)
        self.uname_list = DarkListbox(lf, height=4)
        sb = tk.Scrollbar(lf, bg=SIDEBAR, troughcolor=INPUT,
                          command=self.uname_list.yview)
        self.uname_list.config(yscrollcommand=sb.set)
        self.uname_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        DarkLabel(inner, "检测日志（可用时桌面弹窗提醒）",
                  fg=MUTED, font_size=8).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(6, 2))
        self.uname_log = DarkLog(inner, height=8)
        self.uname_log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=4)
        inner.rowconfigure(7, weight=1)

    def _add_uname(self):
        uname = self.v_uname.get().strip().lstrip("@")
        if not uname: return
        if uname not in self._usernames_to_check:
            self._usernames_to_check.append(uname)
            self.uname_list.insert(tk.END, f"  @{uname:<20} ⏳ 等待检查")
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
        self.btn_un_start.set_state("disabled")
        self.btn_un_stop.set_state("normal")
        self._log(self.uname_log, f"开始监听，每 {interval} 秒检查一次")
        self._async(self._uname_check_loop(interval))

    def _stop_uname_check(self):
        self.username_checking_active = False
        self.btn_un_start.set_state("normal")
        self.btn_un_stop.set_state("disabled")
        self._log(self.uname_log, "⚠ 已停止监听")

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

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _check_login(self):
        if not self.client:
            messagebox.showwarning("未登录", "请先在「登录」页完成登录")
            return False
        return True


if __name__ == "__main__":
    root = tk.Tk()
    app = TelegramTool(root)
    root.mainloop()
