"""Deterministic checks for a group order. No network calls or credentials."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """A draft or quote cannot safely progress to the next step."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def _fields(value: Any, required: set[str], optional: set[str], label: str) -> None:
    _require(isinstance(value, dict), f"{label} 必须是对象")
    _require(required <= value.keys(), f"{label} 缺少字段：{', '.join(sorted(required - value.keys()))}")
    _require(value.keys() <= required | optional,
             f"{label} 包含不支持的字段：{', '.join(sorted(value.keys() - required - optional))}")


def _text(value: Any, label: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} 必须是非空文本")


def _integer(value: Any, label: str, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{label} 必须是 ≥ {minimum} 的整数")


def _texts(value: Any, label: str) -> None:
    _require(isinstance(value, list), f"{label} 必须是文本列表")
    for entry in value:
        _text(entry, label)


def _modification(value: Any, label: str) -> None:
    _fields(value, {"values"}, set(), label)
    _require(isinstance(value["values"], list) and bool(value["values"]), f"{label}.values 不能为空")
    for choice in value["values"]:
        _fields(choice, {"code", "quantity", "key"}, set(), label)
        _text(choice["code"], f"{label}.code")
        _integer(choice["quantity"], f"{label}.quantity")
        _text(choice["key"], f"{label}.key")


def validate_plan(plan: dict) -> None:
    """Validate structure and allocation counts, not natural-language meaning."""
    _fields(plan, {"mode", "title", "store_name", "context", "budget_fen", "members", "lines", "unresolved", "changes"}, set(), "计划")
    _require(plan["mode"] in ("live", "demo"), "mode 必须是 live 或 demo")
    _text(plan["title"], "title")
    _text(plan["store_name"], "store_name")
    context = plan["context"]
    _fields(context, {"storeCode", "orderType", "beType"}, {"needTableware"}, "context")
    _text(context["storeCode"], "storeCode")
    for key in ("orderType", "beType"):
        _require(type(context[key]) is int and context[key] == 1, "第一版仅支持立即到店取餐（orderType=1, beType=1）")
    if "needTableware" in context:
        _require(type(context["needTableware"]) is bool, "needTableware 必须是布尔值")
    if plan["budget_fen"] is not None:
        _integer(plan["budget_fen"], "budget_fen")
    for key in ("unresolved", "changes"):
        _texts(plan[key], key)
    _require(isinstance(plan["members"], list) and bool(plan["members"]), "members 不能为空")
    members: set[str] = set()
    for member in plan["members"]:
        _fields(member, {"id", "name", "requests", "source"}, set(), "成员")
        for key in ("id", "name", "source"):
            _text(member[key], f"成员.{key}")
        _texts(member["requests"], "成员.requests")
        _require(bool(member["requests"]), "成员需求不能为空")
        _require(member["id"] not in members, "成员 id 重复；同名成员也需不同 id")
        members.add(member["id"])
    _require(isinstance(plan["lines"], list) and bool(plan["lines"]), "lines 不能为空")
    allocated: set[str] = set()
    line_ids: set[str] = set()
    for line in plan["lines"]:
        _fields(line, {"id", "name", "item", "allocations"}, {"notes"}, "餐品行")
        for key in ("id", "name"):
            _text(line[key], f"餐品行.{key}")
        _require(isinstance(line.get("notes", ""), str), "notes 必须是文本")
        _require(line["id"] not in line_ids, "餐品行 id 重复")
        line_ids.add(line["id"])
        item = line["item"]
        _fields(item, {"productCode", "quantity"}, {"couponId", "couponCode", "modification", "roundList"}, "item")
        _text(item["productCode"], "productCode")
        _integer(item["quantity"], "item.quantity", 1)
        _require(("couponId" in item) == ("couponCode" in item), "使用优惠券需同时提供 couponId 和 couponCode")
        for key in ("couponId", "couponCode"):
            if key in item:
                _text(item[key], key)
        if "modification" in item:
            _modification(item["modification"], "modification")
        if "roundList" in item:
            _require(isinstance(item["roundList"], list) and bool(item["roundList"]), "roundList 不能为空")
            for group in item["roundList"]:
                _fields(group, {"round", "comboItemList"}, set(), "套餐子项组")
                _text(group["round"], "round")
                _require(isinstance(group["comboItemList"], list) and bool(group["comboItemList"]), "comboItemList 不能为空")
                for child in group["comboItemList"]:
                    _fields(child, {"code", "quantity"}, {"modification"}, "套餐子项")
                    _text(child["code"], "子项 code")
                    _integer(child["quantity"], "子项 quantity", 1)
                    if "modification" in child:
                        _modification(child["modification"], "子项 modification")
        _require(isinstance(line["allocations"], list) and bool(line["allocations"]), "每行必须分配归属")
        owners: set[str] = set()
        count = 0
        for allocation in line["allocations"]:
            _fields(allocation, {"member_id", "quantity"}, set(), "分配项")
            _text(allocation["member_id"], "member_id")
            owner = allocation["member_id"]
            _require(owner in members, f"未知成员：{owner}")
            _require(owner not in owners, f"同一行重复分配给 {owner}，请合并数量")
            _integer(allocation["quantity"], "分配 quantity", 1)
            count += allocation["quantity"]
            owners.add(owner)
            allocated.add(owner)
        _require(count == item["quantity"], f"{line['name']}：下单 {item['quantity']} 份，分配 {count} 份，数量不一致")
    _require(allocated == members, f"这些成员还没有餐品：{', '.join(sorted(members - allocated))}")


def _fingerprint(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(data.encode("utf-8")).hexdigest()


def prepare_quote(plan: dict, *, allow_demo: bool = False) -> dict:
    """Build calculate-price arguments. Explicit demo use is offline only."""
    validate_plan(plan)
    _require(not plan["unresolved"], "仍有待确认问题：" + "；".join(plan["unresolved"]))
    _require(plan["mode"] == "live" or allow_demo, "演示计划禁止发送真实 MCP；allow_demo 仅供离线测试")
    arguments = deepcopy(plan["context"])
    # Preserve complete items, including zero-quantity removals and combo choices.
    # Do not merge same-code items: their customizations/coupons may differ.
    arguments["items"] = [deepcopy(line["item"]) for line in plan["lines"]]
    return {"plan_fingerprint": _fingerprint(plan), "arguments": arguments}


def _quote_data(plan: dict, response: dict) -> dict:
    _require(isinstance(response, dict), "试算响应必须是业务 JSON 对象")
    _require(response.get("success") is True and type(response.get("code")) is int and response["code"] == 200,
             "官方试算未成功，不得把错误响应当作报价")
    data = response.get("data")
    _require(isinstance(data, dict), "试算响应缺少 data")
    _integer(data.get("price"), "试算 data.price（分）")
    for key in ("originalPrice", "discount", "productPrice", "deliveryPrice", "tablewarePrice"):
        if key in data:
            _integer(data[key], f"试算 data.{key}（分）")
    _require(isinstance(data.get("productList"), list) and bool(data["productList"]), "试算响应缺少商品核对清单 productList")
    actual: Counter = Counter()
    for product in data["productList"]:
        _require(isinstance(product, dict), "productList 元素必须是对象")
        _text(product.get("productCode"), "返回的 productCode")
        _integer(product.get("quantity"), "返回的 quantity", 1)
        actual[product["productCode"]] += product["quantity"]
    expected: Counter = Counter()
    for line in plan["lines"]:
        expected[line["item"]["productCode"]] += line["item"]["quantity"]
    _require(actual == expected, "试算返回的餐品编码/数量与请求不一致，请核对接口结果")
    return data


def record_quote(plan: dict, prepared: dict, response: dict) -> dict:
    """Bind an actual tool response to the exact draft that was sent."""
    expected = prepare_quote(plan, allow_demo=plan.get("mode") == "demo")
    _require(prepared == expected, "计划或试算请求已变化，请重新试算")
    _quote_data(plan, response)
    return {"plan_fingerprint": expected["plan_fingerprint"], "response": deepcopy(response)}


def _current_quote(plan: dict, receipt: dict) -> dict:
    validate_plan(plan)
    _require(not plan["unresolved"], "仍有待确认问题，不能下单")
    _fields(receipt, {"plan_fingerprint", "response"}, set(), "试算收据")
    _require(receipt["plan_fingerprint"] == _fingerprint(plan), "计划已修改，旧报价失效，请重新试算")
    return _quote_data(plan, receipt["response"])


def _take_way(data: dict, selected: str) -> None:
    _text(selected, "take_way_code")
    options = data.get("takeWayList")
    _require(isinstance(options, list) and bool(options), "试算未返回可用取餐方式，不能猜测 takeWayCode")
    _require(any(isinstance(option, dict) and option.get("code") == selected for option in options),
             "取餐方式不在本次试算返回的列表中")


def confirmation_fingerprint(plan: dict, receipt: dict, take_way_code: str) -> str:
    """Identify the precise plan, quote and pickup option shown to the user."""
    data = _current_quote(plan, receipt)
    _take_way(data, take_way_code)
    return _fingerprint({"plan": plan, "receipt": receipt, "take_way_code": take_way_code})


def prepare_order(plan: dict, receipt: dict, *, confirmed_fingerprint: str,
                  take_way_code: str) -> dict:
    """Build create-order arguments after the organizer confirms this quote.

    This function does not prove human consent and never sends an order itself.
    The host must obtain consent and invoke the official tool only once.
    """
    validate_plan(plan)
    _require(plan["mode"] == "live", "演示数据不能创建真实订单")
    data = _current_quote(plan, receipt)
    budget = plan["budget_fen"]
    _require(budget is None or data["price"] <= budget, "试算金额超过预算，请调整计划或由组织者修改预算后重新试算")
    expected = confirmation_fingerprint(plan, receipt, take_way_code)
    _require(confirmed_fingerprint == expected, "尚未确认当前计划、报价和取餐方式，不能生成下单请求")
    arguments = prepare_quote(plan)["arguments"]
    # The live create-order schema requires orderType, just like calculate-price.
    arguments["takeWayCode"] = take_way_code
    return arguments


def report_data(plan: dict, receipt: dict | None = None) -> dict:
    """Build a display-only view without exposing coupons or payment details."""
    validate_plan(plan)
    issues = list(plan["unresolved"])
    quote = None
    status = "missing"
    if receipt is not None:
        status = "invalid"
        try:
            if isinstance(receipt, dict) and receipt.get("plan_fingerprint") != _fingerprint(plan):
                status = "stale"
                raise PlanError("计划已修改，旧报价失效，请重新试算")
            data = _current_quote(plan, receipt)
            status = "current"
            quote = {"price_fen": data["price"], "original_price_fen": data.get("originalPrice"),
                     "discount_fen": data.get("discount")}
            if plan["budget_fen"] is not None and data["price"] > plan["budget_fen"]:
                issues.append(f"超出预算 {(data['price'] - plan['budget_fen']) / 100:.2f} 元，不能按当前预算下单")
        except PlanError as error:
            issues.append(str(error))
    members = []
    for member in plan["members"]:
        view = deepcopy(member)
        view["items"] = []
        for line in plan["lines"]:
            for allocation in line["allocations"]:
                if allocation["member_id"] == member["id"]:
                    view["items"].append({"name": line["name"], "quantity": allocation["quantity"], "notes": line.get("notes", "")})
        members.append(view)
    totals = [{"name": line["name"], "quantity": line["item"]["quantity"], "notes": line.get("notes", "")} for line in plan["lines"]]
    checklist = [f"{plan['title']}｜{'演示数据，非真实订单' if plan['mode'] == 'demo' else '点餐核对清单，非下单凭证'}", f"门店：{plan['store_name']}"]
    for member in members:
        meals = "；".join(f"{item['name']} × {item['quantity']}" + (f"（{item['notes']}）" if item['notes'] else "") for item in member["items"])
        checklist.append(f"{member['name']}：{meals}")
    if quote:
        checklist.append(f"{'演示试算' if plan['mode'] == 'demo' else '本次试算应付'}：¥{quote['price_fen'] / 100:.2f}")
    else:
        checklist.append("当前没有可用报价，请先重新试算。")
    checklist.extend(f"待处理：{issue}" for issue in issues)
    return {"title": plan["title"], "mode": plan["mode"], "store_name": plan["store_name"],
            "budget_fen": plan["budget_fen"], "fingerprint": _fingerprint(plan), "quote_status": status,
            "quote": quote, "issues": issues, "members": members, "totals": totals,
            "checklist": "\n".join(checklist), "changes": list(plan["changes"])}


def render_report(plan: dict, receipt: dict | None, output_path: str | Path) -> Path:
    """Write a standalone, offline HTML review sheet; never submit an order."""
    view = report_data(plan, receipt)
    template = Path(__file__).resolve().parents[1] / "assets" / "report.html"
    markup = template.read_text(encoding="utf-8")
    _require(markup.count("__REPORT_DATA__") == 1, "报告模板必须包含唯一数据占位符")
    # A JSON script tag is still terminated by literal </script> in user text.
    encoded = json.dumps(view, ensure_ascii=False, allow_nan=False)
    for character, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        encoded = encoded.replace(character, escaped)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markup.replace("__REPORT_DATA__", encoded), encoding="utf-8")
    return path
