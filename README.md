# Memento

一个简单的 MCP 记忆库 + Web UI。SQLite 后端，时间戳为东八区。

## 功能

- **MCP 工具**
  - `pull`：拉取记忆，置顶在前、短期在后（注入格式：`[ab 2026-09-07] 内容`，id 为随机两位字母）
  - `write`：创建一条新记忆，自动附加时间戳
  - `edit`：按 id（pull 返回行首的两位字母）修改记忆，自动刷新时间戳
  - `pin`：置顶/解除置顶某条记忆（unpin=true 解除；置顶上限 15 条）
  - `search`：单关键词搜索记忆（默认最多 10 条，按相关性排序，可限定 since/until 日期范围）
- **Web UI**：查看全部记忆（置顶在前）、翻页浏览（每页 10 条）、新增、编辑；密码登录（服务端校验）。
  新增/编辑/删除均为乐观更新——先本地生效、后台串行同步，高延迟网络下操作不阻塞；
  同步失败自动回滚为服务端状态并提示

## 环境要求

- Python >= 3.11（开发于 3.14，服务器 3.11 已确认兼容）
- 无其他系统依赖（SQLite 为 Python 标准库自带）

## 安装

```bash
python3.11 -m venv .venv
# Linux: source .venv/bin/activate    Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env   # 按需修改，见下
```

`.env` 配置项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEMENTO_DB_PATH` | `./memento.db` | SQLite 文件路径 |
| `MEMENTO_HOST` | `127.0.0.1` | Web UI 监听地址 |
| `MEMENTO_PORT` | `8765` | Web UI 端口 |
| `MEMENTO_PASSWORD` | 空 | **Web UI 登录密码**；留空 = 免登录（仅限本机使用） |
| `MEMENTO_MCP_HOST` | `127.0.0.1` | MCP HTTP 端点监听地址 |
| `MEMENTO_MCP_PORT` | `8766` | MCP HTTP 端点端口 |

## 本机使用

### MCP（stdio 模式，由客户端本地拉起）

```bash
# Claude Code：
claude mcp add memento -- /path/to/Memento/.venv/bin/memento-mcp

# Kimi Code：在配置的 mcpServers 中加一条
#   "memento": { "command": "/path/to/Memento/.venv/bin/memento-mcp" }
```

注意把客户端的 `cwd` 设为项目目录（或在 `.env` 里用绝对路径），确保读得到 `.env`。

### Web UI

```bash
memento-web    # 或 python -m memento.web.app
```

浏览器打开 `http://127.0.0.1:8765`。

## 设置密码

在 `.env` 中配置：

```
MEMENTO_PASSWORD=你的密码
```

重启 `memento-web` 生效。之后打开 Web UI 会先要求输入密码：服务端校验通过后下发
HttpOnly Cookie（30 天有效），前端不做任何密码校验。修改密码会使所有已登录会话失效。
留空则不启用鉴权，**只在监听 127.0.0.1 的本机场景下这么做**。

## VPS 部署（纯 Python + systemd + nginx）

以下假设部署到 `/opt/memento`，域名为 `memento.example.com`。

### 1. 安装

```bash
git clone <repo> /opt/memento   # 或 scp 上传
cd /opt/memento
python3.11 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

编辑 `.env`：设置 `MEMENTO_PASSWORD`，并用绝对路径设置
`MEMENTO_DB_PATH=/opt/memento/memento.db`。

### 2. systemd 常驻（Web UI + MCP HTTP 端点各一个）

```bash
sudo cp deploy/memento-web.service.example /etc/systemd/system/memento-web.service
sudo cp deploy/memento-mcp.service.example /etc/systemd/system/memento-mcp.service
sudo systemctl enable --now memento-web memento-mcp
```

两个服务都只监听 `127.0.0.1`，不直接对外。

### 3. HTTPS 证书（Let's Encrypt）

```bash
sudo certbot --nginx -d memento.example.com
```

certbot 自动签发并续期证书。

### 4. nginx 反代与鉴权

参考 `deploy/nginx.conf.example`：

- `location /` → 反代到 Web UI（`127.0.0.1:8765`），鉴权由应用的 `MEMENTO_PASSWORD` 完成
- `location /mcp` → 反代到 MCP HTTP 端点（`127.0.0.1:8766`），**nginx 校验
  `Authorization: Bearer <token>`**，token 用 `openssl rand -hex 32` 生成一个长随机串，
  填进 nginx 配置里

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/memento
# 编辑：域名、token；然后启用并重载
sudo nginx -t && sudo systemctl reload nginx
```

### 5. MCP 客户端接入远程端点

以 HTTP 方式连接，URL 为 `https://memento.example.com/mcp`，并带上 token：

```json
{
  "mcpServers": {
    "memento": {
      "type": "http",
      "url": "https://memento.example.com/mcp",
      "headers": { "Authorization": "Bearer 你的token" }
    }
  }
}
```

### 6. 升级

```bash
cd /opt/memento
git pull
sudo systemctl restart memento-web memento-mcp
```

数据库结构在启动时自动迁移，无需手工处理；无新增依赖时不用重装 pip 包。

## 冒烟测试

```bash
.venv/bin/python scripts/smoke_mcp.py        # stdio 模式
.venv/bin/python scripts/smoke_mcp_http.py   # HTTP 模式
```
