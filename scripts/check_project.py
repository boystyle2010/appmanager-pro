"""
Kiểm tra nhanh toàn bộ dự án trước khi build (chạy trong CI, không cần Docker/mạng):
  1. Mọi `from app.x import y` / `import app.x` đều trỏ tới file có thật và tên import có thật.
  2. Template Jinja (index.html, auth.html) không có lỗi cú pháp.
  3. Mọi file /static/... mà template gọi tới đều có trong repo (trừ /static/vendor, tải lúc build).
Bắt đúng các lỗi từng gặp: file bị đổi tên sai (system__monitor.py), thiếu hàm, file cụt giữa chừng.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
errors: list[str] = []


def module_file(mod: str) -> Path | None:
    p = ROOT / Path(*mod.split("."))
    if p.with_suffix(".py").exists():
        return p.with_suffix(".py")
    if (p / "__init__.py").exists():
        return p / "__init__.py"
    return p if p.is_dir() else None  # namespace package (không có __init__.py)


def top_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


# 1) import nội bộ
for py in sorted(APP.rglob("*.py")):
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except SyntaxError as exc:
        errors.append(f"{py.relative_to(ROOT)}: lỗi cú pháp dòng {exc.lineno}: {exc.msg}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "app" and node.level == 0:
            target = module_file(node.module)
            if target is None:
                errors.append(f"{py.relative_to(ROOT)}:{node.lineno}: không tìm thấy module '{node.module}'")
                continue
            if target.is_file():
                have = top_level_names(target)
                for alias in node.names:
                    if alias.name != "*" and alias.name not in have and module_file(f"{node.module}.{alias.name}") is None:
                        errors.append(f"{py.relative_to(ROOT)}:{node.lineno}: '{alias.name}' không có trong {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "app" and module_file(alias.name) is None:
                    errors.append(f"{py.relative_to(ROOT)}:{node.lineno}: không tìm thấy module '{alias.name}'")

# 2) Jinja
try:
    import jinja2
    env = jinja2.Environment()
    for tpl in sorted((APP / "templates").glob("*.html")):
        try:
            env.parse(tpl.read_text(encoding="utf-8"))
        except jinja2.TemplateSyntaxError as exc:
            errors.append(f"{tpl.relative_to(ROOT)}:{exc.lineno}: Jinja lỗi: {exc.message}")
except ImportError:
    print("Bỏ qua kiểm tra Jinja (chưa cài jinja2)")

# 3) file /static được tham chiếu
for tpl in sorted((APP / "templates").glob("*.html")):
    text = tpl.read_text(encoding="utf-8")
    for ref in set(re.findall(r'(?:src|href)="(/static/[^"?#]+)', text)):
        if ref.startswith("/static/vendor/") or ref == "/static/css/tailwind.css":
            continue
        if not (APP / ref.lstrip("/")).exists():
            errors.append(f"{tpl.relative_to(ROOT)}: tham chiếu {ref} nhưng file không tồn tại")

if errors:
    print("PHÁT HIỆN LỖI:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("OK: import nội bộ, Jinja và file tĩnh đều hợp lệ")
