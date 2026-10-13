"""Offline behavioral checks; all catalog IDs and responses are synthetic."""

from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "mcd-group-order" / "scripts"))
from order_plan import (  # noqa: E402
    PlanError, confirmation_fingerprint, prepare_order, prepare_quote,
    record_quote, render_report, report_data, validate_plan,
)


class GroupOrderTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / "examples" / "plan.demo.json").read_text(encoding="utf-8"))
        # Test the live-mode guards offline, with fixtures, never network calls.
        self.plan["mode"] = "live"
        self.response = json.loads((ROOT / "examples" / "quote.demo.json").read_text(encoding="utf-8"))

    def quoted(self):
        return record_quote(self.plan, prepare_quote(self.plan), self.response)

    def order(self, receipt, confirmation=None, pickup="DEMO_PICKUP"):
        if confirmation is None:
            confirmation = confirmation_fingerprint(self.plan, receipt, pickup)
        return prepare_order(self.plan, receipt, confirmed_fingerprint=confirmation, take_way_code=pickup)

    def test_quote_and_order_preserve_coupons_combo_and_zero_quantity_removal(self):
        original = deepcopy(self.plan)
        prepared = prepare_quote(self.plan)
        receipt = self.quoted()
        order = self.order(receipt)
        self.assertEqual(order["items"], prepared["arguments"]["items"])
        self.assertEqual(order["items"][0]["roundList"][0]["comboItemList"][0]["modification"]["values"][0]["quantity"], 0)
        self.assertEqual(order["items"][1]["couponId"], "DEMO_COUPON_ID")
        self.assertEqual(order["takeWayCode"], "DEMO_PICKUP")
        self.assertEqual(order["orderType"], 1)
        self.assertNotIn("beCode", order)
        self.assertNotIn("notes", order["items"][0])
        order["items"][0]["quantity"] = 999
        self.assertEqual(self.plan, original)

    def test_coffee_allocation_is_per_person(self):
        view = report_data(self.plan, self.quoted())
        counts = {member["id"]: sum(item["quantity"] for item in member["items"] if "咖啡" in item["name"]) for member in view["members"]}
        self.assertEqual(counts, {"li": 0, "wang": 1, "chen": 1})
        self.assertEqual(view["quote"]["price_fen"], 7300)

    def test_under_or_over_allocation_rejected(self):
        for quantity in (1, 3):
            with self.subTest(quantity=quantity):
                plan = deepcopy(self.plan)
                plan["lines"][2]["item"]["quantity"] = quantity
                with self.assertRaisesRegex(PlanError, "数量不一致"):
                    prepare_quote(plan)

    def test_unknown_owner_and_unserved_member_rejected(self):
        self.plan["lines"][2]["allocations"][1]["member_id"] = "stranger"
        with self.assertRaisesRegex(PlanError, "未知成员"):
            validate_plan(self.plan)
        self.plan["lines"][2]["allocations"] = [{"member_id": "wang", "quantity": 2}]
        with self.assertRaisesRegex(PlanError, "还没有餐品"):
            validate_plan(self.plan)

    def test_different_customizations_are_never_merged(self):
        coffee = self.plan["lines"].pop()
        for index, allocation in enumerate(coffee["allocations"]):
            line = deepcopy(coffee)
            line["id"] = f"coffee-{index}"
            line["item"]["quantity"] = 1
            line["allocations"] = [allocation]
            if index == 0:
                line["item"]["modification"] = {"values": [{"code": "DEMO_ICE", "quantity": 0, "key": "DEMO_NO_ICE"}]}
            self.plan["lines"].append(line)
        items = prepare_quote(self.plan)["arguments"]["items"]
        self.assertEqual(len(items), 4)
        self.assertIn("modification", items[2])
        self.assertNotIn("modification", items[3])
        self.assertEqual(self.order(self.quoted())["items"], items)

    def test_unresolved_request_is_visible_but_blocks_quote(self):
        self.plan["unresolved"] = ["接口没有去酸黄瓜选项，需组织者选择替代方案"]
        view = report_data(self.plan)
        self.assertEqual(view["issues"], self.plan["unresolved"])
        self.assertIsNone(view["quote"])
        with self.assertRaisesRegex(PlanError, "待确认"):
            prepare_quote(self.plan)

    def test_demo_cannot_quote_live_or_create_order(self):
        self.plan["mode"] = "demo"
        with self.assertRaisesRegex(PlanError, "演示计划"):
            prepare_quote(self.plan)
        prepared = prepare_quote(self.plan, allow_demo=True)
        receipt = record_quote(self.plan, prepared, self.response)
        with self.assertRaisesRegex(PlanError, "演示数据"):
            self.order(receipt)

    def test_change_during_tool_call_rejects_response(self):
        prepared = prepare_quote(self.plan)
        self.plan["members"][0]["requests"].append("饮料改为热饮")
        with self.assertRaisesRegex(PlanError, "重新试算"):
            record_quote(self.plan, prepared, self.response)

    def test_modified_prepared_payload_rejects_response(self):
        prepared = prepare_quote(self.plan)
        prepared["arguments"]["items"][0]["quantity"] = 2
        with self.assertRaisesRegex(PlanError, "试算请求已变化"):
            record_quote(self.plan, prepared, self.response)

    def test_owner_notes_budget_or_store_change_invalidates_quote(self):
        receipt = self.quoted()
        variants = []
        for key, value in (("budget_fen", 10000), ("store_name", "另一门店")):
            plan = deepcopy(self.plan)
            plan[key] = value
            variants.append(plan)
        plan = deepcopy(self.plan)
        plan["lines"][0]["notes"] = "改为不去酸黄瓜"
        variants.append(plan)
        plan = deepcopy(self.plan)
        plan["lines"][0]["allocations"][0]["member_id"] = "wang"
        plan["lines"][1]["allocations"][0]["member_id"] = "li"
        variants.append(plan)
        for plan in variants:
            with self.subTest(plan=plan["title"]):
                view = report_data(plan, receipt)
                self.assertEqual(view["quote_status"], "stale")
                self.assertIsNone(view["quote"])
                self.assertNotIn("73.00", view["checklist"])
                with self.assertRaisesRegex(PlanError, "旧报价失效"):
                    confirmation_fingerprint(plan, receipt, "DEMO_PICKUP")

    def test_price_change_requires_new_confirmation(self):
        old_receipt = self.quoted()
        confirmed = confirmation_fingerprint(self.plan, old_receipt, "DEMO_PICKUP")
        self.response["data"]["price"] = 7400
        new_receipt = self.quoted()
        with self.assertRaisesRegex(PlanError, "尚未确认"):
            self.order(new_receipt, confirmed)
        self.order(new_receipt)

    def test_pickup_change_requires_new_confirmation(self):
        self.response["data"]["takeWayList"].append({"code": "DEMO_OTHER_PICKUP"})
        receipt = self.quoted()
        confirmed = confirmation_fingerprint(self.plan, receipt, "DEMO_PICKUP")
        with self.assertRaisesRegex(PlanError, "尚未确认"):
            self.order(receipt, confirmed, "DEMO_OTHER_PICKUP")

    def test_missing_confirmation_rejected(self):
        with self.assertRaisesRegex(PlanError, "尚未确认"):
            self.order(self.quoted(), "")

    def test_budget_enforced_and_exact_budget_allowed(self):
        self.plan["budget_fen"] = 7299
        receipt = self.quoted()
        self.assertTrue(any("超出预算" in issue for issue in report_data(self.plan, receipt)["issues"]))
        with self.assertRaisesRegex(PlanError, "超过预算"):
            self.order(receipt)
        self.plan["budget_fen"] = 7300
        self.order(self.quoted())
        self.plan["budget_fen"] = None
        self.order(self.quoted())

    def test_failed_or_malformed_quotes_rejected(self):
        for response in ({"success": False, "code": 200, "data": self.response["data"]}, {"success": True, "code": 500}, {"success": True, "code": 200, "data": {}}, None):
            with self.subTest(response=response):
                with self.assertRaises(PlanError):
                    record_quote(self.plan, prepare_quote(self.plan), response)
        for price in (True, -1, "73.00", 73.0, float("nan")):
            self.response["data"]["price"] = price
            with self.subTest(price=price), self.assertRaises(PlanError):
                self.quoted()

    def test_incomplete_or_wrong_product_response_rejected(self):
        self.response["data"]["productList"][2]["quantity"] = 1
        with self.assertRaisesRegex(PlanError, "不一致"):
            self.quoted()
        self.response["data"]["productList"][2]["quantity"] = 2
        self.response["data"]["productList"][2]["productCode"] = "OTHER"
        with self.assertRaisesRegex(PlanError, "不一致"):
            self.quoted()

    def test_pickup_code_must_come_from_this_response(self):
        with self.assertRaisesRegex(PlanError, "列表中"):
            self.order(self.quoted(), pickup="MADE_UP_CODE")
        self.response["data"]["takeWayList"] = []
        with self.assertRaisesRegex(PlanError, "不能猜测"):
            self.order(self.quoted())

    def test_pickup_code_uses_official_response_field(self):
        self.response["data"]["takeWayList"] = [{"takeWayCode": "UNEXPECTED_SHAPE"}]
        with self.assertRaisesRegex(PlanError, "列表中"):
            self.order(self.quoted(), pickup="UNEXPECTED_SHAPE")

    def test_unknown_fields_and_unsupported_business_type_fail_closed(self):
        self.plan["lines"][0]["item"]["remark"] = "不能用文字冒充特调"
        with self.assertRaisesRegex(PlanError, "不支持的字段"):
            prepare_quote(self.plan)
        del self.plan["lines"][0]["item"]["remark"]
        self.plan["context"]["beType"] = 2
        with self.assertRaisesRegex(PlanError, "仅支持"):
            prepare_quote(self.plan)

    def test_boolean_quantities_and_partial_coupons_rejected(self):
        self.plan["lines"][0]["item"]["quantity"] = True
        with self.assertRaises(PlanError):
            prepare_quote(self.plan)
        self.plan["lines"][0]["item"]["quantity"] = 1
        del self.plan["lines"][1]["item"]["couponCode"]
        with self.assertRaisesRegex(PlanError, "同时提供"):
            prepare_quote(self.plan)

    def test_pickup_rejects_be_code_instead_of_silently_dropping_it(self):
        self.plan["context"]["beCode"] = "UNSUPPORTED_PICKUP_BE"
        with self.assertRaisesRegex(PlanError, "不支持的字段"):
            prepare_quote(self.plan)

    def test_round_and_component_codes_must_match_live_string_schema(self):
        group = self.plan["lines"][0]["item"]["roundList"][0]
        for target, field in ((group, "round"), (group["comboItemList"][0], "code"),
                              (group["comboItemList"][0]["modification"]["values"][0], "code")):
            original = target[field]
            target[field] = 123
            with self.subTest(field=field), self.assertRaises(PlanError):
                prepare_quote(self.plan)
            target[field] = original

    def test_report_escapes_script_injection_and_excludes_private_tool_data(self):
        attack = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'
        self.plan["members"][0]["name"] = attack
        self.response["data"]["payH5Url"] = "https://private.invalid/payment-secret"
        receipt = self.quoted()
        output_dir = ROOT / "output"
        output_dir.mkdir(exist_ok=True)
        page = output_dir / f"report-test-{uuid4().hex}.html"
        try:
            render_report(self.plan, receipt, page)
            html = page.read_text(encoding="utf-8")
            self.assertNotIn(attack, html)
            self.assertNotIn("DEMO_COUPON_ID", html)
            self.assertNotIn("payment-secret", html)
            parser = HTMLParser()
            parser.feed(html)
            embedded = html.split('<script id="report-data" type="application/json">', 1)[1].split('</script>', 1)[0]
            self.assertEqual(json.loads(embedded)["members"][0]["name"], attack)
        finally:
            page.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
