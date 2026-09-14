# Memento

一个简单的 MCP 记忆库 + Web UI。SQLite 后端，时间戳为东八区。

## 功能

- **MCP 工具**
  - `pull`：拉取记忆，首行为库元信息（`── 库 2026-09-10 起 · 共 27 条 · 本次注入 7 条 ──`），其后置顶记忆在前、短期记忆在后（注入格式：`[a3f 2026-09-07] 内容`，id 为随机字母数字，长度由 `ID_LENGTH` 控制，默认 3）
  - `write`：创建一条新记忆，自动附加时间戳
  - `edit`：按 id（pull 返回行首的字母编号）修改记忆，自动刷新时间戳
  - `pin`：置顶/解除置顶某条记忆（unpin=true 解除；置顶上限 15 条）
  - `search`：单关键词搜索记忆（默认最多 10 条，按相关性排序，可限定 since/until 日期范围）
- **Web UI**：查看全部记忆（置顶单独成区、默认折叠可展开）、翻页浏览（每页 10 条）、新增、编辑；密码登录（服务端校验）。
  新增/编辑/删除均为乐观更新——先本地生效、后台串行同步，高延迟网络下操作不阻塞；
  同步失败自动回滚为服务端状态并提示
- **备份**：`memento-backup` 命令 + systemd timer。快照每 2 天一次、自动清理 10 天前的旧快照；
  长期归档每 15 天一次、不自动删除；支持把快照恢复/合并回现有数据库；具体请看BACKUP.md

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
| `MEMENTO_BACKUP_DIR` | `<数据库所在目录>/backups` | 备份根目录（`snapshots/`、`archive/`、`restore-safety/`） |
| `MEMENTO_SNAPSHOT_KEEP_DAYS` | `10` | 快照保留天数，0 = 不自动清理 |

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

### 7. 定时备份（systemd timer）

`memento-backup` 命令提供三种操作，均直接操作 SQLite 文件，不经 MCP / Web UI：

- `snapshot`：备份当前库到 `snapshots/`，并自动删除超过 `MEMENTO_SNAPSHOT_KEEP_DAYS` 天的旧快照（默认 10 天）
- `archive`：备份当前库到 `archive/`，**不自动删除**（长期归档）
- `restore <快照文件>`：把快照导入现有数据库，恢复前会自动把当前库备份到 `restore-safety/`

部署两个 timer（快照每 2 天一次，归档每 15 天一次）：

```bash
sudo cp deploy/memento-backup-snapshot.{service,timer}.example /etc/systemd/system/
sudo cp deploy/memento-backup-archive.{service,timer}.example /etc/systemd/system/
# 去掉 .example 后缀后：
sudo systemctl enable --now memento-backup-snapshot.timer memento-backup-archive.timer
systemctl list-timers memento-backup-*   # 确认下次触发时间
```

VPS 上手动操作（手动备份/恢复）：

```bash
cd /opt/memento
.venv/bin/memento-backup snapshot                    # 手动快照（顺带清理过期快照）
.venv/bin/memento-backup archive                     # 手动长期归档
.venv/bin/memento-backup restore backups/snapshots/memento-20260911-100000.db   # 整体替换恢复
.venv/bin/memento-backup restore backups/archive/memento-xxx.db --merge         # 只导入缺失的条目
```

恢复说明：

- 默认整体替换：清空 `memories` 后写入快照内容，适合回滚/迁移；
- `--merge`：只导入当前库里不存在的条目，现有数据一律不动，适合把旧库内容并进来；
- 两种模式都会在覆盖前把当前库备份到 `restore-safety/`，恢复路径写错了也能找回来。
- 备份用的是 SQLite 在线备份 API，服务运行中也能安全执行；恢复（replace/merge）是单事务写入，无需停服务。

完整说明（目录结构、定时任务排错、恢复选型等）见项目根目录的 `BACKUP.md`。

## 测试

```bash
.venv/bin/python scripts/smoke_mcp.py        # stdio 模式
.venv/bin/python scripts/smoke_mcp_http.py   # HTTP 模式
```

---

## 一些话

个人自用项目，随时可能灵机一动突然加了点啥进去。想加自己想要的功能的话，比较建议自己fork走

做这个东西是想到，对于ai助手来说，记忆文件如果无限堆叠下去，不仅费用增加，还容易让模型分不清主次、导致回复质量降低。市面上不同的总结、摘要方案什么的，其实也很多。想了下也可以试试少即是多，直接只全量注入最近的几条（这个可以自己根据需求改改具体数字），随着使用、较早的记忆也会自动被挤出窗口，这样也是动态短期记忆了；毕竟日常聊天的场景，虽然ai会忘记之前的事，但是其实人类也会。

那些比较之前的记忆，重要的可以pin起来，不那么重要的配合搜索功能也能捞出来点。

感谢读到这里~许可证是**MIT**。

