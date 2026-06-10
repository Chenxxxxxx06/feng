# 风调预顺 PHM — Git分支管理方案

> **团队：8人 | 仓库：G:\code\code_vscode\软件开发能力\feng**
> **方案日期：2026-06-10**

---

## 一、分支架构

```
master ───────●────────────●──────────●──────  (展示/交付)
              ↗            ↗          ↗
dev ────────●────●────●────●────●─────●──────  (日常集成)
            ↗    ↗    ↗    ↗    ↗
           p1   p2   p3   p4   p5 p6 p7 p8     (个人开发)
```

| 分支 | 作用 | 谁维护 | 说明 |
|------|------|--------|------|
| `master` | 稳定发布版 | 组长 | 始终可运行、可演示 |
| `dev` | 日常集成版 | 组长 | 所有人代码先合并到这里验证 |
| `p1` ~ `p8` | 个人开发分支 | 各成员 | 每人自己的分支，随便改 |

---

## 二、你的现有分支（从远程拉下来）

```
master   ← 当前只有这个在本地
dev      ← 需要拉取
feature  ← 多余，建议删除
test     ← 多余，建议删除
hotfix   ← 保留，紧急修复用
```

### 第一步：清理分支，只留有用的

```bash
cd G:\code\code_vscode\软件开发能力\feng

# 拉取所有远程分支
git fetch origin

# 切换到 dev 并拉下来
git checkout -b dev origin/dev

# 删除不需要的分支（远程）
git push origin --delete feature
git push origin --delete test

# 回到 master
git checkout master
```

---

## 三、8个人的分支创建

```bash
# 每个人基于 dev 创建自己的分支
git checkout dev

git checkout -b p1-backend-core      # P1 的分支
git checkout -b p2-backend-ai        # P2 的分支
git checkout -b p3-backend-pipeline  # P3 的分支
git checkout -b p4-tests-seed        # P4 的分支
git checkout -b p5-frontend-monitor  # P5 的分支
git checkout -b p6-frontend-workflow # P6 的分支
git checkout -b p7-frontend-infra    # P7 的分支
git checkout -b p8-docs-config       # P8 的分支

# 推送所有分支到远程
git push origin p1-backend-core p2-backend-ai p3-backend-pipeline \
                p4-tests-seed p5-frontend-monitor p6-frontend-workflow \
                p7-frontend-infra p8-docs-config
```

---

## 四、工作流程（每日）

### 每个人每天做的事

```bash
# 1. 早上：切到自己的分支
git checkout p1-backend-core

# 2. 写代码... 写代码... 写代码...

# 3. 提交
git add .
git commit -m "P1: 完成数据库模型定义"

# 4. 推送到远程（备份到云端）
git push origin p1-backend-core
```

### 每天结束时（组长做）

```bash
# 1. 切到 dev 分支
git checkout dev

# 2. 拉取最新代码
git pull origin dev

# 3. 依次合并每个人的分支（解决了冲突才合并）
git merge p1-backend-core
git merge p2-backend-ai
# ... 依次合并

# 4. 如果有冲突，找到对应的人一起解决

# 5. 推送到远程
git push origin dev

# 6. 验证能跑通
# 启动后端 + 前端，看看有没有报错
```

---

## 五、完整流程示意图

```
第0天：组长把基础代码推到 dev
        ↓
第1天：每人从 dev 创建自己的分支，开始写代码
        ↓
每天18:00：组长把所有人的分支合并到 dev
        ↓
第N天：dev 版本稳定
        ↓
组长把 dev 合并到 master → 发布演示版
        ↓
继续迭代：回到第1天
```

---

## 六、实际操作命令

### 第一阶段：组长初始化（只做一次）

```bash
cd G:\code\code_vscode\软件开发能力\feng

# 确保在 master
git checkout master

# 把 fengdiao-pHM 的全部代码复制过来
cp -r ../fengdiao-pHM/* .
# 注意：不要复制 node_modules、.db、__pycache__、dist

# 把基础代码推到 master（初始版）
git add .
git commit -m "初始版本：风调预顺PHM系统基础框架"
git push origin master

# dev 分支从 master 分出来
git checkout -b dev
git push origin dev

# 创建8个个人分支
git checkout dev
for branch in p1-backend-core p2-backend-ai p3-backend-pipeline \
              p4-tests-seed p5-frontend-monitor p6-frontend-workflow \
              p7-frontend-infra p8-docs-config; do
    git checkout -b $branch
    git push origin $branch
    git checkout dev
done

echo "初始化完成！"
```

### 第二阶段：每个人开始工作

**P1 举例（其他人照抄，换分支名就行）**

```bash
# 第一天：把分支拉到本地
cd G:\code\code_vscode\软件开发能力\feng
git fetch origin
git checkout -b p1-backend-core origin/p1-backend-core

# 开始写代码...（把分配给你的文件写好）
# ... 

# 提交
git add backend/app/models/__init__.py backend/app/schemas/__init__.py ...
git commit -m "P1: 完成数据库模型和Schema定义"

# 推送
git push origin p1-backend-core
```

### 第三阶段：每日集成（组长操作）

```bash
cd G:\code\code_vscode\软件开发能力\feng

# 切到 dev
git checkout dev
git pull origin dev

# 合并 P1
git merge p1-backend-core
# 如果有冲突，解决冲突后：
# git add . && git commit -m "解决P1合并冲突"

# 合并 P2
git merge p2-backend-ai

# ... 全部8个人合并完

# 验证：跑一下
# 终端1: conda activate phm && cd backend && python -m uvicorn app.main:app --port 8000
# 终端2: cd frontend && npx vite --port 5173
# 打开 http://localhost:5173 看看有没有问题

# 没问题就推送
git push origin dev

# 如果 dev 很稳定，合并到 master
git checkout master
git merge dev
git push origin master
```

---

## 七、分支功能对照

| 分支名 | 负责内容 | 文件范围 |
|--------|----------|----------|
| `p1-backend-core` | 后端核心 | models/schemas/config/db/main/security/requirements |
| `p2-backend-ai` | 后端AI层 | ai/qwen/settings/personnel/diagnosis/prediction/workorders |
| `p3-backend-pipeline` | 数据管道 | 6个pipeline/turbines/health_index/geojson/download_era5 |
| `p4-tests-seed` | 测试+种子 | seed_data/test_api/test_pipeline/conftest |
| `p5-frontend-monitor` | 前端监控 | Dashboard/Detail/Diagnosis/Login/Map/Layout/Filter/ErrorBoundary |
| `p6-frontend-workflow` | 前端工单 | WorkOrder/Settings/Prediction/CopilotFAB/AIPanel |
| `p7-frontend-infra` | 前端基础设施 | types/api/authStore/App/main/global.css/config文件 |
| `p8-docs-config` | 文档+配置 | README/设计文档/demo_server/.env/.gitignore |

---

## 八、日常时间线

```
08:00  每人拉取最新 dev → 合并到自己的分支 → 开始工作
       git checkout p1-backend-core
       git merge dev    ← 把别人昨天的改动同步过来

08:00-17:00  写代码、提交、推送（只推自己的分支）

17:00  组长收集所有人分支，准备合并
       
17:30  组长逐个合并到 dev
       有冲突 → 叫当事人一起解决
       
18:00  验证 dev 能跑通
       能跑 → 推送 dev
       不能跑 → 修好再推送
       
18:30  如果 dev 稳定 → 合并到 master → 推送 master
       不稳定 → 明天继续修
```

---

## 九、常见问题处理

### 问题1：合并冲突了怎么办？

```bash
# 组长合并时出现冲突：
git merge p1-backend-core
# CONFLICT! 某个文件冲突了

# 1. 看哪些文件冲突
git status

# 2. 找到写这个文件的人（P1和P2），一起看代码
# 3. 编辑冲突文件，删掉 >>> === <<< 标记，保留正确的代码
# 4. 保存后
git add 冲突文件名
git commit -m "解决P1和P2的合并冲突"

# 5. 继续合并其他人
```

### 问题2：某个人没完成怎么办？

```bash
# 不要合并未完成的分支
# 跳过这个人的合并，其他人照常合并
# 等他完成了再单独合并
```

### 问题3：dev 被搞坏了怎么办？

```bash
# 回退到上一次正常的状态
git checkout dev
git reset --hard HEAD~1   # 回退一次合并
# 或者
git log --oneline          # 找到上次正常的commit
git reset --hard abc123    # 回退到指定commit
git push -f origin dev     # 强制推送（谨慎使用）
```

### 问题4：不小心改错了文件？

```bash
# 丢弃所有未提交的改动
git checkout -- .

# 只丢弃某个文件
git checkout -- 文件名

# 回退最后一次commit（保留改动）
git reset --soft HEAD~1
```

---

## 十、.gitignore 确认清单

确保以下内容不会上传到Git：

```
node_modules/      ← 前端依赖，npm install 就有了
__pycache__/       ← Python缓存
*.db               ← 数据库文件
*.pyc              ← Python编译文件
.env               ← 环境变量（含密钥！）
dist/              ← 前端构建产物
.pytest_cache/     ← 测试缓存
```

---

## 十一、快速参考卡片

```bash
# 每人每天
git checkout 我的分支
git merge dev              # 同步最新代码
# ... 写代码 ...
git add . && git commit -m "做了什么" && git push

# 组长每天
git checkout dev
git merge p1 p2 p3 ... p8  # 合并所有人
# 验证能跑
git push

# 组长每周
git checkout master
git merge dev
git push
```

---

> **一句话总结**：每人一个分支写代码 → 组长每天合并到dev验证 → dev稳了推到master发布。分支名字就是 `p1` 到 `p8`。
