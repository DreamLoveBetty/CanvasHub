<p align="center">
  <img src="frontend/assets/canvashub-cover.png" alt="CanvasHub 桌面画布封面" width="100%">
</p>

# CanvasHub

**语言：** [English](README.md) | 中文

一个模块化节点的 Image2/banana 图像生成，图片资产管理以及提示词优化项目。
  *Image2生成需要导入 codex oauth/本地 codex 登录/web端 RT/AT 导入(账号池 api)，banana 生成需接入第三方 api。

本项目规模较小：一个 Python HTTP 服务器同时服务于小程序/静态桌面界面以及界面使用的 JSON API。生成的图像会存档在本地，Telegram 同步这些存档。

注：Telegram 小程序需要公网 IP 或做反向代理，隧道穿透。
    *姿态参考节点/排版节点，comfyui 调用未完成。

## 安全默认值

- 服务默认绑定到 `127.0.0.1`。
- 公网模式需要在设置中心 -> 系统中手动开启。
- 公网模式必须设置小程序访问密码。
- 运行时数据和本地密钥默认被 Git 忽略。
- `settings.json` 是本地配置文件，不应提交。
- 内置密码门禁是轻量访问控制，不是企业级多用户 RBAC。

## 快速开始

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp settings.example.json settings.json
python3 server.py
```

然后打开：

```text
http://127.0.0.1:18463/desktop.html
```

Windows 用户可以在项目根目录双击 `start-windows.bat` 一键启动。脚本会在需要时创建 `.venv`、安装依赖并打开桌面页面。需要停止时双击 `stop-windows.bat`。

macOS/Linux 可以使用 `./start.sh` 启动本地应用。

如果通过隧道或反向代理暴露应用，并希望 `start.sh` 打印用于 BotFather 配置的公开 URL，可以设置 `MINIAPP_PUBLIC_URL`：

```bash
MINIAPP_PUBLIC_URL=https://your-domain.example ./start.sh
```

## 桌面 App

桌面版可以从 [GitHub Releases](https://github.com/DreamLoveBetty/CanvasHub/releases)
下载。应用设置、账号信息、图片归档、缓存和可选组件会保存在当前用户的数据
目录中，覆盖安装或升级应用不会清除这些内容。

### 高清放大组件

为了控制安装包体积，高清放大组件不会包含在首次安装包中。用户第一次运行
高清放大节点时，应用会自动在后台下载、校验并安装对应组件，无需手动查找、
下载或解压文件。界面会显示下载进度，安装完成后继续执行高清放大；以后使用
会直接复用已经安装的组件。

组件下载需要能够访问 GitHub。下载中断时可以重新点击高清放大，应用会继续
下载或重新尝试安装。普通生图、编辑和图库功能不受高清组件下载状态影响。

未使用 Developer ID 的 macOS 包适合内测：用户可右键应用选择“打开”，或在
“系统设置 -> 隐私与安全性”中选择“仍要打开”。如果仍被隔离，可执行：

```bash
xattr -dr com.apple.quarantine /Applications/CanvasHub.app
open /Applications/CanvasHub.app
```

不要让用户全局关闭 Gatekeeper。macOS 可靠自动更新需要 Developer ID 签名
和 Apple 公证；未签名版本应通过重新下载新版 DMG 手动更新。

## 配置

大多数运行时设置都可以在桌面端设置中心中编辑。

- 系统：绑定地址、端口、公网模式、访问密码。
- Telegram：Bot Token、Chat ID、允许用户 ID、Telegram 代理。
- Provider：本地 Codex provider、托管 Codex OAuth、传输策略、超时。
- 第三方：nano banana / 兼容图片 API。
- 账号池：账号连接和授权账号管理。
- 润色：提示词技能 provider/model 配置。
- 路径：归档目录、源图目录、任务数据库。

默认存储路径位于项目目录内：

```text
data/archive
data/source_images
tasks.db
```

路径设置可在设置中心 -> 路径中修改。相对路径会从仓库根目录解析。

## 可选运行时远程提示源

图库工作区可以在运行时选择同步公开远程仓库中的提示词/示例图记录。运行同步后的数据会写入 `data/source_images/` 等本地运行时目录。感谢作者的收集/开源，以下是几个仓库地址。

| 来源 | 上游仓库 |
| --- | --- |
| GPT Image 2 | `https://github.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts` |
| Awesome GPT Image | `https://github.com/ZeroLu/awesome-gpt-image` |
| GPT-4o Image | `https://github.com/ImgEdify/Awesome-GPT4o-Image-Prompts` |
| YouMind GPT Image 2 | `https://github.com/YouMind-OpenLab/awesome-gpt-image-2` |
| YouMind Nano Banana Pro | `https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts` |
| DavidWu GPT Image2 Prompts | `https://github.com/davidwuw0811-boop/awesome-gpt-image2-prompts` |

## 可选 3D 资产

公开仓库不内置 Director Stage 的 `xbot.glb` / `ybot.glb` 模型文件。缺少这些文件时，应用会使用程序化人体模型作为 fallback。

如需启用可选 GLB 人体模型，请下载文件并放到：

```text
static/pose/mannequin/xbot.glb
static/pose/mannequin/ybot.glb
```

来源链接和命令见 `static/pose/mannequin/README.md`。

## 公网模式

公网模式默认关闭。如果需要让应用在本机之外访问：

1. 打开 `desktop.html`。
2. 进入设置中心 -> 系统。
3. 开启公网模式。
4. 设置非空访问密码。
5. 保存并重启 Python 服务。

公网模式只改变服务绑定地址。面向互联网部署时，请自行配置 HTTPS、反向代理、防火墙规则以及 Telegram 域名设置。

## 第三方通知

见 `THIRD_PARTY_NOTICES.md`。

## 许可

项目自有源码使用 MIT License。随附第三方代码和资产仍遵循其各自许可；详见 `THIRD_PARTY_NOTICES.md`。
