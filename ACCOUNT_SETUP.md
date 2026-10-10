# VectorBody Python 邮箱登录和扫码绑定（试验版）

启动前设置 VECTORBODY_AUTH_SECRET（至少32个随机字符）、VECTORBODY_SMTP_HOST、VECTORBODY_SMTP_PORT、VECTORBODY_SMTP_USER、VECTORBODY_SMTP_PASSWORD、VECTORBODY_SMTP_FROM。安装 email-validator。

本模块提供 /api/account/otp、/verify、/me、/pair/new、/pair/confirm、/logout。二维码内容应为 HTTPS 域名下 /?pair=<token>，前端需要生成二维码、要求手机邮箱登录并由用户主动确认，不能把 token 作为登录凭证。

重要：现有 /api/reports 和视频分析接口尚未完成用户所有权授权改造，不能公开部署或存储真实学生数据。该分支仅为后端账号原型，不能视为完整学生端上线版本。