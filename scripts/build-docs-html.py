#!/usr/bin/env python3
"""
build-docs-html.py - 把所有 SIRO 文件合成單一 HTML 方便閱讀

執行：
    python scripts/build-docs-html.py
    # 產生 SIRO.html 在專案根目錄
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from html import escape

import markdown
from markdown.extensions.toc import TocExtension
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

# ==================== 設定 ====================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
OUTPUT = ROOT / "SIRO.html"

# 要包含的文件（按顯示順序）
DOCS: list[tuple[str, str, str]] = [
    # (path, title, category)
    ("README.md", "入口與總覽", "Overview"),
    ("LIVE2D_AI_AGENT_OS_PLAN.md", "主計畫書 (v2.0)", "Planning"),
    ("docs/ARCHITECTURE.md", "系統架構", "Architecture"),
    ("docs/SETUP.md", "安裝設定指南", "Architecture"),
    ("docs/DECISIONS.md", "設計決策紀錄 (20 個 ADR)", "Architecture"),
    ("docs/API.md", "API 參考手冊", "Architecture"),
    ("docs/SECURITY.md", "安全性設計", "Architecture"),
    ("docs/DEPLOYMENT.md", "部署指南", "Architecture"),
    ("docs/TESTING.md", "測試策略", "Architecture"),
    ("docs/CONTRIBUTING.md", "貢獻指南（給 AI 助手）", "Architecture"),
    ("hardware/README.md", "硬體總覽", "Hardware"),
    ("hardware/detection.md", "硬體偵測", "Hardware"),
    ("hardware/audio.md", "音訊設定", "Hardware"),
    ("hardware/video.md", "視訊設定", "Hardware"),
    ("hardware/assembly.md", "組裝改裝", "Hardware"),
    ("os/README.md", "Linux 系統設定總覽", "OS Layer"),
    ("os/install/README.md", "安裝腳本規劃", "OS Layer"),
    ("os/systemd/README.md", "systemd 服務", "OS Layer"),
    ("os/kiosk/README.md", "Kiosk 模式", "OS Layer"),
    ("os/security/README.md", "安全政策", "OS Layer"),
    ("os/network/README.md", "網路設定", "OS Layer"),
    ("os/audio/README.md", "OS 音訊", "OS Layer"),
    ("os/video/README.md", "OS 視訊", "OS Layer"),
    ("os/power/README.md", "電源管理", "OS Layer"),
    ("os/backup/README.md", "備份還原", "OS Layer"),
    ("os/monitoring/README.md", "監控", "OS Layer"),
    ("os-runtime/README.md", "Rust 系統層", "Rust Runtime"),
    ("bridge/README.md", "Python Bridge", "Python Bridge"),
    ("agent/README.md", "Hermes 整合", "Agent"),
    ("agent/notes/hermes_api_surface.md", "Hermes API 介面筆記", "Agent"),
    ("unity/README.md", "Unity 客戶端", "Unity"),
]

# ==================== Markdown 處理 ====================

md = markdown.Markdown(
    extensions=[
        "fenced_code",
        "tables",
        "sane_lists",
        "nl2br",
        "codehilite",
        TocExtension(toc_depth="2-3", anchorlink=False),
    ],
    extension_configs={
        "codehilite": {
            "css_class": "codehilite",
            "use_pygments": True,
        }
    },
)


def render_markdown(text: str) -> tuple[str, str]:
    """渲染 markdown 並回傳 (HTML, TOC)"""
    md.reset()
    html = md.convert(text)
    toc = md.toc
    return html, toc


# ==================== Pygments 主題 ====================

PYGMENTS_CSS = HtmlFormatter(style="github-dark").get_style_defs(".codehilite")


# ==================== HTML 樣板 ====================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SIRO - Live2D AI Agent 專屬作業系統</title>
<style>
/* ============================================
   Reset & Base
   ============================================ */
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei",
                 "Helvetica Neue", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.7;
    color: #1a1a1a;
    background: #fafafa;
    -webkit-font-smoothing: antialiased;
}
* { scroll-behavior: smooth; }

/* ============================================
   Layout
   ============================================ */
.layout {
    display: flex;
    min-height: 100vh;
}
.sidebar {
    width: 280px;
    flex-shrink: 0;
    background: #1e293b;
    color: #e2e8f0;
    padding: 20px 0;
    position: fixed;
    height: 100vh;
    overflow-y: auto;
    box-shadow: 2px 0 8px rgba(0,0,0,0.1);
}
.main {
    margin-left: 280px;
    padding: 40px 60px 80px;
    max-width: 1100px;
    flex: 1;
}
@media (max-width: 900px) {
    .sidebar { position: relative; width: 100%; height: auto; }
    .main { margin-left: 0; padding: 20px; }
    .layout { flex-direction: column; }
}

/* ============================================
   Sidebar
   ============================================ */
.sidebar-header {
    padding: 0 20px 20px;
    border-bottom: 1px solid #334155;
    margin-bottom: 20px;
}
.sidebar-header h1 {
    margin: 0 0 8px;
    font-size: 20px;
    color: #f1f5f9;
    font-weight: 700;
}
.sidebar-header p {
    margin: 0;
    font-size: 12px;
    color: #94a3b8;
}
.sidebar-search {
    margin: 0 20px 16px;
    padding: 8px 12px;
    background: #334155;
    border: 1px solid #475569;
    border-radius: 6px;
    color: #f1f5f9;
    font-size: 14px;
    width: calc(100% - 40px);
}
.sidebar-search:focus {
    outline: none;
    border-color: #60a5fa;
    background: #475569;
}
.sidebar-nav {
    list-style: none;
    padding: 0;
    margin: 0;
}
.nav-category {
    padding: 12px 20px 4px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
    font-weight: 600;
    margin-top: 12px;
}
.nav-item {
    list-style: none;
}
.nav-item a {
    display: block;
    padding: 6px 20px 6px 28px;
    color: #cbd5e1;
    text-decoration: none;
    font-size: 13px;
    border-left: 2px solid transparent;
    transition: all 0.15s;
}
.nav-item a:hover {
    background: #334155;
    color: #f1f5f9;
    border-left-color: #60a5fa;
}
.nav-item a.active {
    background: #334155;
    color: #60a5fa;
    border-left-color: #60a5fa;
}

/* ============================================
   Typography
   ============================================ */
h1, h2, h3, h4, h5, h6 {
    line-height: 1.3;
    margin: 2em 0 0.8em;
    font-weight: 700;
    color: #0f172a;
}
h1 { font-size: 2.2em; padding-bottom: 0.4em; border-bottom: 2px solid #e2e8f0; margin-top: 0; }
h2 { font-size: 1.6em; padding-bottom: 0.3em; border-bottom: 1px solid #e2e8f0; }
h3 { font-size: 1.3em; }
h4 { font-size: 1.1em; color: #475569; }
h5 { font-size: 1em; color: #64748b; }
h6 { font-size: 0.9em; color: #94a3b8; }
p { margin: 0 0 1em; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: #0f172a; font-weight: 600; }
em { color: #475569; }
ul, ol { margin: 0 0 1em; padding-left: 2em; }
li { margin: 0.3em 0; }
hr { border: 0; border-top: 1px solid #e2e8f0; margin: 2em 0; }
blockquote {
    border-left: 4px solid #3b82f6;
    background: #f1f5f9;
    margin: 1em 0;
    padding: 0.8em 1.2em;
    color: #334155;
    border-radius: 0 6px 6px 0;
}
blockquote p:last-child { margin-bottom: 0; }
blockquote p:first-child { margin-top: 0; }

/* ============================================
   Code
   ============================================ */
code {
    font-family: "SFMono-Regular", "JetBrains Mono", Consolas, "Courier New", monospace;
    font-size: 0.9em;
    background: #f1f5f9;
    color: #be185d;
    padding: 0.15em 0.4em;
    border-radius: 4px;
}
pre {
    background: #0f172a;
    color: #e2e8f0;
    padding: 1em 1.2em;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.85em;
    line-height: 1.5;
    margin: 1em 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
pre code {
    background: none;
    color: inherit;
    padding: 0;
    font-size: inherit;
    border-radius: 0;
}

/* ============================================
   Tables
   ============================================ */
table {
    border-collapse: collapse;
    margin: 1em 0;
    width: 100%;
    font-size: 0.95em;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    border-radius: 6px;
    overflow: hidden;
}
thead { background: #f1f5f9; }
th {
    text-align: left;
    padding: 10px 14px;
    font-weight: 600;
    color: #0f172a;
    border-bottom: 2px solid #cbd5e1;
}
td {
    padding: 10px 14px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
}
tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #f8fafc; }

/* ============================================
   Task list
   ============================================ */
.task-list { list-style: none; padding-left: 1.5em; }
.task-list li { position: relative; }
.task-list input[type="checkbox"] {
    margin-right: 0.5em;
    transform: scale(1.1);
}

/* ============================================
   Section dividers
   ============================================ */
.doc-section {
    margin-bottom: 4em;
    padding-bottom: 3em;
    border-bottom: 2px dashed #e2e8f0;
}
.doc-section:last-child {
    border-bottom: 0;
}
.doc-title {
    background: linear-gradient(135deg, #1e3a8a, #3b82f6);
    color: white;
    padding: 16px 24px;
    border-radius: 8px;
    margin: 0 0 2em;
    box-shadow: 0 4px 12px rgba(59,130,246,0.2);
}
.doc-title h2 {
    margin: 0 0 4px;
    color: white;
    border: 0;
    padding: 0;
    font-size: 1.5em;
}
.doc-title .doc-meta {
    font-size: 0.85em;
    opacity: 0.85;
    margin: 0;
}

/* ============================================
   Pygments syntax highlighting
   ============================================ */
{pygments_css}

/* ============================================
   Tooltips, back-to-top
   ============================================ */
.back-to-top {
    position: fixed;
    bottom: 30px;
    right: 30px;
    width: 44px;
    height: 44px;
    background: #3b82f6;
    color: white;
    border-radius: 50%;
    text-align: center;
    line-height: 44px;
    font-size: 20px;
    text-decoration: none;
    box-shadow: 0 4px 12px rgba(59,130,246,0.3);
    opacity: 0;
    transition: opacity 0.2s;
    z-index: 100;
}
.back-to-top.visible { opacity: 1; }

/* ============================================
   Print
   ============================================ */
@media print {
    .sidebar, .back-to-top { display: none; }
    .main { margin-left: 0; padding: 0; max-width: 100%; }
    .doc-title { background: none; color: black; box-shadow: none; border: 2px solid black; }
    .doc-title h2 { color: black; }
    h1, h2, h3 { page-break-after: avoid; }
    pre, table { page-break-inside: avoid; }
    .doc-section { page-break-before: always; }
}

/* ============================================
   Mermaid
   ============================================ */
.mermaid {
    background: white;
    padding: 1em;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin: 1em 0;
    text-align: center;
}

/* ============================================
   Anchors
   ============================================ */
h1 .headerlink, h2 .headerlink, h3 .headerlink, h4 .headerlink, h5 .headerlink, h6 .headerlink {
    opacity: 0;
    margin-left: 0.5em;
    text-decoration: none;
    font-size: 0.8em;
    color: #94a3b8;
    transition: opacity 0.1s;
}
h1:hover .headerlink, h2:hover .headerlink, h3:hover .headerlink,
h4:hover .headerlink, h5:hover .headerlink, h6:hover .headerlink {
    opacity: 1;
}
h1 .headerlink:hover, h2 .headerlink:hover, h3 .headerlink:hover { color: #3b82f6; }
</style>
</head>
<body>
<div class="layout">
    <nav class="sidebar">
        <div class="sidebar-header">
            <h1>SIRO</h1>
            <p>Live2D AI Agent 作業系統 v2.0</p>
        </div>
        <input type="text" class="sidebar-search" placeholder="搜尋文件..." id="search">
        <ul class="sidebar-nav" id="nav">
            {nav_html}
        </ul>
    </nav>
    <main class="main">
        <div class="doc-section" id="top">
            <div class="doc-title">
                <h2>SIRO 文件總覽</h2>
                <p class="doc-meta">產出時間：{generated_at} · {doc_count} 個文件 · 6 個 Phase</p>
            </div>
            <p>這是 SIRO 專案的完整文件集。所有 Markdown 來源檔案在 <code>SIRO/</code> 專案根目錄下，本檔由 <code>scripts/build-docs-html.py</code> 自動產生。</p>

            <h2>快速導覽</h2>
            <ul>
                <li><strong>剛開始</strong>：先看 <a href="#readme">入口</a>、<a href="#plan">主計畫書</a>、<a href="#setup">安裝設定</a></li>
                <li><strong>要理解架構</strong>：<a href="#architecture">系統架構</a>、<a href="#decisions">設計決策</a></li>
                <li><strong>要寫程式</strong>：<a href="#contributing">貢獻指南</a>、<a href="#api">API 參考</a>、<a href="#testing">測試</a></li>
                <li><strong>要部署</strong>：<a href="#deployment">部署指南</a>、<a href="#hardware">硬體</a>、<a href="#security">安全</a></li>
                <li><strong>硬體相關</strong>：<a href="#hardware">硬體總覽</a>、<a href="#hardware-audio">音訊</a>、<a href="#hardware-video">視訊</a></li>
            </ul>

            <h2>6 個開發階段</h2>
            <table>
                <thead>
                    <tr><th>Phase</th><th>重點</th><th>狀態</th><th>預估</th></tr>
                </thead>
                <tbody>
                    <tr><td>Phase 0</td><td>規劃設計、建立結構</td><td>✅ 完成</td><td>已</td></tr>
                    <tr><td>Phase 1</td><td>Python AI 整合（Hermes + 文字對話 + Live2D 表情）</td><td>待開始</td><td>2-3 週</td></tr>
                    <tr><td>Phase 2</td><td>Live2D 視覺強化（待機動作、過渡）</td><td>待開始</td><td>1-2 週</td></tr>
                    <tr><td>Phase 3</td><td>Rust 系統層（supervisor、gRPC、硬體抽象）</td><td>待開始</td><td>3-4 週</td></tr>
                    <tr><td>Phase 4</td><td>Linux 客製化（Ubuntu Server 24.04 LTS 雙系統）</td><td>待開始</td><td>2-3 週</td></tr>
                    <tr><td>Phase 5</td><td>硬體整合（音訊、視訊、kiosk 模式）</td><td>待開始</td><td>1-2 週</td></tr>
                    <tr><td>Phase 6</td><td>部署與營運（Packer image、OTA、備份）</td><td>待開始</td><td>2-3 週</td></tr>
                </tbody>
            </table>
        </div>

        {sections_html}
    </main>
</div>

<a href="#top" class="back-to-top" id="back-to-top" title="回到頂部">↑</a>

<!-- Mermaid for diagrams (loaded from CDN) -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({
    startOnLoad: true,
    theme: 'default',
    securityLevel: 'loose',
    flowchart: { curve: 'basis' }
});
</script>

<script>
// Back to top
const btn = document.getElementById('back-to-top');
window.addEventListener('scroll', () => {
    btn.classList.toggle('visible', window.scrollY > 400);
});

// Active link highlight
const navLinks = document.querySelectorAll('.nav-item a');
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            navLinks.forEach(l => l.classList.remove('active'));
            const id = entry.target.id;
            const link = document.querySelector(`.nav-item a[href="#${id}"]`);
            if (link) link.classList.add('active');
        }
    });
}, { rootMargin: '-20% 0px -70% 0px' });

document.querySelectorAll('.doc-section, [id="top"]').forEach(s => observer.observe(s));

// Simple search
const search = document.getElementById('search');
search.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    navLinks.forEach(link => {
        const text = link.textContent.toLowerCase();
        const match = !q || text.includes(q);
        link.parentElement.style.display = match ? '' : 'none';
    });
});
</script>
</body>
</html>
"""


# ==================== 產生導覽列 ====================

def build_nav() -> str:
    """產生側邊導覽列 HTML"""
    out: list[str] = []
    current_category = None
    for path, title, category in DOCS:
        if category != current_category:
            if current_category is not None:
                out.append("</ul>")
            out.append(f'<li class="nav-category">{category}</li>')
            out.append('<ul class="sidebar-nav" style="margin: 0; padding: 0;">')
            current_category = category
        anchor = path_to_anchor(path)
        out.append(
            f'<li class="nav-item"><a href="#{anchor}">{title}</a></li>'
        )
    if current_category is not None:
        out.append("</ul>")
    return "\n".join(out)


def path_to_anchor(path: str) -> str:
    """把檔案路徑轉成 HTML anchor ID"""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", path.replace("/", "-").replace(".md", "").lower())


# ==================== 讀取 + 渲染 ====================

def read_doc(path: str) -> str:
    """讀 markdown 檔，回傳內容（如果檔案不存在回傳 placeholder）"""
    full_path = ROOT / path
    if not full_path.exists():
        return f"> ⚠️ 檔案不存在: `{path}`\n"
    return full_path.read_text(encoding="utf-8")


def build_sections() -> str:
    """把所有文件轉成 HTML 並組合成 sections"""
    out: list[str] = []
    for path, title, category in DOCS:
        anchor = path_to_anchor(path)
        text = read_doc(path)
        body_html, _ = render_markdown(text)

        # 移除文檔自己的 H1（避免重複）
        body_html = re.sub(
            r"<h1>.*?</h1>",
            "",
            body_html,
            count=1,
            flags=re.DOTALL,
        )

        out.append(f'''
        <div class="doc-section" id="{anchor}">
            <div class="doc-title">
                <h2>{escape(title)}</h2>
                <p class="doc-meta">📄 {path}</p>
            </div>
            {body_html}
        </div>
        ''')
    return "\n".join(out)


# ==================== 主程式 ====================

def main() -> None:
    nav_html = build_nav()
    sections_html = build_sections()

    # 用簡單的 replace 取代 .format()，避免 CSS 內的 {} 衝突
    html = HTML_TEMPLATE
    html = html.replace("{nav_html}", nav_html)
    html = html.replace("{sections_html}", sections_html)
    html = html.replace("{generated_at}", datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("{doc_count}", str(len(DOCS)))
    html = html.replace("{pygments_css}", PYGMENTS_CSS)

    OUTPUT.write_text(html, encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"[OK]  Generated: {OUTPUT}")
    print(f"  Size:    {size_kb:.1f} KB")
    print(f"  Files:   {len(DOCS)} documents")
    print(f"\nOpen in browser: file:///{OUTPUT.as_posix()}")


if __name__ == "__main__":
    main()
