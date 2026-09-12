# Memento 备份说明

记忆库（SQLite）的备份、归档与恢复。命令为 `memento-backup`，直接操作数据库文件，
**不经 MCP、不经 Web UI**，在 VPS 上手动执行或由 systemd timer 定时拉起。

## 目录结构

备份根目录由 `MEMENTO_BACKUP_DIR` 指定，默认 `<数据库所在目录>/backups/`
（VPS 上即 `/opt/memento/backups/`）：

```
backups/
├── snapshots/        # 每 2 天一份的快照，自动清理超过保留期的旧文件
├── archive/          # 每 15 天一份的长期归档，永不自动删除
└── restore-safety/   # 每次恢复前，当前库自动备份到这里
```

文件名格式：`memento-YYYYMMDD-HHMMSS.db`（东八区时间）。

## 配置（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEMENTO_BACKUP_DIR` | `<数据库所在目录>/backups` | 备份根目录 |
| `MEMENTO_SNAPSHOT_KEEP_DAYS` | `10` | 快照保留天数，0 = 不自动清理 |

## 手动操作（VPS 上）

```bash
cd /opt/memento

# 手动快照（顺带清理过期快照）
.venv/bin/memento-backup snapshot

# 手动长期归档
.venv/bin/memento-backup archive

# 恢复：整体替换（清空现有记忆，写入快照内容）
.venv/bin/memento-backup restore backups/snapshots/memento-YYYYMMDD-HHMMSS.db

# 恢复：合并模式（只导入当前库里不存在的条目，现有数据一律不动）
.venv/bin/memento-backup restore backups/archive/memento-YYYYMMDD-HHMMSS.db --merge
```

恢复前会自动把当前库备份到 `restore-safety/`，路径会打印出来；恢复错了可从那里找回。

## 定时任务（systemd timer）

首次部署或重装备份功能后执行一次：

```bash
cd /opt/memento
sudo cp deploy/memento-backup-snapshot.service deploy/memento-backup-snapshot.timer /etc/systemd/system/
sudo cp deploy/memento-backup-archive.service  deploy/memento-backup-archive.timer  /etc/systemd/system/
sudo systemctl enable --now memento-backup-snapshot.timer memento-backup-archive.timer
```

- 快照 timer：每 2 天触发一次，做新快照并清理超过 `MEMENTO_SNAPSHOT_KEEP_DAYS` 天的旧快照
- 归档 timer：每 15 天触发一次，写入 `archive/`，不删除
- `Persistent=true`：VPS 关机期间错过的触发，开机后补跑

查看定时任务状态：

```bash
systemctl list-timers memento-backup-*     # 下次触发时间
journalctl -u memento-backup-snapshot.service -n 20   # 快照执行日志
journalctl -u memento-backup-archive.service -n 20    # 归档执行日志
```

手动立即跑一次（测试用）：

```bash
sudo systemctl start memento-backup-snapshot.service
sudo systemctl start memento-backup-archive.service
```

## 常见问题

**怎么挑恢复用的快照？** 按文件名日期选，或先看内容再决定：

```bash
sqlite3 backups/snapshots/memento-xxx.db "SELECT id, updated_at, content FROM memories ORDER BY updated_at DESC LIMIT 20;"
```

**replace 还是 --merge？**
- 库损坏 / 误删大量记忆 → 用 replace，整库回到快照时刻
- 想把旧库内容并进来、又不想动现在的数据 → 用 `--merge`，只补缺失条目

**备份/恢复时要停服务吗？** 不用。备份用 SQLite 在线备份 API，
恢复是单事务写入，服务运行中即可执行。

**磁盘满了怎么办？** 归档永不自动删除，需要人工清理：

```bash
ls -lh /opt/memento/backups/archive/    # 按日期挑要删的
```

**整机故障怎么办？** 备份和目标库在同一台机器上，救不了磁盘/整机故障。
建议定期把 `backups/archive/` rsync 到别处，例如：

```bash
rsync -a /opt/memento/backups/archive/ user@其他机器:/path/to/memento-archive/
```
