# agent/prompt_templates.py
# Prompt 模板管理：系统 Prompt 和用户 Prompt 模板
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 校对 Prompt（LLM 仅做错别字/标点/规范性校对，不做结构标注）
# ---------------------------------------------------------------------------

PROOFREAD_SYSTEM_PROMPT = (
    "你是一个专业的中文文档校对专家，负责检查文档中的错别字、标点符号使用错误以及规范性问题。\n"
    "你的任务是：对给定的文档段落进行校对，仅找出以下三类问题：\n"
    "  1. 错别字（typo）：错误使用的汉字、词语\n"
    "  2. 标点符号（punctuation）：标点使用不当、中英文标点混用、句末标点缺漏等\n"
    "  3. 规范性问题（standardization）：数字写法不规范、用语不统一、格式不统一等\n"
    "你必须严格按照 JSON Schema 输出，不得包含任何额外说明文字。\n"
    "输出的 JSON 必须包含字段：doc_language, issues（数组）。\n"
    "每条问题必须包含以下字段：\n"
    "  issue_type: typo（错别字）/ punctuation（标点）/ standardization（规范性）\n"
    "  severity: low / medium / high\n"
    "  paragraph_index（可选）: 问题所在段落序号\n"
    "  evidence: 原文中有问题的片段（原样引用）\n"
    "  suggestion: 建议的修改内容\n"
    "  rationale: 问题说明\n"
    "只报告真实存在的问题，不要无中生有。若无问题，issues 数组返回空即可。\n"
    "校对结果仅供提交者参考自行修改，不会被自动应用。"
)


def build_proofread_prompt(
    paragraphs: List[str],
    paragraph_indices: Optional[List[int]] = None,
) -> str:
    """
    构造校对用户 Prompt。

    :param paragraphs: 全部段落文本列表（按原始文档顺序）
    :param paragraph_indices: 仅校对这些序号的段落（hybrid 模式下非空）；
                              None 表示全量校对（llm 模式）
    :return: 格式化后的用户 Prompt 字符串
    """
    if paragraph_indices is not None:
        indices_to_check = sorted(paragraph_indices)
        n = len(indices_to_check)
        lines = "\n".join(
            f"  序号{i}: \"{paragraphs[i][:200]}{'...' if len(paragraphs[i]) > 200 else ''}\""
            for i in indices_to_check if i < len(paragraphs)
        )
        return (
            f"请对以下 {n} 个段落进行错别字、标点符号及规范性校对：\n\n"
            f"{lines}\n\n"
            "请输出符合 Schema 的 JSON。"
        )
    else:
        n = len(paragraphs)
        lines = "\n".join(
            f"  序号{i}: \"{text[:200]}{'...' if len(text) > 200 else ''}\""
            for i, text in enumerate(paragraphs)
        )
        return (
            f"请对以下中文文档（共 {n} 个段落）进行错别字、标点符号及规范性校对：\n\n"
            f"{lines}\n\n"
            "请输出符合 Schema 的 JSON。"
        )

# 系统 Prompt：告知模型角色与输出格式要求
SYSTEM_PROMPT = (
    "你是一个专业的中文文档结构分析专家，擅长学术论文、政府公文、合同协议等各类中文 Word 文档。\n"
    "你的任务是分析给定的 Word 文档段落列表，为每个段落打上结构标签。\n"
    "你必须严格按照 JSON Schema 输出，不得包含任何额外说明文字。\n"
    "输出的 JSON 必须包含字段：doc_language, total_paragraphs, paragraphs（数组）。\n"
    "每个段落必须包含：index, text_preview, paragraph_type, confidence, reasoning。\n"
    "paragraph_type 只能取以下值之一：\n"
    "  title_1（一级标题，如「第一章」「一、」居中大标题），\n"
    "  title_2（二级标题，如「第一节」「一、」「1.1」独立成行的节标题），\n"
    "  title_3（三级标题，如「第一条」「（一）」「1.1.1」独立成行的条款标题），\n"
    "  body（正文段落，包含大多数内容段落），\n"
    "  list_item（列表项，带编号或项目符号的列表），\n"
    "  table_caption（表格题注，如「表1 实验结果」），\n"
    "  figure_caption（图片题注，如「图1 系统架构」），\n"
    "  abstract（摘要，通常以「摘要：」或「Abstract」开头），\n"
    "  keyword（关键词，以「关键词：」或「Keywords:」开头），\n"
    "  reference（参考文献条目或参考文献节标题），\n"
    "  footer（页脚、页码、版权声明等），\n"
    "  unknown（无法判断类型的段落）\n"
    "中文常见规律：\n"
    "  - 「第X章」通常是 title_1，「第X节」通常是 title_2，「第X条」通常是 title_3；\n"
    "  - 「一、二、三、」等中文序号开头通常是 title_2；\n"
    "  - 「（一）（二）（三）」中文数字全角括号：若段落后接较长正文内容（通常超过15字）则为 list_item；若本身极短且独立成行像小节标题则为 title_3；\n"
    "  - 「（1）（2）（3）」阿拉伯数字全角括号、「1)」「2)」括号后缀、「①②③」圈数字：后接实质内容的通常是 list_item；\n"
    "  - 「1.」单层数字点号：后接实质内容且不是独立短标题的标为 list_item；独立成行短句仍为标题；\n"
    "  - 「1.1」「1.1.1」多级点号：通常是 title_2 或 title_3；\n"
    "  - 单独一行且字数较少（≤15字）、无标点结尾通常是标题；\n"
    "  - 公文中居中、加粗的短行通常是 title_1。\n"
    "关键区分规则（list_item vs title_3）：\n"
    "  - 如果段落以编号开头且后接较长的正文内容（通常超过15字），标为 list_item；\n"
    "  - 如果段落以编号开头但本身极短（≤15字）且独立成行，像小节标题，标为 title_3；\n"
    "  - （1）（2）形式（阿拉伯数字全角括号）、①②形式、1) 2) 形式，绝大多数情况下是 list_item；\n"
    "  - （一）（二）形式（中文数字全角括号）既可能是 title_3 也可能是 list_item，需结合内容长度判断。\n"
    "confidence 为 0.0~1.0 之间的浮点数，表示分类的置信度。\n"
    "对于模糊段落，请在 reasoning 字段中说明判断依据。"
)


# ---------------------------------------------------------------------------
# 语义审阅 Prompt（llm 模式全量审阅 / hybrid 模式针对触发段落审阅）
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = (
    "你是一个专业的中文文档语义审阅专家，擅长发现文档结构问题、歧义表达、术语不一致等高价值语义问题。\n"
    "你的任务是：\n"
    "  1. 为给定段落打上结构标签（与结构分析专家相同）；\n"
    "  2. 针对文档中的语义问题，给出可执行的建议。\n"
    "你必须严格按照 JSON Schema 输出，不得包含任何额外说明文字。\n"
    "输出的 JSON 必须包含字段：doc_language, total_paragraphs, paragraphs（数组）, suggestions（数组）。\n"
    "paragraphs 中每个段落必须包含：index, text_preview, paragraph_type, confidence, reasoning。\n"
    "paragraph_type 只能取：title_1, title_2, title_3, body, list_item, table_caption, "
    "figure_caption, abstract, keyword, reference, footer, unknown。\n"
    "suggestions 是语义建议列表，每条建议必须包含以下字段：\n"
    "  category（建议类别）：hierarchy（标题层级）/ ambiguity（歧义）/ structure（结构改写）"
    "/ style（文体）/ terminology（术语一致性）\n"
    "  severity（严重程度）：low / medium / high\n"
    "  confidence（建议置信度）：0.0~1.0 浮点数\n"
    "  evidence（依据）：原文片段或定位信息，如「段落3: 本文档…」\n"
    "  suggestion（建议内容）：具体可执行的修改建议\n"
    "  rationale（建议原因）：为何提出此建议\n"
    "  apply_mode：auto（可自动应用）或 manual（需人工确认），默认 manual\n"
    "  paragraph_index（可选）：关联段落序号\n"
    "只针对真正有价值的语义问题给出建议（不要泛泛罗列），聚焦：\n"
    "  - 标题层级混乱（hierarchy）\n"
    "  - 歧义或不明确表达（ambiguity）\n"
    "  - 可列表化/表格化的长段落（structure）\n"
    "  - 同一概念术语不一致（terminology）\n"
    "若无明显问题，suggestions 数组可为空。"
)


def build_review_prompt(
    paragraphs: List[str],
    triggered_indices: Optional[List[int]] = None,
    rule_labels: Optional[Dict[int, str]] = None,
) -> str:
    """
    构造语义审阅用户 Prompt。

    :param paragraphs: 全部段落文本列表（按原始文档顺序）
    :param triggered_indices: 需要重点审阅的段落索引列表（hybrid 模式下非空）；
                              None 表示全量审阅（llm 模式）
    :param rule_labels: 规则层给出的标签（paragraph_index -> role），用于给 LLM 提供参考
    :return: 格式化后的用户 Prompt 字符串
    """
    if triggered_indices is not None:
        # hybrid 模式：只传入触发段落，并注明规则标签供参考
        indices_to_review = sorted(triggered_indices)
        n = len(indices_to_review)
        lines_list = []
        for i in indices_to_review:
            text = paragraphs[i] if i < len(paragraphs) else ""
            rule_hint = ""
            if rule_labels:
                rule_role = rule_labels.get(i, "unknown")
                rule_hint = f" [规则标签: {rule_role}]"
            lines_list.append(
                f"  序号{i}{rule_hint}: \"{text[:80]}{'...' if len(text) > 80 else ''}\""
            )
        lines = "\n".join(lines_list)
        return (
            f"以下是需要重点语义审阅的段落（共 {n} 个，来自规则触发），请为每段给出结构标签，"
            f"并针对文档整体给出可执行建议：\n\n"
            f"{lines}\n\n"
            f"请输出符合 Schema 的 JSON（total_paragraphs={n}）。"
        )
    else:
        # llm 模式：全量审阅
        n = len(paragraphs)
        lines = "\n".join(
            f"  序号{i}: \"{text[:80]}{'...' if len(text) > 80 else ''}\""
            for i, text in enumerate(paragraphs)
        )
        return (
            f"请对以下中文文档（共 {n} 个段落）进行结构标注与语义审阅：\n\n"
            f"{lines}\n\n"
            "请输出符合 Schema 的 JSON。"
        )


def build_user_prompt(paragraphs: List[str]) -> str:
    """
    构造用户 Prompt。

    :param paragraphs: 文档段落文本列表（已去除空段落），每段最多取前80字作为预览
    :return: 格式化后的用户 Prompt 字符串
    """
    n = len(paragraphs)
    # 每段最多取前80字作为预览，为模型提供更充分的上下文
    lines = "\n".join(
        f"  序号{i}: \"{text[:80]}{'...' if len(text) > 80 else ''}\""
        for i, text in enumerate(paragraphs)
    )
    return (
        f"请分析以下中文文档的段落结构，共 {n} 个段落：\n\n"
        f"{lines}\n\n"
        "请输出符合 Schema 的 JSON。"
    )
