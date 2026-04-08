# zentao-daily-cli

平台项目每日日报 CLI 工具，从禅道拉取版本进度、延期情况、Bug 状态，生成结构化日报。

可独立使用，也可作为 [Claude Code](https://claude.ai/code) Skill 集成到 AI agent 中。

## 安装

克隆仓库并安装依赖：

```bash
git clone https://github.com/sssguoqiang-art/zentao-daily-skill.git
cd zentao-daily-skill
pip install requests
```

## 配置

首次使用，运行交互式配置：

```bash
python scripts/daily_report.py setup
```

按提示输入禅道地址、账号、密码、项目 ID 即可。配置保存在 `~/.config/zentao-daily/config.json`（权限 600）。

也可以通过环境变量配置（优先级高于配置文件，适合 CI/多人共用场景）：

```bash
export ZENTAO_URL="https://zentao.example.com:8088"
export ZENTAO_ACCOUNT="your_account"
export ZENTAO_PASSWORD="your_password"
export ZENTAO_PROJECT="10"
```

## 使用

```bash
# 生成 Markdown 日报（写入本地文件）
python scripts/daily_report.py

# 输出结构化 JSON（供 Claude Code Skill 使用）
python scripts/daily_report.py --output json

# 重新配置连接信息
python scripts/daily_report.py setup
```

## Claude Code 集成

安装 CLI 并完成配置后，将 Skill 安装到 Claude Code：

```bash
npx skills add https://github.com/sssguoqiang-art/zentao-daily-skill -g
```

重启 Claude Code 后，直接对话即可：

```
帮我生成今天的日报
用老板视角给我一个简洁版本
PHP2 部门今天的情况怎样
```

Claude Code 会自动调用 CLI 拉取禅道数据，并按照指定视角输出报告。

## License

MIT
