# 风调预顺 PHM 系统 — 部署指南 (阿里云 ECS)

> 日期: 2026-06-12 | 版本: v1.0

---

## 1. 服务器选型建议

| 规格 | 推荐 | 月费用估算 |
|------|------|-----------|
| 实例 | ECS 轻量应用服务器 / ecs.c7.large | ~¥100-200 |
| CPU | 2 核 (最低) / 4 核 (推荐) | — |
| 内存 | 4 GB (最低) / 8 GB (推荐) | — |
| 系统盘 | 40 GB ESSD | ~¥20 |
| 带宽 | 3-5 Mbps 按量 | ~¥30-80 |
| 系统 | Ubuntu 22.04 LTS | — |
| **月总** | | **~¥150-300** |

> 初期建议选 **阿里云轻量应用服务器 2核4G 5Mbps** (~¥90/月)，够 5-10 人使用。后期根据负载升配。

---

## 2. 环境安装

### 2.1 连接到服务器

```bash
# 阿里云控制台获取公网IP，然后SSH连接
ssh root@<服务器公网IP>
```

### 2.2 安装基础软件

```bash
# 更新系统
apt update && apt upgrade -y

# 安装 Python 3.11+
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# 安装 Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# 安装 Nginx (反向代理)
apt install -y nginx

# 安装 git
apt install -y git

# 验证
python3.11 --version  # Python 3.11.x
node --version         # v20.x.x
npm --version          # 10.x.x
nginx -v               # 1.24.x
```

### 2.3 安装 SQLite (或 PostgreSQL)

```bash
# SQLite (推荐开发/小团队)
apt install -y sqlite3

# 验证
sqlite3 --version
```

---

## 3. 部署项目

### 3.1 拉取代码

```bash
# 创建项目目录
mkdir -p /opt/fengdiao
cd /opt/fengdiao

# 从你的代码仓库拉取 (或手动上传)
git clone <你的仓库地址> .
git checkout master  # 纯代码分支

# 或使用 dev 分支 (含文档)
# git checkout dev
```

### 3.2 配置后端

```bash
cd /opt/fengdiao/backend

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖 (使用清华镜像加速)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 创建 .env 配置文件
cp .env.example .env

# 编辑 .env，修改以下关键项:
nano .env
```

**.env 关键配置:**

```env
# 生产环境必须改!
SECRET_KEY=生成一个随机字符串(至少32位)
DEBUG=false

# 数据库 (小团队用SQLite即可)
DATABASE_URL=sqlite+aiosqlite:///./fengdiao_phm.db

# AI 模型 (必填! 否则 AI 功能无法使用)
DASHSCOPE_API_KEY=你的阿里百炼API-KEY
# 或使用 OpenAI
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1

# 邮件 (可选)
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USER=你的邮箱@qq.com
SMTP_PASSWORD=授权码
SMTP_FROM=你的邮箱@qq.com
```

### 3.3 初始化数据库

```bash
cd /opt/fengdiao/backend
source venv/bin/activate

# 初始化数据库 + 种子数据
python -m scripts.seed_data
```

输出应该显示：
```
✅ 数据表创建完成
✅ 知识库: 导入 22 个故障节点
🔑 登录账号: admin / admin123
```

### 3.4 配置前端

```bash
cd /opt/fengdiao/frontend

# 安装依赖
npm install

# 构建生产版本
npm run build
# 输出在 frontend/dist/ 目录
```

### 3.5 配置后端服务 (systemd)

```bash
# 创建服务文件
nano /etc/systemd/system/fengdiao-backend.service
```

```ini
[Unit]
Description=风调预顺 PHM Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/fengdiao/backend
ExecStart=/opt/fengdiao/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
```

```bash
# 启动后端服务
systemctl daemon-reload
systemctl enable fengdiao-backend
systemctl start fengdiao-backend

# 检查状态
systemctl status fengdiao-backend
```

### 3.6 配置 Nginx 反向代理

```bash
nano /etc/nginx/sites-available/fengdiao
```

```nginx
server {
    listen 80;
    server_name <你的域名或IP>;

    # 前端静态文件
    root /opt/fengdiao/frontend/dist;
    index index.html;

    # 前端页面
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理到后端
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;  # AI调用可能较慢
    }

    # 静态数据代理
    location /data/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # Gzip 压缩
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 256;
}
```

```bash
# 启用配置
ln -s /etc/nginx/sites-available/fengdiao /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default  # 删默认

# 测试配置
nginx -t

# 重启 Nginx
systemctl reload nginx
```

### 3.7 配置防火墙

阿里云控制台 → 安全组规则 → 添加入方向:
- 端口 80 (HTTP)
- 端口 443 (HTTPS，如需)
- 端口 22 (SSH)

---

## 4. 部署后验证

```bash
# 1. 后端健康检查
curl http://localhost:8000/api/health
# {"status":"ok","app":"风调预顺 - PHM预测性运维系统","version":"2.0.0"}

# 2. 前端通过 Nginx 访问
curl http://localhost/
# 返回 index.html 内容

# 3. 登录测试
curl -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 返回 JWT token

# 4. 知识库测试
curl -H "Authorization: Bearer <token>" http://localhost/api/knowledge-base
```

然后用浏览器访问: `http://<服务器公网IP>` → 看到登录页 → 输入 `admin` / `admin123` → 登录成功。

---

## 5. 可选：配置 HTTPS

使用 Let's Encrypt 免费证书：

```bash
apt install -y certbot python3-certbot-nginx

# 前提: 已有域名并解析到服务器IP
certbot --nginx -d fengdiao.yourdomain.com

# 自动续期
certbot renew --dry-run
```

---

## 6. 日常维护

### 更新代码

```bash
cd /opt/fengdiao
git pull origin master  # 或 dev

# 后端
cd backend && source venv/bin/activate
pip install -r requirements.txt -q
systemctl restart fengdiao-backend

# 前端
cd ../frontend
npm install --silent
npm run build
# Nginx 自动使用新的 dist/ 目录
```

### 查看日志

```bash
# 后端日志
journalctl -u fengdiao-backend -f

# Nginx日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### 数据库备份

```bash
# SQLite: 直接复制文件
cp /opt/fengdiao/backend/fengdiao_phm.db /backup/fengdiao_$(date +%Y%m%d).db

# 建议添加 crontab 每日备份
0 3 * * * cp /opt/fengdiao/backend/fengdiao_phm.db /backup/fengdiao_$(date +\%Y\%m\%d).db
```

---

## 7. 费用预估

| 项目 | 月费 |
|------|------|
| ECS 轻量服务器 2核4G | ~¥90 |
| 带宽 5Mbps | ¥125 (按量看实际) |
| 系统盘 40GB | ~¥14 |
| **基础设施月费** | **~¥230** |
| | |
| 阿里百炼 API (可选) | 按量付费 |
| 域名 (可选) | ~¥60/年 |

**初期月成本约 ¥230-300。**
