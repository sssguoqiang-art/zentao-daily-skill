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
python daily_report.py setup
```

按提示输入禅道地址、账号、密码、项目 ID 即可。配置保存在 `~/.config/zentao-daily/config.json`（权限 600）。

账号密码也可以通过环境变量覆盖（优先级高于配置文件，适合 CI/多人共用场景）：

```bash
export ZENTAO_ACCOUNT="your_account"
export ZENTAO_PASSWORD="your_password"
```

禅道地址和项目 ID 仍从配置文件读取。

## 使用

```bash
# 生成 Markdown 日报（写入本地文件）
python daily_report.py

# 输出结构化 JSON（供 Claude Code Skill 使用）
python daily_report.py --output json

# 重新配置连接信息
python daily_report.py setup
```

## Claude Code 集成

安装 CLI 并完成配置后，将 Skill 安装到 Claude Code：

```bash
npx skills add https://github.com/sssguoqiang-art/zentao-daily-skill -g
```

重启 Claude Code 后，直接对话即可：

```
帮我生成今天的日报
PHP2组今天的情况怎样
有几个线上Bug
```

Claude Code 会自动调用 CLI 拉取禅道数据，并按照指定视角输出报告。

## License

MIT
