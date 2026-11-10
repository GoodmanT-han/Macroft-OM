# CNN、BBC、G1 每日新闻简报

在 Windows 上解压整个文件夹，再双击 `start.cmd`。如果下载的是整个 GitHub 仓库，先进入解压后的 `daily-news-digest` 子文件夹。程序会抓取圣保罗当天发布的报道，生成 `reports/YYYY-MM-DD.html` 并尝试在浏览器打开。窗口会保留运行结果和简报位置，按任意键即可关闭。再次运行会把当天新发现的报道合入同一份简报。保留 `reports/archive.sqlite3` 即可保留已经抓取到的记录。

## 单独安装和运行

启动器可以使用本机 Codex 自带的 Python。若使用系统 Python，须安装 [Python 3.10 或更新版本](https://www.python.org/downloads/windows/)。首次运行时，启动器会在需要时将依赖安装到程序文件夹的 `.venv` 中。

也可以在解压后的文件夹中用以下命令手动运行。在 Windows 上可以把命令中的 `python` 换成 `py -3`。

```powershell
python -m pip install -r requirements.txt
python news_digest.py --open
```

默认最多展示 40 条，可用 `--limit 80` 调整。用 `--date YYYY-MM-DD` 可以从本地档案重新生成指定日期的简报。用 `--output 路径` 可以同时更改简报和档案目录。

## 每天自动生成

在 Windows「任务计划程序」中新建每日任务，选择你希望的运行时间。操作选择「启动程序」，设置如下。

| 字段 | 填写内容 |
| --- | --- |
| 程序或脚本 | `cmd.exe` |
| 添加参数 | `/d /c ""C:\你的解压路径\start.cmd" --scheduled"` |

把示例路径替换为实际路径，保留双引号。`--scheduled` 模式只生成文件。若想覆盖全天，可在触发器中设置每小时重复运行一次，持续一天。栏目只保留最近一批条目，白天多次抓取可以减少遗漏。电脑须在计划运行时能够联网。

## 收录和排序

- CNN 读取[新闻站点地图](https://www.cnn.com/sitemap/news.xml)。BBC 读取[头条](https://feeds.bbci.co.uk/news/rss.xml)、国际、商业和健康 RSS。G1 读取[最新](https://g1.globo.com/rss/g1/)、国际、经济、健康和教育 RSS。
- 通过栏目和英文、葡语关键词标注民生、经济、地缘政治及国际关系。一条新闻可以有多个主题。页面保留原文标题和原文链接。
- 标题明确注明快讯的报道优先，其次是滚动直播、BBC 头条 RSS 的前五条。其他报道按发布时间倒序。新闻按原始发布日期归档。
- 同一家媒体的重复链接会合并，各家对同一事件的报道会分别显示。入口异常会显示在「来源状态」中，之前抓取到的报道仍可查看。

主题识别依靠规则，可能漏掉标题或简介里缺少相关线索的报道。日报覆盖程序运行时已被新闻源收录的内容。
