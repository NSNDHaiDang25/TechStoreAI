"""Nạp prompt template từ thư mục prompts/.

Định dạng file: hai phần bắt đầu bằng dòng `### SYSTEM` và `### USER`.
Biến dạng {{ten_bien}} được thay bằng giá trị khi render.
"""
import re
from functools import lru_cache

from app.config import settings

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@lru_cache(maxsize=32)
def load_prompt(name: str) -> tuple[str, str]:
    path = settings.PROMPTS_DIR / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    match = re.search(r"^### SYSTEM\s*$(.*?)^### USER\s*$(.*)", raw, re.S | re.M)
    if not match:
        raise ValueError(f"Prompt {path.name} thiếu phần '### SYSTEM' hoặc '### USER'")
    return match.group(1).strip(), match.group(2).strip()


def render(template: str, **values) -> str:
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise KeyError(f"Thiếu biến prompt: {key}")
        return str(values[key])
    return _VAR.sub(sub, template)


def render_prompt(name: str, **values) -> tuple[str, str]:
    system, user = load_prompt(name)
    return render(system, **values), render(user, **values)
