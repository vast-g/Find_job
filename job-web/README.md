# job-web —— 求职招聘系统 Web 管理控制台

## 1. 这块前端解决什么问题

这个求职项目原本只有**微信小程序**一个客户端。小程序的问题在于：演示时必须用手机、要扫码、要开发者工具，
面试现场很不方便；而且它看不到系统的全貌（没有管理端视角、没有数据分布、没有爬虫入口）。

`job-web` 补的就是这块空白：一个**浏览器打开即用**的运营/演示控制台，它做四件事：

1. **看见系统全貌** —— 用户/岗位/投递/企业四个总量指标 + 岗位状态、城市分布、薪资区间三张图，
   一屏就能说清"这个系统里有什么"。
2. **管理数据** —— 岗位分页检索与上下架、投递记录、企业列表，用管理端接口（`token` 头）。
3. **演示 AI 能力** —— AI 对话（含意图、耗时、引用来源展示）与岗位匹配五部分分析。
   AI 要跑 ReAct + RAG，**实测 20~120 秒**，所以重点做了"正在分析"的进度反馈。
4. **演示数据获取能力** —— 一键手动爬虫，把"系统能自己从公开招聘网站抓岗位"这件事可视化。

技术上的硬约束是两条，它们决定了整个代码形态：

- **零外部依赖**：部署机器外网不通，任何站外静态资源都会导致整页白屏 → 不引公共静态库，
  图表用**手写 SVG**，HTTP 用原生 `fetch`。
- **零构建链**：不要 npm / webpack / vite → 就是三个 `.js` + 一个 `.css`，nginx 当静态站点托管。
  用普通 `<script>` 而非 ES Module，是为了连直接双击 `index.html`（`file://`）都能跑。

## 2. 目录结构

```
job-web/
├─ index.html          单页骨架：顶部栏 + 6 个视图容器（所有数据块都留了固定容器）
├─ css/
│  └─ app.css          深色大屏主题（CSS 变量集中管理状态色）
├─ js/
│  ├─ api.js           接口层：统一响应/双 token/超时/错误分类/分页归一化
│  ├─ charts.js        手写 SVG 图表：环形图、横向条形图、柱状图、折线图、进度环
│  └─ app.js           页面逻辑：视图路由、表格、分页、AI 对话与分析、爬虫进度
└─ deploy/             另一个 agent 产出的 nginx/启动脚本（非本前端交付物，见第 7 节）
```

脚本加载顺序有依赖，不要调换：`api.js` → `charts.js` → `app.js`。

## 3. 快速开始

### 3.1 只看界面（不需要后端）

```bash
cd job-web
python -m http.server 8099
# 浏览器打开 http://127.0.0.1:8099
```

后端没起时页面**不会白屏**：统计卡片显示「—」，图表区、表格区显示错误卡片并带"排查建议"和重试按钮，
两个健康灯变红。这是刻意设计的——见第 6 节。

### 3.2 正式部署（推荐，也是唯一能让接口通的方式）

**必须先说清楚为什么不能用浏览器直连 `:8080`：**

Java 后端**没有配置任何 CORS**（`WebMvcConfiguration` 里没有 `addCorsMappings`）。
而管理端请求要带自定义头 `token`，会触发浏览器预检（OPTIONS），后端不会回 CORS 响应头，
于是浏览器直接拦截请求。**这不是代码 bug，是必须靠同源代理绕开的部署约束。**

所以正确做法是 nginx 同源托管前端 + 反代 `/api/`：

```nginx
server {
    listen 81;
    root   C:/Users/Lenovo/Desktop/Find_job/job-web;
    index  index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        # ⚠️ 末尾这个 / 是关键：它把 /api/ 前缀替换掉，
        #    使 /api/user/stats → 127.0.0.1:8080/user/stats
        #    如果写成 proxy_pass http://127.0.0.1:8080/api/; 则后端收到 /api/user/stats，
        #    而本后端没有 /api 这个 context-path，会全部 404。
        proxy_pass http://127.0.0.1:8080/;

        # ⚠️ 超时必须放大：nginx 默认 proxy_read_timeout 只有 60s，
        #    而手动爬虫要 1~3 分钟、AI 要 20~120 秒，不改就是 504。
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;          # AI 长回答尽早回传
    }
}
```

之后浏览器访问 nginx 端口，页面上的「接口地址」保持默认 `/api` 即可。
若你的代理没有 `/api` 前缀，把该输入框清空（表示同源根路径）再点「应用」。

## 4. 接口依赖

统一响应结构是 `{ code, msg, data }`，**`code === 1` 才是成功**（不是常见的 0）。
`api.js` 里用常量 `SUCCESS_CODE = 1` 固定住这一点。

### 4.1 鉴权：两套请求头

| 通道 | 请求头 | 说明 |
|---|---|---|
| 管理端 `/admin/**` | `token` | 登录 `POST /api/admin/employee/login` 后从 `data.token` 拿 |
| 用户端 `/user/**` | `authentication` | 微信 `code` 换 token；**只有部分路径免鉴权** |

依据是 `application.yml`：`admin-token-name: token`、`user-token-name: authentication`。
`api.js` 按请求路径自动挑选用哪个头，不无脑全带（避免"我明明登录了为什么还是 401"）。

### 4.2 实际用到的接口

| 用途 | 方法与路径 | 鉴权 | 前端超时 |
|---|---|---|---|
| 员工登录 | `POST /admin/employee/login` | 免 | 15s |
| 岗位分页 | `GET /admin/job/page?page&pageSize&title&name&status` | `token` | 15s |
| 岗位上下架 | `POST /admin/job/status/{status}?id=` | `token` | 15s |
| 企业分页 | `GET /admin/company/page?page&pageSize&name` | `token` | 15s |
| 企业列表 | `GET /admin/company/list` | `token` | 15s |
| 分类列表 | `GET /admin/category/list` | `token` | 15s |
| 投递分页 | `GET /admin/application/page?page&pageSize&status` | `token` | 15s |
| 公告列表 | `GET /admin/announcement/list` | `token` | 15s |
| 手动爬虫 | `POST /admin/crawl/run` | `token` | **300s** |
| 首页统计 | `GET /user/stats` | 免 | 15s |
| 岗位列表 | `GET /user/job/list?name&categoryId` | 免 | 15s |
| 岗位详情 | `GET /user/job/{id}` | 免 | 15s |
| 企业详情 | `GET /user/company/{id}` | 免 | 15s |
| AI 对话 | `POST /user/agent/chat` | **`authentication`** | **180s** |
| 对话历史 | `GET /user/agent/history?sessionId=` | **`authentication`** | 15s |
| AI 反馈 | `POST /user/agent/feedback` | **`authentication`** | 15s |
| 岗位分析 | `POST /user/agent/analyze` | **`authentication`** | **180s** |

路径写法说明：控制器真实映射是 `/user/**` 与 `/admin/**`（`application.yml` 没有
`server.servlet.context-path`，小程序也是直接拼 `/user/job/list`）。
前端默认前缀 `/api`，靠 nginx 的 `proxy_pass .../` 把前缀去掉——这样"任务书要求的 `/api` 前缀"
和"后端真实无前缀"两边都能对上。

### 4.3 分页字段兼容

后端 `PageResult` 是 `{ total, records }`。前端 `normalizePage()` 额外兼容
`rows / list / items` 与 `totalCount / count / totalElements`，取不到就退回数组长度，
所以后端换字段名不会直接把表格打空。

## 5. 与任务书不一致的地方（都已在代码里兼容，请以本节为准）

写代码前逐文件核对了后端源码，发现任务书有 6 处与当前代码不符。**前端按"能跑通"处理，而不是照抄任务书**：

1. **AI 三个接口并非免鉴权。**
   `WebMvcConfiguration` 的 `excludePathPatterns` 只放行了 `/user/job/*`、`/user/company/*`、
   `/user/stats`、`/user/category/list` 等，**没有** `/user/agent/**`。
   所以 AI 接口必须带用户态 `authentication` 头，管理端 `token` 无效；
   而用户登录是微信 `code` 换 token，浏览器拿不到。
   → 前端提供了**「演示登录」按钮**（浏览器内 WebCrypto 本地签发，见第 10 节）来解掉这个死结，
   同时保留手工粘贴 token 的入口；401 时给出明确指引而不是转圈失败。**这是本项目最需要知道的一条。**

2. **`/user/stats` 不返回 `userCount` / `applicationCount`。**
   真实键名是 `companyCount / jobCount / announcementCount / applyTotal / applyProgress / applyRemind`。
   → 取不到的卡片显示「—」并标注"(接口未返回)"，**不拿 0 冒充**（0 会被误解成"真的没有用户"）。

3. **AI 的 `intent` / `latencyMs` / `source` / `stats` 到不了前端。**
   Python 端 `pipeline._result()` 确实产出了 `intent`、`latency_ms`、`stats`，
   但 Java 转发层 `AgentServiceImpl.chat()` 只回传 `sessionId / reply / sources / requestId`，其余被丢弃。
   → 前端按"有就显示、没有就显示未返回"处理：意图缺失时显示"意图：未返回"并附 tooltip 说明原因；
   耗时缺失时改用**前端实测耗时**并标注"前端计时"。想恢复完整字段，只需在 `AgentServiceImpl.chat()`
   里把 `source`/`intent`/`latency_ms` 也 `result.put(...)` 进去（改 Java，不在本次范围）。

4. **岗位分页的模糊查询字段是 `title`，不是 `name`。**
   `JobPageQueryDTO.title` + `JobMapper.xml` 的 `and j.title like ...`。
   → 前端同时发送 `title` 和 `name`（多发的会被 Spring 忽略），
   这样现在能搜到，将来后端改名也能搜到。

5. **投递状态常量类与数据库不一致。**
   `schema.sql` 列注释是 `1已投递 2已查看 3面试邀请 4已录用 5已拒绝`（与任务书一致，也是实际入库的语义），
   但 `ApplicationStatusConstant.java` 是另一套 7 值（`0待投递 2笔试 3面试 4长期无进展 5Offer 6已拒绝`）。
   → 前端以 schema 为准，同时把 `0` 和 `6` 也映射上，保证任何值都不会显示成空白。

6. **岗位 `status` 有三个值，不是两个。**
   实体注释与 schema 都是 `1在招 / 2已结束 / 0下架`。
   → 三种都做了彩色标签，筛选项也给了三个。

## 6. 关键设计取舍

- **错误分类而不是"请求失败"四个字。** `ApiError` 分 `network / timeout / unauthorized / http /
  business / parse` 六类，每类都带一句「怎么排查」。特别是 `parse` 类（返回的不是 JSON）——
  这几乎总是"nginx 把 `/api/` 请求兜到了 `index.html`"，提示里直接点出这一点。
- **永久可用的"接口自检"面板**（系统与爬虫页）。逐个真实请求所有端点并列出结果，
  部署后打不通时比逐个开 F12 快得多；`401` 和 `200` 的区别一眼可见。
- **Agent 健康灯是三态，不是两态。** 探针用 `/user/agent/history?sessionId=health`：
  `code===1` 绿灯；**`401` 黄灯**（能返回 401 说明请求已到 Java，链路是通的，只是缺用户 token）；
  网络失败才红灯。把 401 当红灯会误导人去重启后端。
- **AI 与爬虫都必须有秒表和阶段提示。** 20~120 秒和 1~3 分钟的接口，
  没有进度反馈用户一定会以为卡死并重复点击。爬虫的进度条用**不确定动画**而不是假百分比——
  后端没有进度接口，编一个百分比是骗人。
- **概览页只依赖免鉴权接口**（`/user/stats` + `/user/job/list`），
  所以**不登录也能演示**三张图，登录只是解锁管理表格。
- **时间解析不用 `new Date(str)`。** 后端 `JacksonObjectMapper` 固定输出
  `yyyy-MM-dd HH:mm:ss`，这不是 ISO 格式，Safari/iOS 上会解析失败，因此自己拆字段。
- **薪资格式化按"元"处理。** schema 注释是"月薪/元"，`JobCrawlerService` 抓取时也把 K/万
  统一乘成元，所以 `8000-12000` → `8-12K`；只在两值都缺时显示"面议"，
  单边缺失显示"8K 起"/"最高 12K"。
- **事件用委托而非逐个绑定。** 表格会被反复重绘，逐个 `addEventListener` 重绘后就失效了。

## 7. `deploy/` 目录说明

`deploy/` 里的 `nginx.conf`、`job.ps1`、`job.bat`、`mime.types` 是**另一个并行任务**产出的部署脚本，
不属于本前端交付物，本次没有改动它们。

⚠️ 但有一个必须转达的问题：`deploy/nginx.conf` 里写的是

```nginx
location /api/ { proxy_pass http://job_java/api/; }
```

`proxy_pass` 带 URI 时是**替换** location 前缀，所以 `/api/user/stats` 会被原样转发成
`/api/user/stats` → 后端 404（本后端没有 `/api` context-path）。
应改为 `proxy_pass http://job_java/;`（末尾一个斜杠）。

## 8. 已知限制（诚实清单）

1. **AI 功能依赖「演示登录」或手工 token。** 因为用户登录只有微信 `code` 换取一条路，
   浏览器无法自行完成。前端用 WebCrypto 在本地签一个演示 token 来解决（见第 10 节），
   但**这依赖"后端密钥就是仓库里的 itcast"这一前提**，所以生成后会立刻请求后端自检：
   自检通过才写入，不通过就明确报错并让你改用手工粘贴，不会让你拿着废 token 反复撞 401。
   ⚠️ **安全边界：前端持有签名密钥只适用于本地/内网演示**；生产必须由服务端签发。
2. **岗位"AI 分析"依赖当前用户已有简历。** 后端取不到默认简历会抛 `RESUME_NOT_FOUND`，
   前端只能把这句话翻译得更清楚，没法绕过。演示前请先用小程序创建一份简历。
3. **`/user/agent/analyze` 只认 `jobId`。** `AgentAnalyzeDTO` 只有这一个字段；
   任务书里的 `{ job, resume }` 会被后端忽略（前端仍一并发送以兼容未来版本）。
4. **爬虫没有真实进度。** 后端是同步接口，拿不到"已抓 3/10 页"，所以只能做用时计时 +
   阶段文案 + 不确定进度条。**且前端 5 分钟超时后不再等待，但后端可能仍在跑**，
   此时只能稍后刷新看结果。
5. **未做写入类操作。** 只有岗位上下架这一个写操作。新增/编辑岗位、企业、公告等
   任务书没要求，也没有对应界面。
6. **图表是"就地统计当前岗位列表"**，不是在数据库里做聚合。
   岗位量很大时（数万条）`/user/job/list` 全量返回会明显变慢——演示数据量下没问题，
   生产环境应该在后端加聚合接口。
7. **没有登录态持久化的服务端校验。** token 存在 localStorage，过期后第一次请求才 401，
   前端随后清 token 并提示重新登录（没有做定时续期）。
8. **未在真实浏览器里做过交互回归。** 验证方式见第 9 节（静态服务器 + 语法检查 + 无头 DOM 抓取 +
   接口全不可用时的渲染检查），**没有**覆盖真实点击流程与 AI 真链路（后端当前未运行）。

## 9. 自检方法

```bash
# 1) 语法
node --check js/api.js && node --check js/charts.js && node --check js/app.js

# 2) 零外链自查（应无任何输出）
grep -rniE "https?://|cdn" index.html css/ js/

# 3) 起静态服务器看页面
python -m http.server 8099
```

第 2 条正常应当**零命中**；`README.md` 里出现的 `http://127.0.0.1:8080` 只在 nginx 示例代码中，
是文档而非页面引用。

---

## 10. 演示登录：为什么要让前端自己签 token，以及那个坑

### 10.1 问题

`/user/agent/**` 需要用户态 JWT，而唯一的用户登录入口是微信 `code` 换 token —— 浏览器拿不到。
结果是"打开控制台想演示 AI，先撞一个 401"，演示价值直接归零。

### 10.2 做法

前端用浏览器内置 **WebCrypto**（`crypto.subtle`）本地签一个 HS256 的 JWT：

```
header  = {"alg":"HS256"}
payload = {"userId":1,"exp":<now+7200>}
key     = jjwt 宽松 Base64 解码(application.yml 里的 job.jwt.user-secret-key)
```

生成后**立刻请求 `/user/agent/history?sessionId=health` 自检**，通过才写入 sessionStorage。
界面上明确标注「仅供本地演示，密钥来自仓库配置，不可用于生产」。

### 10.3 踩过的坑：密钥不是"UTF-8 字节"，也不是标准 Base64

`JwtUtil.createJWT` 用的是 jjwt 0.9.1 的 `signWith(SignatureAlgorithm.HS256, String)`，
这个重载把字符串当 **Base64** 解码，**而且它的解码器只处理完整的 4 字符组，尾部直接丢弃**。

`"itcast"` 有 6 个字符，于是只用了前 4 个 `"itca"`：

| 密钥推导方式 | 字节数 | 后端是否接受 |
|---|---|---|
| UTF-8 直取 `itcast` | 6 字节 `697463617374` | ❌ 401 |
| 标准 Base64 解码 `itcast` | 4 字节 `8ad71ab2` | ❌ 401 |
| **jjwt 宽松解码（只取完整 4 字符组）** | **3 字节 `8ad71a`** | ✅ **200 / code=1** |

验证方法很直接：登录拿一个**真实 token**，用它字面量里的 `header.payload` 和候选密钥算 HMAC，
与真实签名段逐字节比对 —— 前两种都不匹配，第三种匹配。`js/api.js` 里的
`jjwtBase64Decode()` 就是这段逻辑，注释里写明了原因，免得后人再踩。

### 10.4 真实联调结果（实测记录）

后端当时在运行（`job-server-1.0-SNAPSHOT.jar`，端口 8080；Python Agent 端口 8000）：

| 验证项 | 结果 |
|---|---|
| 管理端登录 `admin/123456` | `code=1`，签发 103 字符 token |
| `GET /admin/job/page` | `total=756`，字段与表格列完全对应 |
| 岗位搜索 `title=工程` | `total=240` |
| 岗位搜索 `name=工程`（任务书写法） | `total=756` ← **未过滤，证明 `name` 被忽略** |
| `GET /admin/company/page` | `total=359` |
| `GET /admin/application/page` | `total=8` |
| `/admin/category/list`、`/admin/announcement/list`、`/admin/company/list` | `code=1`，返回**裸数组**（8 / 2 / 359 项） |
| `/user/job/list`、`/user/stats` | `code=1`（概览图表数据源） |
| 无 token 访问 `/admin/job/page` | HTTP 401（符合预期） |
| 无 token 访问 `/user/agent/history` | HTTP 401（证明必须带 `authentication`） |
| 自签用户 token → `/user/agent/history` | **HTTP 200 / code=1**（演示登录可行） |
| `POST /user/agent/chat` 真实调用 | **HTTP 200，耗时 20.4s**，返回完整推荐回答 |
| AI 响应实际字段 | `sources, requestId, sessionId, reply` ← **确认没有 `intent`/`latencyMs`/`stats`/`source`** |
| 页面经 nginx:81 渲染 | 岗位 756、企业 359、3 张 SVG 图、Java 灯绿、Agent 灯黄（缺用户 token） |
| 后端不可用时渲染 | 页面骨架完整、错误卡片带排查建议、健康灯红、**绝不白屏** |

实测还发现一个**不在我职责范围内**的现象：`GET /user/stats` 在免鉴权情况下偶尔返回
`applyTotal=8 / applyProgress=6`（正常应为 0，因为 `BaseContext.getCurrentId()` 为 null）。
这看起来是 `BaseContext` 的 ThreadLocal 在请求结束后没有清理，被线程池复用时串了值。
不影响本前端（卡片会照实显示后端返回的数字），但值得后端留意。

### 10.5 演示时的一个真实风险

Python Agent 有时会**在自己的内部超时后返回一句"抱歉，这个问题处理超时了"**，
而 HTTP 仍然是 `200 / code=1`。也就是说：接口成功 ≠ 答案有效。
前端会把这句话当普通回复展示（这是正确行为，前端无从判断内容质量）。
演示前建议先热一次链路，避免现场第一次请求就吃到 Agent 内部超时。
