# TG 多功能工具 v2.0

> 版权所有 © 岁岁 | Telegram: @qqfaka

一款基于 Python + CustomTkinter 的 Telegram 桌面多功能工具，深色现代化 UI，支持多账号管理与多项自动化功能。

## 下载

[**⬇ 直接下载 exe（免安装）**](https://github.com/Guyi888/tg-tool/releases/latest)

---

## 功能

| 功能 | 说明 |
|------|------|
| 🔑 多账号登录 | 保存多个账号档案，顶部下拉一键切换，独立 session 文件 |
| 📨 消息转发 | 设来源/目标，可加关键词过滤，实时自动转发 |
| 👥 群组管理 | 加载成员列表、导出 CSV、发公告、踢人、设置新成员欢迎语 |
| ⏰ 定时发送 | 设定时间 + 内容，支持每天重复发送 |
| 👁 账号监控 | 监控群/频道关键词或指定用户，触发桌面弹窗通知 |
| 🔍 用户名监听 | 定期检测目标用户名是否可注册，可用立即弹窗提醒 |
| 📝 消息模板库 | 创建/编辑/复用常用消息模板，持久化保存 |
| 📤 批量私信 | 从群组加载成员批量发送私信，支持变量替换和发送间隔控制 |

---

## 快速开始

### 方式一：直接运行 exe（推荐）

前往 [Releases](https://github.com/Guyi888/tg-tool/releases/latest) 下载最新版 `TG多功能工具.exe`，双击即可运行，无需安装 Python。

### 方式二：源码运行

**1. 安装依赖**

```bash
pip install -r requirements.txt
```

**2. 运行**

```bash
python main.py
```

**3. 打包为 exe（Windows）**

```bash
build.bat
```

或手动执行：

```bash
python -m PyInstaller --onefile --windowed --name "TG多功能工具" --collect-all customtkinter main.py
```

---

## 首次使用

1. 前往 [my.telegram.org](https://my.telegram.org) → App configuration 获取 **API ID** 和 **API Hash**
2. 在「登录」页填写 API ID、API Hash 和手机号（含国际区号，如 `+86138xxxxxxxx`）
3. 点击「保存账号」可将账号信息存档，下次直接选择即可
4. 点击「登录 / 连接」，输入手机收到的验证码完成登录

---

## 依赖

| 库 | 用途 |
|----|------|
| [Telethon](https://github.com/LonamiWebs/Telethon) | Telegram API 客户端 |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | 现代化 UI 框架 |
| [Plyer](https://github.com/kivy/plyer) | 桌面通知 |
| [PyInstaller](https://pyinstaller.org) | 打包为 exe |

---

## 项目结构

```
tg-tool/
├── main.py           # 主程序
├── requirements.txt  # 依赖列表
├── build.bat         # 一键打包脚本
└── config.json       # 运行时生成，保存账号和模板数据
```

---

## 更新日志

### v2.0
- 新增多账号管理，支持保存多个账号档案
- 新增消息模板库（保存/编辑/一键发送）
- 新增批量私信（支持 `{name}` 变量、进度条、FloodWait 自动处理）
- 群组管理新增导出成员 CSV
- UI 全面升级为 CustomTkinter，圆角按钮/现代外观
- 窗口尺寸记忆，右下角 Toast 通知，顶部任务状态栏

### v1.0
- 初始版本：登录、消息转发、群组管理、定时发送、账号监控、用户名监听

---

## 注意事项

- 本工具仅供学习交流使用
- 请勿用于违反 Telegram 服务条款的行为
- 批量私信请设置合理的发送间隔（建议 ≥ 30 秒），避免账号被限流
- API ID 和 session 文件请妥善保管，勿泄露

---

**© 2025 岁岁 | Telegram: @qqfaka**
