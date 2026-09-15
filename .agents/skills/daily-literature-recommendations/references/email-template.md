# Gmail delivery template

Use a natural email voice. The authenticated account is the sender; the inbox shows `delivery.sender_name` (pass it as `--from`), and the closing signature matches it.

## Subject

```text
[每日文献推荐] <display_name> | <YYYY-MM-DD HH:mm>
```

## Body

```text
你好，

我按照“<research_question>”完成了本次文献检索与筛选。

本次检索：<searched> 篇候选，去重后 <deduplicated> 篇，深入评估 <read> 篇，最终推荐 <selected> 篇。
检索范围：<date/source summary>

1. <Title>
作者：<authors>
年份与来源：<year>, <venue/status>
DOI/链接：<canonical link>
与任务的关系：<direct explanation>
研究问题：<question>
方法与数据：<method/data>
关键结果：<evidence-bounded findings>
推荐理由：<why this deserves user attention>
局限或阅读提醒：<limitations/caveats>
阅读深度：<全文 / 主要章节或片段 / 仅摘要>

<repeat>

说明：本邮件是有界检索结果，不代表系统综述或穷尽性覆盖。未能访问全文的条目已明确标注，没有按全文阅读处理。

祝好，
daily-lit
```

If no paper reaches the threshold or every relevant paper was recommended previously, still send one short zero-result message for this invocation with search counts, scope, main exclusion reasons, and any source/access failures. Do not manufacture recommendations to reach the requested count.

Use concise prose; do not paste long abstracts or copyrighted passages. Include stable links and canonical publication status when known.
