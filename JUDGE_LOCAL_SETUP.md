# VectorBody_v2 · 本地 Python 评委扫码体验（163 统一测试账号）

本分支保留 **Python 3.10 / FastAPI / MediaPipe / OpenCV / DLS-IK / S1/S2/S3** 评分逻辑，新增：

- 实时评估、视频分析都必须填写 **受评者姓名或匿名代号**（1–32 字符）。
- 姓名随报告保存在 `web_data/reports.sqlite3`，报告列表、完整报告及“打印 / 保存PDF”界面显示姓名，并可按姓名精确查找。
- 原有 SQLite 数据库在首次启动时**只新增 student_name 列，不删除旧报告**；旧记录显示“未填写姓名”。
- 评委通过统一测试邮箱 `huanjiaceshi@163.com` + **VectorBody 专用网站密码** 登录。**不是邮箱真实密码，也无需 SMTP、163 授权码或收取邮件验证码。**
- 登录凭据作为本地环境变量配置，使用 HttpOnly 会话 Cookie；未登录者无法调用成绩、照片、视频评估和报告接口。
- 二维码只指向公网 HTTPS 地址，**不含网站密码**。评委扫码后仍需登录。
- **共享测试账号**下的报告对登录评委可见。默认**禁止删除历史报告**，以免误删。此模式不是多学生独立账号系统。

## 一、你电脑本地运行（VS Code PowerShell）

在你的项目根目录打开终端（替换成实际位置）：

```powershell
cd D:\VectorBody_v2-main
conda activate VectorBodyWeb
python -m pip install -r requirements_web.txt
```

如果还没有 Conda 环境：

```powershell
conda create -n VectorBodyWeb python=3.10 -y
conda activate VectorBodyWeb
python -m pip install -r requirements_web.txt
```

### 不要在 GitHub、脚本、聊天或命令历史中填写邮箱的真实密码

在每次启动 Web 服务前，使用 PowerShell 的隐藏输入设置网站测试密码：

```powershell
$secret = Read-Host "设置 VectorBody 网站测试密码（至少12位，不是163邮箱密码）" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
    $env:VECTORBODY_TEST_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
```

如果只在本机通过 `http://127.0.0.1:8000` 调试：

```powershell
Remove-Item Env:VECTORBODY_PUBLIC_URL -ErrorAction SilentlyContinue
$env:VECTORBODY_COOKIE_SECURE = "false"
python -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`，会跳转到登录页。输入账号 `huanjiaceshi@163.com` 和你刚设置的网站测试密码。

> 请不要把网站密码设为123456、邮箱密码，或公开张贴在二维码旁。建议16位以上随机字符串，通过私下方式发给评委。

## 二、手机外网扫码（本地 Python 服务仍运行在你的电脑上）

先运行 Python Web 服务，地址仅绑定 **127.0.0.1:8000**。再通过受信任的 HTTPS 公网隧道（例如 Cloudflare Tunnel）暴露这个本地端口，**不要直接把 8000 端口开放到公网**。

如果你已安装 cloudflared，可在 **第二个 PowerShell 终端**执行：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

它会输出一个实际的 HTTPS 公网地址（由工具分配，不能预先假定）。复制该地址，然后在运行 uvicorn 的第一个终端按 Ctrl+C 停止服务，设置：

```powershell
Remove-Item Env:VECTORBODY_COOKIE_SECURE -ErrorAction SilentlyContinue
$env:VECTORBODY_PUBLIC_URL = "https://此处粘贴隧道实际输出的域名"
python -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

使用 **实际地址**，不要复制示例文本。登录 Python 页面后点击“评委扫码入口”，便可展示二维码；手机扫码后到登录页，评委使用统一邮箱和网站测试密码进入。使用 HTTP 本地调试时应先停止开启的公网环境配置；公网 HTTPS 下 Cookie 必须标记为 Secure。

手机摄像头需要 HTTPS 安全上下文以及浏览器授权。电脑关机、休眠、断网或隧道退出后，外部均无法继续使用。希望电脑关机后可继续使用，需要独立服务器/云部署。使用临时隧道时，分配的网址可能在重启后改变，需要重新设置并重新生成二维码。

## 三、报告与数据

- 数据库：`web_data/reports.sqlite3`
- 原图与骨架照片：`web_data/report_photos/<报告ID>/`
- 登录会话数据库：`web_data/shared_access.sqlite3`
- 不保存完整视频。
- 评估后按“评估报告”查看、输入姓名查询；打开单份报告点击“打印 / 保存PDF”，在浏览器打印对话框中选择“另存为 PDF”。
- 统一评委账号不隔离学生记录，评委可查看所有已存测试报告。**请使用获授权或脱敏的视频**。准备真实课程教学时须改成每人独立账号与报告所有权隔离。
- 建议定期备份 `web_data`。该文件夹及本地密码配置已被 `.gitignore` 排除，不要提交到公开仓库。

## 四、问题排查

- 启动报 `VECTORBODY_TEST_PASSWORD`：先设置网站专用密码，长度至少12位。
- 本机能访问、手机不能：确认隧道终端正在运行、复制了实际 HTTPS 网址、正确设置 `VECTORBODY_PUBLIC_URL`。
- 能打开登录页面但一直跳回登录：检查公网 HTTPS 下没有设置 `VECTORBODY_COOKIE_SECURE=false`；登录前请清除该网站旧 Cookie。
- 登录接口返回429：连续失败次数过多，15分钟后重试。
- 新报告不出现：必须获得有效稳定评分，完成评估后才自动保存；数据库必须有写入权限。
- 无法打印：先在“评估报告”打开完整报告，再使用“打印 / 保存PDF”选择系统 PDF 打印机。

## 安全界限

此功能仅适合**受控的评委演示和有限测试**。登录访问不等同于学校级身份管理或数据隔离。不提供真实163邮箱收信能力，也不要求输入任何邮箱授权码。部署时使用 HTTPS 隧道，确保电脑操作系统、依赖库和隧道客户端及时更新。
