# VectorBody 2.0 · Web 版本

以原仓库 `core/` 算法作为唯一评分引擎的浏览器版。保留现有桌面应用，不修改 `vector_body_main.py` 或 PySide6。

## 功能

- **首页**：极简产品入口；暖白、橄榄绿、枫叶黄配色。
- **实时评估**：浏览器摄像头 → 每帧 MediaPipe 33 点 → 全身入镜检测/画面居中 → 稳定约 2 秒 → OneEuroFilter、骨盆根拓扑、DLS-IK、虚拟骨长和原评分引擎 → 自动评分/语音纠错 → 可调整再评。
- **视频评估**：上传视频，选择 8 类体式、正/侧位、普通/新手；自动识别稳定有效片段并保存最高分帧、S1/S2/S3、代偿风险、拓扑与DLS诊断。
- **评估报告**：SQLite 存储真实评估结果与历史记录；自动为最佳有效评分帧保存原图和骨骼叠加照片；可切换正位/背面原有骨骼与肌肉图，并提供新增侧位骨骼示意图，通过分项低分指标标注重点关注部位；支持打印/保存 PDF。默认不保存完整视频。

## 运行（推荐 Python 3.10）

将本目录的 `web_app.py`、`web/`、`requirements_web.txt` 放进原仓库 `VectorBody_v2` 根目录（与 `core/` 同级）。进入该根目录：

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements_web.txt
uvicorn web_app:app --host 127.0.0.1 --port 8000
```

浏览器打开：`http://127.0.0.1:8000/`。

接口：`/api/docs`、`/api/health`、`/api/poses`、`/api/live/start`、`/api/live/frame`、`/api/live/stop`、`/api/analyze-video`、`/api/reports`、`/api/reports/{id}/photos/original`、`/api/reports/{id}/photos/skeleton`、`/api/anatomy/{orientation}/{layer}`。

> 原仓库若已安装了其他 OpenCV 包，请在**独立虚拟环境**中安装 Web 依赖。`mediapipe==0.10.14` 需搭配兼容 Python、NumPy 1.x 和 OpenCV 版本；不建议直接覆盖桌面版环境。

## Docker / Render

```bash
docker build -t vectorbody-web .
docker run --rm -p 8000:8000 -v vectorbody-data:/app/web_data vectorbody-web
```

Render 可以从仓库中的 `render.yaml` 创建 Blueprint 服务。请选可承载 MediaPipe CPU 推理的实例（预设 Starter 仅为起点，实际所需计算资源以压力测试为准），配置持久磁盘，健康检查 `/api/health`，用 `https://` 公网域名访问，以便浏览器获取摄像头权限。此配置只是部署模板，不表示已上线。

Render 之外的 Docker 主机也可使用本文件。若采用多进程/多实例，需要把实时会话从当前进程内存转成统一的会话服务；当前配置固定 `--workers 1`。

## 重要限制与验收

- 评分严格来自原 `CompensationRiskEngine.analyze`；无随机评分。`S1/S2/S3` 权重沿用原项目（0.30/0.35/0.35）。
- 语音使用浏览器 `speechSynthesis`，不是 Windows SAPI；某些浏览器需点击按钮激活语音或安装中文语音包。
- 视频最高分来源于**稳定有效片段**，不是“整个视频的平均成绩”。若无有效片段，接口返回明确错误，而不是虚构结果。
- 该系统是体育教学辅助工具。视觉发力代理不是肌电、肌力或地面反作用力的直接测量，风险提示不能作为医疗诊断。
- **隐私重要**：新版本会把视频最高评分帧的照片存到服务器（完整视频仍不保存）。评委体验请使用已经获授权的脱敏视频。当前报告及照片接口没有用户鉴权，仅适合可信的本地测试；**在公网开放前必须新增鉴权、访问控制、限流、隐私授权与删除/保留策略**。
- 报告照片位于 `web_data/report_photos/<报告编号>/`，包含 `original.jpg` 和 `skeleton.jpg`；删除报告时会一起删除照片。旧版报告无照片仍可查看。请定期备份/清理并设置合规保存期限。
- 正位和背面骨骼/肌肉图继续直接使用原仓库 `assets/front_skeleton.png`、`assets/back_skeleton.png`、`assets/front_muscle.png`、`assets/back_muscle.png`，侧位使用新建的网页示意 SVG（非额外拍摄/检测数据）。
- 问题部位源于当前动作的分项评分和规则提示。它是运动学习辅助信息，不是病患诊断，无法识别确切损伤，也不会凭一个摄像机画面确定左右肢体病理。
- 浏览器语音替代 Windows SAPI；网页中的解剖视图展示为示意，不直接显示肌肉真实受力。
- 未在本执行环境完成真实 MediaPipe 运行/公网压力测试前，不应声称已经完成生产验收。