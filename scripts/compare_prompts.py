"""So sánh 3 phiên bản prompt tư vấn sản phẩm (v1, v2, v3) trên cùng bộ kịch bản.

Chỉ số chính: số lần AI gợi ý sản phẩm HẾT HÀNG hoặc VƯỢT NGÂN SÁCH (trước khi hệ thống hậu kiểm lọc bỏ).
Cần GEMINI_API_KEY trong .env và đã chạy `python -m scripts.seed`.

Chạy:  python -m scripts.compare_prompts [--runs 3]
Kết quả ghi vào docs/ket_qua_so_sanh_prompt.md
"""
import argparse
import sys
from datetime import datetime

from sqlalchemy import select

from app.ai import service
from app.ai.client import GeminiClient
from app.config import BASE_DIR
from app.database import SessionLocal
from app.models import Product

# Kịch bản cố tình "gài" sản phẩm hết hàng phù hợp nhất (PK002, AT003, DT003 trong dữ liệu mẫu)
SCENARIOS = [
    "Khách cần tai nghe dưới 500000 đồng, pin lâu, còn hàng",
    "Khách muốn tai nghe chống ồn tốt nhất",
    "Tai nghe chụp tai chống ồn pin trâu",
    "Khách muốn mua iPhone",
    "Tai nghe Bluetooth A2 Pro còn không?",
    "Quà tặng cho bạn gái thích nghe nhạc, tầm 1 triệu rưỡi",
    "Loa nghe nhạc đi picnic dưới 1 triệu",
    "Điện thoại pin trâu dưới 5 triệu",
]


def run(runs: int):
    client = GeminiClient()
    if not client.enabled:
        sys.exit("Cần cấu hình GEMINI_API_KEY trong .env để chạy so sánh.")
    db = SessionLocal()
    products = {p.code: p for p in db.scalars(select(Product))}
    results = {v: {"total": 0, "out_of_stock": 0, "over_budget": 0, "empty": 0, "fallback": 0, "samples": []}
               for v in ("v1", "v2", "v3")}

    for version in results:
        r = results[version]
        for msg in SCENARIOS:
            budget = service.parse_budget(msg)
            for i in range(runs):
                res = service.advise(db, client, msg, [], version)
                r["total"] += 1
                if res["source"] != "ai":
                    r["fallback"] += 1
                    continue
                bad = [c for c in res.get("removed", []) if c in products and products[c].stock <= 0]
                over = [s["code"] for s in res["suggestions"] if budget and s["price"] > budget]
                r["out_of_stock"] += bool(bad)
                r["over_budget"] += bool(over)
                r["empty"] += not res["suggestions"]
                if i == 0:
                    r["samples"].append((msg, res["answer"][:300].replace("\n", " "), bad, over))
                print(f"[{version}] {msg[:40]:40} hết hàng={bad} vượt ngân sách={over}")

    lines = [f"# Kết quả so sánh prompt tư vấn ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"Model: `{client.model}` · {len(SCENARIOS)} kịch bản × {runs} lần chạy mỗi phiên bản.", "",
             "| Phiên bản | Số lượt | Gợi ý hàng hết | Vượt ngân sách | Không gợi ý | Lỗi → dự phòng |",
             "|---|---|---|---|---|---|"]
    for v, r in results.items():
        n = max(1, r["total"] - r["fallback"])
        lines.append(f"| {v} | {r['total']} | {r['out_of_stock']} ({r['out_of_stock'] / n:.0%}) | "
                     f"{r['over_budget']} ({r['over_budget'] / n:.0%}) | {r['empty']} | {r['fallback']} |")
    lines += ["", "> Với v1/v2 (văn bản tự do), 'gợi ý hàng hết' = câu trả lời có nhắc mã sản phẩm hết hàng; "
              "cần đọc mẫu bên dưới để loại trường hợp AI chỉ thông báo 'sản phẩm X đã hết'.", ""]
    for v, r in results.items():
        lines += [f"## Mẫu trả lời {v}", ""]
        for msg, ans, bad, over in r["samples"]:
            lines.append(f"- **{msg}** → {ans} {'⚠️ hết hàng: ' + ', '.join(bad) if bad else ''}"
                         f"{' ⚠️ vượt ngân sách: ' + ', '.join(over) if over else ''}")
        lines.append("")
    out = BASE_DIR / "docs" / "ket_qua_so_sanh_prompt.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nĐã ghi kết quả vào {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    run(parser.parse_args().runs)
