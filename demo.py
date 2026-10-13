"""Run directly in an IDE to generate the offline group-order demonstration."""

from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skills" / "mcd-group-order" / "scripts"))
from order_plan import prepare_quote, record_quote, render_report  # noqa: E402


def main(plan_path: Path, quote_path: Path, output_dir: Path) -> tuple[Path, Path]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("mode") != "demo":
        raise ValueError("demo.py 仅处理合成演示计划，真实计划请使用 Skill")
    response = json.loads(quote_path.read_text(encoding="utf-8"))
    prepared = prepare_quote(plan, allow_demo=True)
    receipt = record_quote(plan, prepared, response)
    original = render_report(plan, receipt, output_dir / "demo.html")

    changed = deepcopy(plan)
    changed["title"] = "临时加一杯？先重新核价"
    changed["lines"][2]["item"]["quantity"] += 1
    changed["lines"][2]["allocations"][1]["quantity"] += 1
    changed["members"][2]["requests"] = ["美式改为两杯"]
    changed["members"][2]["source"] += " 更新：帮我改为两杯美式。"
    changed["changes"].append("小陈把美式从一杯改为两杯；旧报价失效，需要重新试算。")
    changed["lines"][2]["notes"] = "小王一杯，小陈两杯"
    updated = render_report(changed, receipt, output_dir / "changed.html")
    print("离线演示已生成；未连接 MCP、未创建订单。")
    print(f"核对看板：{original}")
    print(f"修改后看板：{updated}")
    return original, updated


if __name__ == "__main__":
    PLAN_PATH = ROOT / "examples" / "plan.demo.json"
    QUOTE_PATH = ROOT / "examples" / "quote.demo.json"
    OUTPUT_DIR = ROOT / "output"
    main(PLAN_PATH, QUOTE_PATH, OUTPUT_DIR)
