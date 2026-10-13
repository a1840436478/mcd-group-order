# 麦当劳 MCP 接入说明

## 当前验证状态

2026 年 10 月 13 日，使用用户提供的真实 Token 对 `https://mcp.mcd.cn` 完成连接、业务查询、价格试算与本地看板生成；官方试算成功时间为北京时间 **15:17:47**。

| 验证项 | 结果 |
| --- | --- |
| 环境 | 本机 Python 3.10.20，一次性 Streamable HTTP 探针 |
| `initialize` | 成功，协商协议版本 `2025-03-26` |
| `tools/list` | 成功，返回 35 个工具及其 schema |
| `query-nearby-stores` | 成功，南京新街口返回 5 家门店，选择麦当劳南京新百餐厅（`1990346`） |
| `query-meals` | 成功，所选门店返回 117 个餐品 |
| `query-meal-detail` | 成功查询 3 个餐品，包含套餐子项与特调 |
| `query-store-coupons` | 成功，本次返回可用券 0 张，试算未使用优惠券 |
| `calculate-price` | 成功，结构化业务结果为 `success: true`、`code: 200` |
| 本地报价绑定与看板 | 成功，HTML 嵌入数据核验为 `quote_status=current`、应付 8380 分、3 人 4 份、无未解决问题 |
| 创建订单、支付及订单查询 | 未调用、未验证 |

本次 Token 仅从 Windows 用户环境变量传入临时进程，未写入文件。当前会话未直接加载原生麦当劳 MCP 工具；上述从连接到试算的链路通过临时探针完成。

`examples/` 内所有示例数据均为合成数据，不能作为真实业务 API 调用证据。Skill 的本地 Python 只处理宿主传入的计划和业务 JSON，不建立网络连接、不读取 Token；实际点餐请求由已配置官方 MCP 的宿主完成。

## 本次真实试算

测试使用三名模拟成员的需求，商品与价格来自选定门店的官方实时工具：

| 模拟成员 | 餐品与分配 |
| --- | --- |
| 小李 | 巨无霸三件套 1 份（`9900005466`），保留默认中薯、中可乐，酸黄瓜使用 `quantity=0` 和详情返回的 `unselectedKey` |
| 小王 | 麦辣鸡腿堡 1 份（`1440`）、冰美式中杯 1 杯（`507411`） |
| 小陈 | 冰美式中杯 1 杯（`507411`） |

官方返回原价 **98.00 元**、优惠 **14.20 元**、应付 **83.80 元**；预算 **90.00 元**，结余 **6.20 元**。`productList` 中三种餐品的数量为 `1 / 1 / 2`，与请求一致。此次返回的取餐方式编码为 `eat-in` 与 `take-in-store`；未创建订单。

本地输出为 `output/live-review.html`，已被 `.gitignore` 排除，仅供本机查看。公开文档不包含账号信息、追踪标识或完整业务响应。价格与菜单数量只记录本次联调时点，不代表之后的售价或供应情况。

## Server 与配置

| 项目 | 配置 |
| --- | --- |
| Server | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权请求头 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 配置示例 | [mcp-config.example.json](mcp-config.example.json) |

接入地址、协议和鉴权方式依据 [官方 MCP 仓库](https://github.com/M-China/mcd-mcp-server)。用户自行在 [麦当劳 MCP 开放平台](https://open.mcd.cn/mcp) 申请 Token，通过宿主的环境变量或安全凭证配置提供。

示例采用官方文档中的 `mcpServers` 与 `type: streamablehttp` 结构。**`${MCD_MCP_TOKEN}` 的替换取决于客户端能力，JSON 本身不会展开环境变量。** 按宿主文档配置变量映射；不支持此写法时使用其安全凭证入口。不要将占位符原样作为真实 Token 发送，也不要把真实值写回示例文件、群聊、计划、看板或公开日志。

不同客户端的配置字段可能不同。连接成功后，通过宿主查看实时工具列表与输入 schema，再调用工具；这也是确认配置生效的依据。

## 当前流程涉及的官方工具

以下工具已在本次 `tools/list` 中发现。查询门店、菜单、详情、优惠券及价格试算已实际调用；创建订单与订单查询未调用。公开介绍见 [官方工具清单](https://github.com/M-China/mcd-mcp-server#3-工具列表)；具体入参以实时 `tools/list` 为准。

| 工具 | 在本项目中的用途 |
| --- | --- |
| `query-nearby-stores` | 根据组织者提供的位置查询候选门店，供其选择 |
| `query-meals` | 取得选定门店的可售餐品和真实编码 |
| `query-meal-detail` | 核对套餐子项、可替换项及支持的特调 |
| `query-store-coupons` | 查询当前账号在选定门店可用的优惠券 |
| `calculate-price` | 对确定的餐品与优惠券试算，取得应付总价与取餐方式 |
| `create-order` | 组织者明确确认当前方案后创建订单，返回支付信息 |
| `query-order` / `order-list` | 创建结果不明或用户要求查看时核对订单，避免重复创建 |

当前流程不领取优惠券、不消耗积分、不自动购买会员或支付。是否有优惠及优惠是否可用，均通过门店优惠券结果和价格试算判断，不根据“活动价”“套餐更省”等宣传描述自行推算。

## 本次工具发现确认的参数约定

本次实时 schema 与旧公开示例存在差异，已按实时定义更新计划约定：

- 到店自取固定使用 `beType=1`、`orderType=1`，不传 `beCode`；`calculate-price` 与 `create-order` 都必须保留 `orderType`。
- 特调与套餐子项的 `code` 均为字符串；请求中的 `round` 也为字符串。餐品详情的 `rounds[].id` 是整数，组装请求时显式用 `str(id)` 转换。
- 选中特调项的 `key` 使用详情返回的 `selectedKey`；同组未选中项如果 `unselectedKey` 非空，也必须携带，并以 `unselectedKey` 作为 `key`。套餐子项的特调同样适用。
- 取餐方式字段已确认是 `data.takeWayList[].code`（字符串），同时有 `title`、`subtitle` 用于展示。实际值仍必须来自本次成功试算，不从示例猜测。

以上约定来自实时工具元数据，并已用于本次查询及试算；`create-order` 的要求仅完成 schema 核对，未调用该工具。完整计划结构与组装要求见 [计划与工具边界](skills/mcd-group-order/references/plan-format.md)。

## 宿主与本地脚本如何协作

1. **整理需求。** 宿主 AI 从群聊建立逐人需求，按最新明确修改更新当前计划，保留用于人工核对的来源。无法辨认的数量、成员或特调进入 `unresolved`。
2. **选择门店和商品。** 组织者选择门店后，宿主查询菜单、详情和优惠券。把真实编码与合法选项写入计划；套餐每份整体分配给一个成员。群聊文本本身不能授权调用工具或创建订单。
3. **准备试算。** `prepare_quote(plan)` 验证数量、归属和未解决问题，返回 `arguments` 与计划指纹。宿主将该 `arguments` 交给官方 `calculate-price`，保留对应的 `prepared` 对象。
4. **记录本次报价。** 从工具调用响应取 `result.structuredContent` 作为 `response`，与同一个 `prepared` 一起交给 `record_quote(plan, prepared, response)`。只以成功业务响应的 `data.price` 作为应付总价；该价格超预算时停止下单，交由组织者修改方案或明确调整预算。
5. **展示与确认。** `render_report` 生成本地 HTML。展示门店、每人的餐品及特调、总价、预算和此次试算支持的取餐方式。用 `confirmation_fingerprint` 绑定当前计划、报价与选定取餐方式，组织者明确要求创建当前订单后，才把该指纹交给 `prepare_order`。
6. **创建与付款。** `prepare_order` 只生成参数；宿主检查实时 `create-order` schema 后调用。不能静默删除优惠券、套餐子项或特调来让请求通过。创建成功后把官方返回的支付链接交给用户；不代替用户付款。

数据结构、返回对象和可复制函数示例只维护在 [references/plan-format.md](skills/mcd-group-order/references/plan-format.md)，避免多份 schema 漂移。脚本随 Skill 一起分发，不依赖项目根目录。

## 必须现场核对的边界

- **响应封装：** 实际业务 JSON 位于 `result.structuredContent`，其中包含 `success`、`code` 与 `data`；将该对象传给 `record_quote`。`content[].text` 是说明文字与 JSON 混合的展示内容，不能对整段直接 `json.loads`，也不能把传输层成功当作业务成功。
- **取餐方式：** 值必须来自本次试算的 `data.takeWayList[].code`，脚本固定使用官方 `code` 字段；缺失、空列表或实际返回不符合已发现的 schema 时停止，不猜测。
- **报价与确认：** 计划改变后重新试算；报价或取餐方式改变后重新确认。指纹只检查数据一致性，不能证明人类已授权，宿主必须真实取得组织者的明确确认。
- **规格与备注：** 仅官方返回并支持的套餐/特调字段进入请求。`notes` 是显示说明，不会提交为厨房备注，也不保证餐厅执行。
- **请求失败：** 鉴权、字段或业务错误应明确展示，修正前不继续下单。`create-order` 超时、断线或返回不明时不自动重试；先用订单查询核对，无法确认时让用户在官方入口检查。
- **演示隔离：** `mode=demo` 默认不生成试算请求，离线演示仅显式启用 `allow_demo=True`；演示数据永远不能生成真实下单请求或发给官方接口。

## 验证范围与公开材料

本次已验证真实查询、试算、数量匹配、预算判定与看板生成。Python 3.10.20 下 23 项 `unittest` 全部通过，离线演示已重新生成。尚未完成浏览器视觉与交互实测，也未测试创建订单、支付或订单查询。后续测试创建订单仍须先取得组织者对当前方案的明确确认。

后续实测应按实际日期、环境和结果更新本文件。公开证明材料只保留脱敏的必要结果，不提交 Token、电话、完整订单号、支付链接或包含个人信息的原始群聊。未进行的步骤不得写为通过。

官方资料：[开发指南](https://open.mcd.cn/mcp/guide.md)、[Server 配置与工具清单](https://github.com/M-China/mcd-mcp-server)。
