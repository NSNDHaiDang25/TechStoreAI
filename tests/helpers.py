"""Hàm tiện ích dùng chung cho test."""


def product_id(client, headers, code):
    items = client.get("/api/products", params={"q": code}, headers=headers).json()["items"]
    return next(p["id"] for p in items if p["code"] == code)


def stock_of(client, headers, code):
    items = client.get("/api/products", params={"q": code}, headers=headers).json()["items"]
    return next(p["stock"] for p in items if p["code"] == code)

