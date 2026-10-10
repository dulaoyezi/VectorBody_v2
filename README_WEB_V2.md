# 智瑜镜 · VectorBody v2 Web Edition

基于仓库中**原有** `core/` 的 FastAPI Web 版本。Web 后端不引入 `PySide6`、`pythoncom`、`pyttsx3`、SAPI。没有伪造评分，也不引入教学 Agent。保留原有桌面程序 `vector_body_main.py` 和旧版 `web_api.py` 不变。

## 功能

- 4个一级页面：首页、实时评估、视频评估、评估报告/历史记录。
- 8种体式：战士一式、战士二式、山式、简易坐、站立前屈式、眼镜蛇式、平衡式、下犬式；支持正/侧位、普通/新手阈值（沿用仓库 `CompensationRiskEngine.POSE_PROFILES`）。
- 重用 MediaPipe 33 点、OneEuroFilter、骨盆根拓扑树、DLS-IK 优化、虚拟骨长一致性、S1/S2/S3 和代偿风险评分。
- 上传视频：真正逐帧检测，筛选连续2秒稳定后的最佳有效评分帧，保存骨架叠加 JPEG、SQLite JSON 报告。
- 实时评估：浏览器摄像头 → WebSocket JPEG → 后端；动作引导 → 入镜检查 → 稳定2秒 → 评分 → 纠正 → 再评估。
- 语音使用浏览器内置 `speechSynthesis`（需要浏览器可用的中文语音）；不会从服务器调用 Windows SAPI。

## 本地启动（Windows PowerShell）

建议使用你现有的 `D:\conda\envs\VectorBody` 环境，或新建 Python 3.10 虚拟环境。将本补丁中的 `web_v2/`、`requirements_web_v2.txt`、`Dockerfile.web`、`docker-compose.web.yml` 放到原 `VectorBody_v2` **根目录**，确保原有 `core/` 不被覆盖。

```powershell
cd D:\VectorBody_v2-main
& "D:\conda\envs\VectorBody\python.exe" -m pip install -r requirements_web_v2.txt
& "D:\conda\envs\VectorBody\python.exe" -m uvicorn web_v2.app:app --host 127.0.0.1 --port 8000
```

仅需**一个服务**。浏览器打开 `http://127.0.0.1:8000/`；文档在 `http://127.0.0.1:8000/docs`。

如遇到 Windows 语音模块问题，勿使用 `vector_body_main.py` 启动 Web；正确入口为 `web_v2.app:app`。

## Docker / Linux 部署

```bash
docker compose -f docker-compose.web.yml up --build -d
curl -f http://127.0.0.1:8000/health
```

默认仅绑定宿主机 `127.0.0.1`；公网部署需自行配置具备 HTTPS、认证和访问控制的反向代理，检查服务器是否有足够计算资源。摄像头权限仅在 HTTPS 或 localhost 下可用。

**安全边界**：当前适合单机教学演示和受信任的内网测试；无登录/用户隔离/限额配额，历史记录为服务实例共享，不应未经补充认证和隐私治理就直接开放公网。视频最大120MB，WebSocket 单帧最大1MB，非医疗用途。上传视频临时文件分析后删除；SQLite 报告和最佳帧默认保存在 `reports/web`，可以通过环境变量 `VECTORBODY_DATA_DIR` 调整。建议定期删除不再需要的报告。

## API

| HTTP / WS | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| GET | `/poses` | 动作/视角/难度元数据 |
| POST | `/analyze-video?pose=warrior2&view=front&level=normal` | FormData `file=视频`；真实逐帧分析 |
| WebSocket | `/ws/assess` | 首帧发送 JSON 配置，随后发送 JPEG 二进制帧 |
| GET | `/api/reports` | 查询归档列表 |
| GET | `/api/reports/{id}` | 报告 JSON |
| GET | `/api/reports/{id}/frame` | 最佳帧 JPEG |

WebSocket 首条消息示例：

```json
{"pose":"warrior2","view":"front","level":"normal"}
```

之后按一定节奏发送 JPEG 字节帧；服务端返回 `phase`、`message`、`landmarks` 和（出现有效评分时）`result`，其中 `phase` 包括 `guide`、`framing`、`stabilizing`、`scoring`、`advice` 和再次评估过程。前端通过浏览器合成语音进行引导与纠正。

### 有效性与归档原则

- 对 MediaPipe 关键点能见度和画面边界进行筛查；未入镜不给分。
- 检测窗口建立后，已就绪但不符合虚拟骨长一致性要求的帧不作为有效评分。
- 视频分析要求有效动作连续稳定约2秒后才能选取最佳评分帧；如果没有合格帧，返回 HTTP 422，**不生成随机成绩**。
- 目前视频分析会遍历最多 `max_frames` 帧，长视频上传可能需较长时间；本版本不实现异步队列和上传进度推送。
- 相机检测的2秒为服务器收到有效稳定帧后的近似墙钟时间；实际体验受网络和帧率影响。
- S3 是视觉支撑/发力代理，不等于真实肌肉力或地面反作用力；代偿风险是教学提示，不是损伤诊断。

## 验证

```bash
python -m compileall -q web_v2
python -m pytest tests/test_web_v2.py -q
```

必须进一步使用真实8类体式视频和真实摄像头进行验收：实际帧率、延迟、DLS 残差、骨长稳定性、评分可重复性、错误帧抑制、专家一致性。仓库原算法的真实效果不能由前后端接口测试代替。

## 部署状态

本补丁提供了容器部署文件与本地可运行入口。**没有自动部署到任何公网域名**；如果要公开体验，需要先启用访问控制、HTTPS 和安全的用户数据管理，并配置实际服务器或部署平台。