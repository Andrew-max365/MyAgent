# ui/app.py
from __future__ import annotations

import sys
import os

# 运行时路径补丁，供直接执行（python ui/app.py）时使用。
# 推荐方式：在项目根目录执行 `pip install -e .` 后，使用 `python -m ui.app` 启动。
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import json
from typing import Dict, Optional

import streamlit as st
import matplotlib.pyplot as plt

# ✅ 用 Agent 层（更符合比赛叙事：Perception→Reasoning→Action→Explanation）
# 你之前运行的是 python -m agent.Structura_agent ...
from agent.Structura_agent import run_doc_agent_bytes, _safe_get
from config import LLM_MODE

LABEL_MODES = ["rule", "llm", "hybrid"]


def _format_pct(x: Optional[float]) -> str:
    if x is None:
        return "-"
    try:
        return f"{x*100:.0f}%"
    except Exception:
        return "-"


def plot_role_counts(counts: Dict[str, int], title: str):
    # matplotlib 画图（不指定颜色，按要求）
    roles = ["h1", "h2", "h3", "body"]
    values = [int(counts.get(r, 0)) for r in roles]

    fig = plt.figure()
    plt.bar(roles, values)
    plt.title(title)
    plt.xlabel("role")
    plt.ylabel("count")
    st.pyplot(fig)


st.set_page_config(page_title="StructuraAgent - 文档质量检查与自动排版", layout="wide")

st.title("📄Structura:文档结构认知增强智能体")
st.caption("上传 Word 文档（.docx），智能体会进行结构诊断与自动修复，并输出可解释报告与排版后的文档。")

with st.sidebar:
    st.header("⚙️ 配置")
    spec_path = st.text_input("spec 路径", value="specs/default.yaml")
    label_mode = st.selectbox(
        "标签模式",
        options=LABEL_MODES,
        index=LABEL_MODES.index(LLM_MODE) if LLM_MODE in LABEL_MODES else LABEL_MODES.index("hybrid"),
        help="rule=纯规则；llm=仅大模型（失败自动回退规则）；hybrid=大模型+规则补全",
    )
    st.markdown("---")
    st.markdown("**说明**：当前 UI 直接调用本地 Agent（不走 API），适合比赛 Demo。")

uploaded = st.file_uploader("上传 Word 文档（.docx）", type=["docx"])

if uploaded is None:
    st.info("请先上传一个 .docx 文件，Structura会显示诊断报告、结构统计，并提供下载。")
    st.stop()

# 运行按钮（避免每次交互都重跑）
col_run, col_hint = st.columns([1, 3])
with col_run:
    run = st.button("🚀 运行 StructuraAgent", type="primary")
with col_hint:
    st.write(f"文件：`{uploaded.name}`（{uploaded.size} bytes）")

if not run:
    st.stop()

with st.spinner("StructuraAgent 正在分析并修复文档..."):
    input_bytes = uploaded.read()
    out_bytes, agent_res = run_doc_agent_bytes(
        input_bytes,
        spec_path=spec_path,
        filename_hint=uploaded.name,
        label_mode=label_mode,
    )

report = agent_res.report

# -------------------------
# 顶部：关键指标卡片
# -------------------------
meta_before = _safe_get(report, "meta", "paragraphs_before", default=0)
meta_after = _safe_get(report, "meta", "paragraphs_after", default=0)

created = _safe_get(report, "actions", "split_body_new_paragraphs_created", default=0)
affected = _safe_get(report, "actions", "split_body_original_paragraphs_affected", default=0)
max_lines = _safe_get(report, "actions", "split_body_max_lines_in_one_paragraph", default=0)

coverage_rate = _safe_get(report, "labels", "coverage", "coverage_rate", default=None)
mismatch = _safe_get(report, "labels", "consistency", "mismatched", default=0)
warns = report.get("warnings") or []

kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
kpi1.metric("段落（Before）", meta_before)
kpi2.metric("段落（After）", meta_after)
kpi3.metric("拆分新增段落", created)
kpi4.metric("受影响原段落", affected)
kpi5.metric("单段最大行数", max_lines)
kpi6.metric("标签覆盖率", _format_pct(coverage_rate))

st.markdown("### 🧠 Agent Summary")
st.success(agent_res.summary)

# -------------------------
# 中部：结构分布图 + 诊断信息
# -------------------------
left, right = st.columns([1.2, 1.0])

with left:
    st.markdown("### 📊 结构角色分布")
    formatted_counts = _safe_get(report, "formatted", "counts", default={}) or {}
    labels_counts = _safe_get(report, "labels", "counts", default={}) or {}

    tab1, tab2 = st.tabs(["格式化后（formatted.counts）", "原始标签（labels.counts）"])
    with tab1:
        plot_role_counts(formatted_counts, "formatted.counts")
        st.caption("表示最终输出文档的段落角色数量。")
    with tab2:
        plot_role_counts(labels_counts, "labels.counts")
        st.caption("表示原始段落（拆分前）的标签角色数量。")

with right:
    st.markdown("### 🧾 诊断与一致性")
    st.write(f"**标签一致性冲突（mismatch）**：{mismatch} 条")
    plan = report.get("plan_executed") or []
    if plan:
        st.write("**执行计划（plan_executed）**：")
        st.code("\n".join(plan), language="text")

    st.markdown("### ⚠️ Warnings")
    if warns:
        for w in warns:
            st.warning(w)
    else:
        st.info("无警告。")

# -------------------------
# LLM 校对结果（如有）
# -------------------------
llm_proofread = report.get("llm_proofread") or {}
proofread_issues = llm_proofread.get("issues") or []
if proofread_issues:
    st.markdown("---")
    st.markdown("## 🔍 LLM 校对结果（请提交者自行修改）")
    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    type_label = {"typo": "错别字", "punctuation": "标点符号", "standardization": "规范性"}
    for issue in proofread_issues:
        icon = severity_icon.get(issue.get("severity", "low"), "⚪")
        itype = type_label.get(issue.get("issue_type", ""), issue.get("issue_type", ""))
        para_info = f"（段落 {issue['paragraph_index']}）" if issue.get("paragraph_index") is not None else ""
        st.markdown(
            f"{icon} **{itype}**{para_info}：`{issue.get('evidence', '')}` → {issue.get('suggestion', '')}  \n"
            f"<small>{issue.get('rationale', '')}</small>",
            unsafe_allow_html=True,
        )

# -------------------------
# 底部：下载与原始 report
# -------------------------
st.markdown("---")
st.markdown("## 📥 下载产物")

c1, c2, c3 = st.columns([1, 1, 2])

with c1:
    st.download_button(
        label="⬇️ 下载 output.docx",
        data=out_bytes,
        file_name="output.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )

with c2:
    report_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        label="⬇️ 下载 report.json",
        data=report_bytes,
        file_name="output.report.json",
        mime="application/json",
        use_container_width=True,
    )

with c3:
    with st.expander("查看 report.json（原始）", expanded=False):
        st.json(report)
