# TG 多功能工具

> 版权所有 © 岁岁 | Telegram: @qqfaka

一款基于 Python + Tkinter 的 Telegram 桌面多功能工具，深色 UI 设计，支持多项自动化功能。

## 功能

| 功能 | 说明 |
|------|------|
| 🔑 登录 | 输入 API ID + API Hash + 手机号，支持验证码和两步验证 |
| 📨 消息转发 | 设来源/目标，可加关键词过滤，实时自动转发 |
| 👥 群组管理 | 加载成员列表、发公告、踢人、设置新成员欢迎语 |
| ⏰ 定时发送 | 设定时间+内容，支持每天重复发送 |
| 👁 账号监控 | 监控群/频道关键词或指定用户，触发桌面弹窗通知 |
| 🔍 用户名监听 | 定期检测目标用户名是否可注册，可用立即弹窗提醒 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 打包为 exe（Windows）

```bash
build.bat
```

或手动执行：

```bash
pyinstaller --onefile --windowed --name "TG多功能工具" main.py
```

### 3. 运行

直接运行 `dist/TG多功能工具.exe`，在登录页填入：

- **API ID** 和 **API Hash**：前往 [my.telegram.org](https://my.telegram.org) → App configuration 获取
- **手机号**：含国际区号，如 `+86138xxxxxxxx`

## 依赖

- Python 3.8+
- [Telethon](https://github.com/LonamiWebs/Telethon)
- [Plyer](https://github.com/kivy/plyer)（桌面通知）
- [PyInstaller](https://pyinstaller.org)（打包）

## 项目结构

```
tg-tool/
├── main.py          # 主程序
├── requirements.txt # 依赖列表
└── build.bat        # 一键打包脚本
```

## 注意事项

- 本工具仅供学习交流使用
- 请勿用于违反 Telegram 服务条款的行为
- API ID 和 session 文件请妥善保管，勿泄露

---

**© 2025 岁岁 | Telegram: @qqfaka**
