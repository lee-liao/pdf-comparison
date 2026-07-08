"""HTML 差异报告生成

左右对照视图：使用表格布局保证两侧行高始终对齐；
支持 上一处/下一处 差异导航、文本搜索高亮、亮色/暗色主题。
"""

import html as html_mod
from string import Template

THEMES = {
    "light": {
        "bg": "#ffffff", "text": "#1f2328",
        "num_bg": "#f6f8fa", "num_text": "#656d76",
        "border": "#d0d7de", "header_bg": "#f6f8fa",
        "add_bg": "#dafbe1", "add_border": "#2da44e", "add_text": "#1a7f37",
        "del_bg": "#ffebe9", "del_border": "#cf222e", "del_text": "#cf222e",
        "mod_bg": "#fff8c5", "mod_border": "#d4a72c", "mod_text": "#9a6700",
        "add_word_bg": "#1a7f37", "del_word_bg": "#cf222e", "word_text": "#ffffff",
        "focus": "#0969da",
    },
    "dark": {
        "bg": "#0d1117", "text": "#c9d1d9",
        "num_bg": "#161b22", "num_text": "#484f58",
        "border": "#30363d", "header_bg": "#161b22",
        "add_bg": "#1c3a29", "add_border": "#2ea44f", "add_text": "#3fb950",
        "del_bg": "#3d1c1c", "del_border": "#f85149", "del_text": "#ff7b72",
        "mod_bg": "#3d3a00", "mod_border": "#d4a72c", "mod_text": "#e3b341",
        "add_word_bg": "#238636", "del_word_bg": "#da3633", "word_text": "#ffffff",
        "focus": "#58a6ff",
    },
}

_PAGE = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$title</title>
<style>
:root {
$css_vars
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Roboto, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5;
}
.container { max-width: 1600px; margin: 0 auto; padding: 16px; }
.header {
  background: var(--header-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;
  position: sticky; top: 8px; z-index: 10;
}
.header h1 { font-size: 16px; font-weight: 600; margin-bottom: 10px; word-break: break-all; }
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.stat-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.badge {
  display: inline-flex; padding: 2px 8px; border-radius: 12px;
  font-size: 12px; font-weight: 600; border: 1px solid;
}
.badge.added { background: var(--add-bg); color: var(--add-text); border-color: var(--add-border); }
.badge.deleted { background: var(--del-bg); color: var(--del-text); border-color: var(--del-border); }
.badge.changed { background: var(--mod-bg); color: var(--mod-text); border-color: var(--mod-border); }
.nav-group { display: flex; gap: 6px; align-items: center; margin-left: auto; }
.nav-btn {
  padding: 4px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--text); font-size: 13px; cursor: pointer;
}
.nav-btn:hover { border-color: var(--focus); color: var(--focus); }
.nav-counter { font-size: 12px; color: var(--num-text); min-width: 70px; text-align: center; }
.search-input {
  width: 220px; padding: 5px 10px; font-size: 13px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--text);
}
.diff-wrapper { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
table.diff-table {
  width: 100%; border-collapse: collapse; table-layout: fixed;
  font-family: "SFMono-Regular", Consolas, "Microsoft YaHei", monospace;
  font-size: 13px; line-height: 20px;
}
.diff-table th {
  background: var(--header-bg); padding: 8px 12px; font-size: 12px;
  text-align: left; border-bottom: 1px solid var(--border);
}
.diff-table td { border-bottom: 1px solid var(--border); vertical-align: top; }
.diff-table td.num {
  width: 46px; padding: 0 8px; text-align: right; user-select: none;
  color: var(--num-text); font-size: 12px; background: var(--num-bg);
  border-right: 1px solid var(--border);
}
.diff-table td.line {
  padding: 0 12px; white-space: pre-wrap; word-break: break-word;
}
.diff-table td.line + td.num { border-left: 1px solid var(--border); }
td.line.added { background: var(--add-bg); }
td.line.deleted { background: var(--del-bg); }
td.line.modified { background: var(--mod-bg); }
td.line.empty { background: var(--num-bg); }
.added-word {
  background: var(--add-word-bg); color: var(--word-text);
  padding: 1px 3px; border-radius: 3px; font-weight: 600;
}
.deleted-word {
  background: var(--del-word-bg); color: var(--word-text);
  padding: 1px 3px; border-radius: 3px; font-weight: 600; text-decoration: line-through;
}
tr.diff-current td.line { outline: 2px solid var(--focus); outline-offset: -2px; }
.search-highlight { background: #fffb8c; color: #1f2328; border-radius: 2px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>$title</h1>
    <div class="toolbar">
      <div class="stat-item"><span class="badge added">+$additions</span><span>新增</span></div>
      <div class="stat-item"><span class="badge deleted">-$deletions</span><span>删除</span></div>
      <div class="stat-item"><span class="badge changed">~$modifications</span><span>修改</span></div>
      <div class="stat-item"><span>未变 $unchanged · 共 $total 单元</span></div>
      <input type="text" class="search-input" id="searchInput" placeholder="搜索内容... (Ctrl+F)">
      <div class="nav-group">
        <button class="nav-btn" id="prevBtn" title="上一处差异">&uarr; 上一处</button>
        <span class="nav-counter" id="navCounter">- / $diff_count</span>
        <button class="nav-btn" id="nextBtn" title="下一处差异">&darr; 下一处</button>
      </div>
    </div>
  </div>
  <div class="diff-wrapper">
    <table class="diff-table">
      <colgroup><col style="width:46px"><col><col style="width:46px"><col></colgroup>
      <thead><tr><th></th><th>原文 $old_name</th><th></th><th>新文 $new_name</th></tr></thead>
      <tbody id="diffBody">
$rows
      </tbody>
    </table>
  </div>
</div>
<script>
(function () {
  var diffRows = Array.prototype.slice.call(
    document.querySelectorAll('#diffBody tr[data-diff]'));
  var current = -1;
  var counter = document.getElementById('navCounter');

  function goTo(index) {
    if (!diffRows.length) return;
    if (current >= 0) diffRows[current].classList.remove('diff-current');
    current = (index + diffRows.length) % diffRows.length;
    var row = diffRows[current];
    row.classList.add('diff-current');
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    counter.textContent = (current + 1) + ' / ' + diffRows.length;
  }
  document.getElementById('nextBtn').addEventListener('click', function () { goTo(current + 1); });
  document.getElementById('prevBtn').addEventListener('click', function () { goTo(current - 1); });

  var searchInput = document.getElementById('searchInput');
  function clearHighlights() {
    document.querySelectorAll('mark.search-highlight').forEach(function (el) {
      var parent = el.parentNode;
      parent.replaceChild(document.createTextNode(el.textContent), el);
      parent.normalize();
    });
  }
  function escapeRegex(s) { return s.replace(/[.*+?^$${}()|[\\]\\\\]/g, '\\\\$$&'); }
  function highlight(query) {
    var regex = new RegExp('(' + escapeRegex(query) + ')', 'gi');
    document.querySelectorAll('#diffBody td.line').forEach(function (cell) {
      var walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT, null);
      var nodes = [], node;
      while ((node = walker.nextNode())) {
        if (node.textContent.toLowerCase().indexOf(query.toLowerCase()) !== -1) nodes.push(node);
      }
      nodes.forEach(function (textNode) {
        var span = document.createElement('span');
        span.innerHTML = textNode.textContent.replace(regex,
          '<mark class="search-highlight">$$1</mark>');
        textNode.parentNode.replaceChild(span, textNode);
      });
    });
    var first = document.querySelector('mark.search-highlight');
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  var timer = null;
  searchInput.addEventListener('input', function () {
    clearTimeout(timer);
    var value = this.value.trim();
    timer = setTimeout(function () {
      clearHighlights();
      if (value.length >= 2) highlight(value);
    }, 200);
  });
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && e.key === 'f') { e.preventDefault(); searchInput.focus(); searchInput.select(); }
    if (e.key === 'F3' || (e.altKey && e.key === 'ArrowDown')) { e.preventDefault(); goTo(current + 1); }
    if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); goTo(current - 1); }
  });
})();
</script>
</body>
</html>
""")


def _row_html(row_type, old_num, old_class, old_content, new_num, new_class, new_content):
    diff_attr = f' data-diff="{row_type}"' if row_type != "equal" else ""
    return (
        f'<tr{diff_attr}>'
        f'<td class="num">{old_num}</td><td class="line {old_class}">{old_content or "&nbsp;"}</td>'
        f'<td class="num">{new_num}</td><td class="line {new_class}">{new_content or "&nbsp;"}</td>'
        f'</tr>'
    )


def generate_html(diff_result: dict, output_file: str, title: str,
                  old_name: str = "", new_name: str = "", theme: str = "dark") -> None:
    """生成左右对照 HTML 差异报告"""
    esc = html_mod.escape
    theme_colors = THEMES.get(theme, THEMES["dark"])
    stats = diff_result["stats"]
    units = diff_result["units"]

    rows = []
    old_num = new_num = 0
    for unit in units:
        unit_type = unit["type"]
        if unit_type == "equal":
            old_num += 1
            new_num += 1
            rows.append(_row_html("equal", old_num, "", esc(unit["old"]),
                                  new_num, "", esc(unit["new"])))
        elif unit_type == "deleted":
            old_num += 1
            rows.append(_row_html("deleted", old_num, "deleted", esc(unit["old"]),
                                  "", "empty", ""))
        elif unit_type == "added":
            new_num += 1
            rows.append(_row_html("added", "", "empty", "",
                                  new_num, "added", esc(unit["new"])))
        else:  # modified: *_html 已含高亮标记与转义
            old_num += 1
            new_num += 1
            rows.append(_row_html("modified", old_num, "modified", unit["old_html"],
                                  new_num, "modified", unit["new_html"]))

    css_vars = "\n".join(
        f"  --{key.replace('_', '-')}: {value};" for key, value in theme_colors.items()
    )
    diff_count = stats["additions"] + stats["deletions"] + stats["modifications"]

    page = _PAGE.substitute(
        title=esc(title),
        css_vars=css_vars,
        additions=stats["additions"],
        deletions=stats["deletions"],
        modifications=stats["modifications"],
        unchanged=stats["unchanged"],
        total=len(units),
        diff_count=diff_count,
        old_name=esc(old_name),
        new_name=esc(new_name),
        rows="\n".join(rows),
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(page)
