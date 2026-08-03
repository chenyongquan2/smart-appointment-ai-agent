# OCS4 业务层错误码（Return Code）

> 本文整理 OCS4 **业务层** 返回给上层（API/前端）的错误码，即 `Response.nCode` / `ORDER_RETURN.nResultCode` 中携带的值。
> 这些错误码由 OCS 自身定义，与 MT4/MT5 平台 API 的原生返回码（`RET_*` / `MT_RET_*`）不同——后者见 [`mt-returncode.md`](./mt-returncode.md)。
>
> 来源文件：
> - MT4：`src/ocs/MT4/MT4ParaData.h`（`ENUM_MT4_ERR_CODE`、`ENUM_ERR_CODE`）
> - MT5：`src/ocs/MT5/MT5ParaData.h`（`ENUM_ERR_MT5_CODE`、`ENUM_MT5_ERR_CODE`）

---

## 1. 返回码的产生与结构

业务层通过 `Response`（`MT4_HANDLE_RET_EX::SetCode*`）或 `CODE_DESC::SetCode` 设置返回码，字段含义：

| 字段 | 含义 |
|------|------|
| `nCode` | 错误码（本文表格中的值）。`0` 表示成功（`O.K.`）。 |
| `strCodeDesc` | 错误描述文本（人类可读，常带 MT 原始码与上下文）。 |
| `bIsApiError` | 是否为 **MT API 调用层** 出错（网络/连接类）。`true` 会触发 `NotifyReconAllManager()` 让后台线程重连检查。 |

设置入口（见 `MT4ParaData.h:30-59`）：
- `SetCodeCom(code, desc, ...)` → 业务/参数错误，`bIsApiError=false`
- `SetCodeAPI(code, desc, ...)` → API 出错，`bIsApiError=true`
- `SetCodeAPI(flag, code, desc, ...)` → 由 `flag` 决定是否为 API 错误（常配合 `IsNetworkError()`）

### 错误码段位划分（MT4/MT5 通用约定）

| 段位 | 用途 |
|------|------|
| `0` | 成功 |
| `66400 ~ 66447` | **参数错误**（请求解析、字段校验失败） |
| `66500 ~ 66556` | **业务/交易错误**（连接、下单、查询等具体操作失败） |
| `66700 ~ 66729` | **MT5 专属** API 调用错误（创建对象/调用 SDK 接口失败） |
| `66302 / 68302` | 前端硬编码判断的"账号不存在"专用码 |
| `66534 / 66537` | 前端硬编码判断的"用户禁用 / 交易禁用"专用码（intrade 指定） |

> ⚠️ 头文件中标注「下面的错误码要慢慢废弃」。`ENUM_ERR_CODE`/`ENUM_MT5_ERR_CODE` 为历史码表，新码优先放入 `ENUM_MT4_ERR_CODE`/`ENUM_ERR_MT5_CODE`（前端会硬编码判断的稳定码）。

---

## 2. MT4 OCS 业务层错误码

### 2.1 前端固定判断码（`ENUM_MT4_ERR_CODE`）
| 码值 | 名称 | 说明 |
|------|------|------|
| 0 | `ENUM_MT4_ERR_OK` | 成功 |
| 66302 | `ENUM_MT4_ERR_OP_LOGIN_NOT_EXIST` | 用户账号不存在（前端固定判断） |

### 2.2 参数错误（66400 段）`ENUM_ERR_CODE`
| 码值 | 名称 | 说明 |
|------|------|------|
| 66400 | `ENUM_ERR_PARA_START` | 参数错误返回码起始值 |
| 66401 | `ENUM_ERR_PARA_PARABUFF` | JSON 数据解析错误 |
| 66402 | `ENUM_ERR_PARA_REQUEST_ID` | 请求 ID 错误 |
| 66403 | `ENUM_ERR_PARA_REQUEST_CMD` | 请求 CMD 错误 |
| 66404 | `ENUM_ERR_PARA_LOGIN` | Login 错误 |
| 66405 | `ENUM_ERR_PARA_SYMBOL` | symbol 错误 |
| 66406 | `ENUM_ERR_PARA_TRADE_CMD` | 订单 CMD 错误 |
| 66407 | `ENUM_ERR_PARA__CMD_VALUE` | 订单 CMD 值错误 |
| 66408 | `ENUM_ERR_PARA_VOLUME` | 订单量错误 |
| 66409 | `ENUM_ERR_PARA_SL` | 订单止损错误 |
| 66410 | `ENUM_ERR_PARA_TP` | 订单止盈错误 |
| 66411 | `ENUM_ERR_PARA_EXPIRATION_TIME` | 订单过期时间错误 |
| 66412 | `ENUM_ERR_PARA_COMMENT` | 订单注释错误 |
| 66413 | `ENUM_ERR_PARA_PENDING_PRICE` | 订单挂单价格错误 |
| 66414 | `ENUM_ERR_PARA_ORDER` | 订单号错误 |
| 66415 | `ENUM_ERR_PARA_PASSWORD` | 密码错误 |
| 66416 | `ENUM_ERR_PARA_FOLLOW_ID` | 批量操作 ID 错误 |
| 66417 | `ENUM_ERR_PARA_CLOSE_VOLUME_BELOW_0` | 平仓手数小于 0 |
| 66418 | `ENUM_ERR_PARA_SERVER_ID` | Server id 错误 |
| 66419 | `ENUM_ERR_PARA_NAME` | 用户名错误 |
| 66420 | `ENUM_ERR_PARA_GROUP` | 用户组错误 |
| 66421 | `ENUM_ERR_PARA_INVESTOR_PWD` | 投资人密码错误 |
| 66422 | `ENUM_ERR_PARA_LEVERAGE` | 杠杆错误 |
| 66423 | `ENUM_ERR_PARA_EMAIL` | 邮箱错误 |
| 66424 | `ENUM_ERR_PARA_PHONE_PWD` | 手机密码错误 |
| 66425 | `ENUM_ERR_PARA_COUNTRY` | 国家错误 |
| 66426 | `ENUM_ERR_PARA_STATE` | 省份错误 |
| 66427 | `ENUM_ERR_PARA_CITY` | 城市错误 |
| 66428 | `ENUM_ERR_PARA_ADDRESS` | 地址错误 |
| 66429 | `ENUM_ERR_PARA_PHONE` | 手机号码错误 |
| 66430 | `ENUM_ERR_PARA_STATUS` | 用户身份错误 |
| 66431 | `ENUM_ERR_PARA_ZIP_CODE` | 邮编错误 |
| 66432 | `ENUM_ERR_PARA_ID_NUMBER` | id 错误 |
| 66433 | `ENUM_ERR_PARA_AGENT_ACCOUNT` | 代理错误 |
| 66434 | `ENUM_ERR_PARA_LEAD_SOURCE` | 注册来源错误 |
| 66435 | `ENUM_ERR_PARA_READ_ONLY` | 是否只读错误 |
| 66436 | `ENUM_ERR_PARA_CHANGE_PWD` | 是否允许修改密码错误 |
| 66437 | `ENUM_ERR_PARA_ENABLE` | 是否启用错误 |
| 66438 | `ENUM_ERR_PARA_DEFAULT_DEPOSIT` | 默认入金参数错误 |
| 66439 | `ENUM_ERR_PARA_DEPOSIT` | 入金金额错误 |
| 66440 | `ENUM_ERR_PARA_WITHDRAWAL` | 出金金额错误 |
| 66441 | `ENUM_ERR_OP_DEPOSIT_BELOW_0` | 入金金额小于 0 |
| 66442 | `ENUM_ERR_OP_CALL_TRADETRANSATION` | 调用 TradeTransaction 失败 |
| 66443 | `ENUM_ERR_OP_WITHDRAWAL_BELOW_0` | 出金金额小于 0 |
| 66444 | `ENUM_ERR_OP_NOT_ENOUGH_MONEY_WITHDRAWAL` | 没有足够的钱出金 |
| 66445 | `ENUM_ERR_MTAPI_REQUEST_ERR` | MT API 执行出错 |
| 66446 | `ENUM_ERR_PARA_FROM_TIME` | 订单开始时间错误 |
| 66447 | `ENUM_ERR_PARA_TO_TIME` | 订单结束时间错误 |

### 2.3 业务/交易错误（66500 段）`ENUM_ERR_CODE`
| 码值 | 名称 | 说明 |
|------|------|------|
| 66500 | `ENUM_ERR_OP_UNKNOWCMD` | 命令错误 |
| 66501 | `ENUM_ERR_OP_CONNECTED_SERVER` | 连接 MT4 错误 |
| 66502 | `ENUM_ERR_OP_LOGIN_NOT_EXIST` | 用户 ID 不存在 |
| 66503 | `ENUM_ERR_OP_GET_CURRENT_PRICES` | 获取现价错误 |
| 66504 | `ENUM_ERR_OP_CALL_UPDATEACCOUNT` | 更新用户失败 |
| 66505 | `ENUM_ERR_OP_GET_ORDER` | 订单查询不到 |
| 66506 | `ENUM_ERR_OP_LOGIN_NOT_MACH_ORDER` | 订单的用户 ID 不匹配 |
| 66507 | `ENUM_ERR_OP_ORDER_CLOSED` | 订单已经被平仓过 |
| 66508 | `ENUM_ERR_OP_MULTI_NEW_ORDER_200` | 批量开仓大于 200 |
| 66509 | `ENUM_ERR_OP_MULTI_NEW_ORDER_SIZE` | 批量开仓数据为 0 |
| 66510 | `ENUM_ERR_OP_MULTI_NEW_ORDER_PART_FAILED` | 批量开仓部分操作错误 |
| 66511 | `ENUM_ERR_OP_MULTI_CLOSE_ORDER_PART_FAILED` | 批量平仓部分操作错误 |
| 66512 | `ENUM_ERR_OP_GET_PRICE` | 获取报价失败 |
| 66513 | `ENUM_ERR_OP_LOGIN_BELOW_0` | 用户 ID 小于等于 0 |
| 66514 | `ENUM_ERR_OP_PASSWORDCHECK` | 密码校验错误 |
| 66515 | `ENUM_ERR_OP_INVALID_DATA` | 下单参数有误（← MT4 `RET_INVALID_DATA`） |
| 66516 | `ENUM_ERR_OP_TRADE_TIMEOUT` | 超时（← MT4 `RET_TRADE_TIMEOUT`，网络类） |
| 66517 | `ENUM_ERR_OP_TRADE_BAD_PRICES` | 价格错误（← `RET_TRADE_BAD_PRICES`） |
| 66518 | `ENUM_ERR_OP_TRADE_BAD_STOPS` | 无效的止盈止损（← `RET_TRADE_BAD_STOPS`） |
| 66519 | `ENUM_ERR_OP_TRADE_BAD_VOLUME` | 下单手数不合法（← `RET_TRADE_BAD_VOLUME`） |
| 66520 | `ENUM_ERR_OP_TRADE_MARKET_CLOSED` | 市场关闭（← `RET_TRADE_MARKET_CLOSED`） |
| 66521 | `ENUM_ERR_OP_TRADE_DISABLE` | 交易被禁止（← `RET_TRADE_DISABLE`） |
| 66522 | `ENUM_ERR_OP_TRADE_NO_MONEY` | 保证金不足（← `RET_TRADE_NO_MONEY`） |
| 66523 | `ENUM_ERR_OP_TRADE_PRICE_CHANGED` | 价格变更（← `RET_TRADE_PRICE_CHANGED`） |
| 66524 | `ENUM_ERR_OP_TRADE_OFFQUOTES` | 没有报价（← `RET_TRADE_OFFQUOTES`） |
| 66525 | `ENUM_ERR_OP_TRADE_BROKER_BUSY` | 交易频繁/broker 忙（← `RET_TRADE_BROKER_BUSY`） |
| 66526 | `ENUM_ERR_OP_TRADE_REQUOTE` | 重新报价（← `RET_TRADE_REQUOTE`） |
| 66527 | `ENUM_ERR_OP_TRADE_ORDER_LOCKED` | Dealer 正在处理订单（← `RET_TRADE_ORDER_LOCKED`） |
| 66528 | `ENUM_ERR_OP_TRADE_LONG_ONLY` | 只允许做多单（← `RET_TRADE_LONG_ONLY`） |
| 66529 | `ENUM_ERR_OP_TRADE_TOO_MANY_REQ` | 请求频繁（← `RET_TRADE_TOO_MANY_REQ`） |
| 66530 | `ENUM_ERR_OP_TRADE_NETWORK_ERROR` | 网络错误（← `RET_NO_CONNECT`） |
| 66531 | `ENUM_ERR_OP_TRADE_UNKNOW_ERROR` | 未知错误 |
| 66532 | `ENUM_ERR_OP_TRADE_OPEN_OK_SLTP_ERROR` | 开仓成功，止盈止损设置失败 |
| 66533 | `ENUM_ERR_OP_TRADE_NOT_ENOUGH_RIGHTS` | 没有足够的权限（← `RET_NOT_ENOUGH_RIGHTS`） |
| 66534 | `ENUM_ERR_OP_TRADE_USER_DISABLE` | 用户被禁用，禁止开仓 |
| 66535 | `ENUM_ERR_OP_CALL_MANAGERRIGHTS` | 获取 manager 权限失败 |
| 66536 | `ENUM_ERR_OP_GET_USERGROUP` | 获取用户组信息失败 |
| 66537 | `ENUM_ERR_OP_USER_READONLY` | 用户只读 |
| 66538 | `ENUM_ERR_OP_USERGROUP_DISABLE` | 用户组被禁用 |
| 66539 | `ENUM_ERR_OP_SYMBOL_NOT_TRADE` | 该品种不可交易 |
| 66540 | `ENUM_ERR_OR_GET_SYMBOL` | 获取品种信息失败 |
| 66541 | `ENUM_ERR_OR_MANAGER_NULL` | manager 为空 |
| 66542 | `ENUM_ERR_OP_CALL_USERGET` | 获取用户失败（UsersGet） |
| 66543 | `ENUM_ERR_OP_LOGIN_EXIST` | login 已存在 |
| 66544 | `ENUM_ERR_OP_GET_ALL_GROUP` | 获取全部组失败 |
| 66545 | `ENUM_ERR_OP_CALL_USERRECORDNEW` | 新建用户失败 |
| 66546 | `ENUM_ERR_OP_GET_GROUP` | 获取组失败 |
| 66547 | `ENUM_ERR_OP_CALL_MARGINLEVELREQUEST` | 获取用户资金失败 |
| 66548 | `ENUM_ERR_OP_CALL_TRADE_OKNONE` | 开仓成功，但未返回订单号（← `RET_OK_NONE`） |
| 66549 | `ENUM_ERR_OP_TRADE_UPDATE_ORDER` | 错误的修改订单参数 |
| 66550 | `ENUM_ERR_OP_TRADE_DELETE_CMD` | 错误的撤单类型 |
| 66551 | `ENUM_ERR_OP_CALL_MT4_CHARTTREQUEST` | K 线图查询请求失败 |
| 66552 | `ENUM_ERR_OP_CALL_MT4_SYMBOLTICK` | 批量报价查询请求参数错误 |
| 66553 | `ENUM_ERR_OP_CALL_MT4_MTLOG` | 获取 MT 日志失败 |
| 66554 | `ENUM_ERR_OP_GET_TICK_INFO` | 获取 tick 信息失败 |
| 66555 | `ENUM_ERR_OP_GET_HOLIDAY` | 获取 holiday 信息失败 |
| 66556 | `ENUM_ERR_OP_LOGIN_RANGE_EXHAUSTED` | 指定范围内的所有账号都已被使用 |

### 2.4 MT4 原生码 → OCS 码的映射（`CMT4ParaData::GetErrorInfo`）
`MT4ParaData.cpp:94` 在交易接口（`TradeTransaction`）返回非 `RET_OK` 时，把 MT4 平台的 `RET_*` 翻译为上面 66515~66548 段的 OCS 码；`strRetErrorInfo` 取自 `pManagerServer->ErrorDescription(nMT4Code)`。

| MT4 原生码 | → OCS 码 |
|-----------|---------|
| `RET_INVALID_DATA` | 66515 `ENUM_ERR_OP_INVALID_DATA` |
| `RET_NOT_ENOUGH_RIGHTS` | 66533 `..._NOT_ENOUGH_RIGHTS` |
| `RET_TRADE_TIMEOUT` | 66516 `..._TRADE_TIMEOUT` |
| `RET_TRADE_BAD_PRICES` | 66517 `..._TRADE_BAD_PRICES` |
| `RET_TRADE_BAD_STOPS` | 66518 `..._TRADE_BAD_STOPS` |
| `RET_TRADE_BAD_VOLUME` | 66519 `..._TRADE_BAD_VOLUME` |
| `RET_TRADE_MARKET_CLOSED` | 66520 `..._TRADE_MARKET_CLOSED` |
| `RET_TRADE_DISABLE` | 66521 `..._TRADE_DISABLE` |
| `RET_TRADE_NO_MONEY` | 66522 `..._TRADE_NO_MONEY` |
| `RET_TRADE_PRICE_CHANGED` | 66523 `..._TRADE_PRICE_CHANGED` |
| `RET_TRADE_OFFQUOTES` | 66524 `..._TRADE_OFFQUOTES` |
| `RET_TRADE_BROKER_BUSY` | 66525 `..._TRADE_BROKER_BUSY` |
| `RET_TRADE_REQUOTE` | 66526 `..._TRADE_REQUOTE` |
| `RET_TRADE_ORDER_LOCKED` | 66527 `..._TRADE_ORDER_LOCKED` |
| `RET_TRADE_LONG_ONLY` | 66528 `..._TRADE_LONG_ONLY` |
| `RET_TRADE_TOO_MANY_REQ` | 66529 `..._TRADE_TOO_MANY_REQ` |
| `RET_NO_CONNECT` | 66530 `..._TRADE_NETWORK_ERROR` |
| `RET_OK_NONE` | 66548 `..._CALL_TRADE_OKNONE` |
| **其它（default）** | **原样返回 `nMT4Code`**（即直接透传 MT4 平台码，见下方注意） |

> ⚠️ **注意：default 分支会把未列出的 MT4 原生码原样透传给上层**（`nSystemCode = nMT4Code`）。
> 因此上层有时会收到非 66xxx 段的码（如 128~150 的 `RET_TRADE_*`、或 0~66 的通用码），需对照 [`mt-returncode.md`](./mt-returncode.md) 解读。

**网络类判定 `CMT4ParaData::IsNetworkError`**（`MT4ParaData.cpp:162`）：当 MT 码为
`RET_NO_CONNECT` / `RET_TRADE_TIMEOUT` / `RET_BAD_ACCOUNT_INFO` / `RET_ERROR`
时视为网络错误，`SetCodeAPI` 的 `flag` 置 `true`，触发重连检查。

---

## 3. MT5 OCS 业务层错误码

### 3.1 前端固定判断码（`ENUM_ERR_MT5_CODE`）
| 码值 | 名称 | 说明 |
|------|------|------|
| 0 | `ENUM_ERR_MT5_OK` | 成功 |
| 66534 | `ENUM_ERR_MT5_OP_USER_DISABLE` | 用户禁用（intrade 指定使用） |
| 66537 | `ENUM_ERR_MT5_OP_TRADE_USER_DISABLE` | 用户交易被禁用（intrade 指定使用） |
| 68302 | `ENUM_ERR_MT5_OP_LOGIN_NOT_EXIST` | 用户账号不存在 |

### 3.2 参数错误（66400 段）`ENUM_MT5_ERR_CODE`
| 码值 | 名称 | 说明 |
|------|------|------|
| 66400 | `ENUM_MT5_ERR_PARA` | 参数错误 |
| 66401 | `ENUM_MT5_ERR_PARA_PARABUFF` | JSON 数据解析错误 |
| 66402 | `ENUM_MT5_ERR_PARA_REQUEST_ID` | 请求 ID 错误 |
| 66403 | `ENUM_MT5_ERR_PARA_REQUEST_CMD` | 请求 CMD 错误 |
| 66404 | `ENUM_MT5_ERR_PARA_LOGIN` | Login 错误 |
| 66405 | `ENUM_MT5_ERR_PARA_SYMBOL` | symbol 错误 |
| 66406 | `ENUM_MT5_ERR_PARA_TRADE_CMD` | 订单 CMD 错误 |
| 66407 | `ENUM_MT5_ERR_PARA__CMD_VALUE` | 订单 CMD 值错误 |
| 66408 | `ENUM_MT5_ERR_PARA_VOLUME` | 订单量错误 |
| 66409 | `ENUM_MT5_ERR_PARA_SL` | 订单止损错误 |
| 66410 | `ENUM_MT5_ERR_PARA_TP` | 订单止盈错误 |
| 66411 | `ENUM_MT5_ERR_PARA_EXPIRATION_TIME` | 订单过期时间错误 |
| 66412 | `ENUM_MT5_ERR_PARA_COMMENT` | 订单注释错误 |
| 66413 | `ENUM_MT5_ERR_PARA_PENDING_PRICE` | 订单挂单价格错误 |
| 66414 | `ENUM_MT5_ERR_PARA_ORDER` | 订单号错误 |
| 66415 | `ENUM_MT5_ERR_PARA_PASSWORD` | 密码错误 |
| 66416 | `ENUM_MT5_ERR_PARA_FOLLOW_ID` | 批量操作 ID 错误 |
| 66417 | `ENUM_MT5_ERR_PARA_CLOSE_VOLUME_BELOW_0` | 平仓手数小于 0 |
| 66418 | `ENUM_MT5_ERR_PARA_SERVER_ID` | Server id 错误 |
| 66419 | `ENUM_MT5_ERR_PARA_NAME` | 用户名错误 |
| 66420 | `ENUM_MT5_ERR_PARA_GROUP` | 用户组错误 |
| 66421 | `ENUM_MT5_ERR_PARA_INVESTOR_PWD` | 投资人密码错误 |
| 66422 | `ENUM_MT5_ERR_PARA_LEVERAGE` | 杠杆错误 |
| 66423 | `ENUM_MT5_ERR_PARA_EMAIL` | 邮箱错误 |
| 66424 | `ENUM_MT5_ERR_PARA_PHONE_PWD` | 手机密码错误 |
| 66425 | `ENUM_MT5_ERR_PARA_COUNTRY` | 国家错误 |
| 66426 | `ENUM_MT5_ERR_PARA_STATE` | 省份错误 |
| 66427 | `ENUM_MT5_ERR_PARA_CITY` | 城市错误 |
| 66428 | `ENUM_MT5_ERR_PARA_ADDRESS` | 地址错误 |
| 66429 | `ENUM_MT5_ERR_PARA_PHONE` | 手机号码错误 |
| 66430 | `ENUM_MT5_ERR_PARA_STATUS` | 用户身份错误 |
| 66431 | `ENUM_MT5_ERR_PARA_ZIP_CODE` | 邮编错误 |
| 66432 | `ENUM_MT5_ERR_PARA_ID_NUMBER` | id 错误 |
| 66433 | `ENUM_MT5_ERR_PARA_AGENT_ACCOUNT` | 代理错误 |
| 66434 | `ENUM_MT5_ERR_PARA_LEAD_SOURCE` | 注册来源错误 |
| 66435 | `ENUM_MT5_ERR_PARA_READ_ONLY` | 是否只读错误 |
| 66436 | `ENUM_MT5_ERR_PARA_CHANGE_PWD` | 是否允许修改密码错误 |
| 66437 | `ENUM_MT5_ERR_PARA_ENABLE` | 是否启用错误 |
| 66438 | `ENUM_MT5_ERR_PARA_DEFAULT_DEPOSIT` | 默认入金参数错误 |
| 66439 | `ENUM_MT5_ERR_PARA_DEFAULT_WITHDRAWAL` | 默认出金参数错误 |
| 66440 | `ENUM_MT5_ERR_OP_WITHDRAWAL_BELOW_0` | 出金金额小于 0 |
| 66441 | `ENUM_MT5_ERR_OP_NOT_ENOUGH_MONEY_WITHDRAWAL` | 没有足够的钱出金 |
| 66442 | `ENUM_MT5_ERR_OP_COMMON_ERROR` | 公共错误（代码中需把详细信息返回） |
| 66443 | `ENUM_MT5_ERR_OP_MULTI_OVER` | 批量操作数据超过限制值 |

### 3.3 业务/交易错误（66500 段）`ENUM_MT5_ERR_CODE`
| 码值 | 名称 | 说明 |
|------|------|------|
| 66500 | `ENUM_MT5_ERR_OP_UNKNOWCMD` | 命令错误 |
| 66501 | `ENUM_MT5_ERR_OP_CONNECTED_SERVER` | 连接错误 |
| 66502 | `ENUM_MT5_ERR_OP_LOGIN_NOT_EXIST` | 用户 ID 不存在 |
| 66503 | `ENUM_MT5_ERR_OP_GET_CURRENT_PRICES` | 获取现价错误 |
| 66504 | `ENUM_MT5_ERR_OP_CALL_TRADETRANSACTION` | 调用 TradeTransaction 失败 |
| 66505 | `ENUM_MT5_ERR_OP_GET_ORDER` | 订单查询不到 |
| 66506 | `ENUM_MT5_ERR_OP_LOGIN_NOT_MACH_ORDER` | 订单的用户 ID 不匹配 |
| 66507 | `ENUM_MT5_ERR_OP_ORDER_CLOSED` | 订单已经被平仓过 |
| 66508 | `ENUM_MT5_ERR_OP_MULTI_NEW_ORDER_200` | 批量开仓大于 200 |
| 66509 | `ENUM_MT5_ERR_OP_MULTI_NEW_ORDER_SIZE` | 批量开仓数据为 0 |
| 66510 | `ENUM_MT5_ERR_OP_MULTI_NEW_ORDER_PART_FAILED` | 批量开仓部分操作错误 |
| 66511 | `ENUM_MT5_ERR_OP_MULTI_CLOSE_ORDER_PART_FAILED` | 批量平仓部分操作错误 |
| 66512 | `ENUM_MT5_ERR_OP_GET_PRICE` | 获取报价失败 |
| 66513 | `ENUM_MT5_ERR_OP_LOGIN_BELOW_0` | 用户 ID 小于等于 0 |
| 66514 | `ENUM_MT5_ERR_OP_PASSWORDCHECK` | 密码校验错误 |
| 66515 | `ENUM_MT5_ERR_OP_INVALID_DATA` | 下单参数有误 |
| 66516 | `ENUM_MT5_ERR_OP_TRADE_TIMEOUT` | 超时 |
| 66517 | `ENUM_MT5_ERR_OP_TRADE_BAD_PRICES` | 价格错误 |
| 66518 | `ENUM_MT5_ERR_OP_TRADE_BAD_STOPS` | 无效的止盈止损 |
| 66519 | `ENUM_MT5_ERR_OP_TRADE_BAD_VOLUME` | 下单手数不合法 |
| 66520 | `ENUM_MT5_ERR_OP_TRADE_MARKET_CLOSED` | 市场关闭 |
| 66521 | `ENUM_MT5_ERR_OP_TRADE_DISABLE` | 交易被禁止 |
| 66522 | `ENUM_MT5_ERR_OP_TRADE_NO_MONEY` | 保证金不足 |
| 66523 | `ENUM_MT5_ERR_OP_TRADE_PRICE_CHANGED` | 价格变更 |
| 66524 | `ENUM_MT5_ERR_OP_TRADE_OFFQUOTES` | 没有报价 |
| 66525 | `ENUM_MT5_ERR_OP_TRADE_BROKER_BUSY` | 交易频繁/broker 忙 |
| 66526 | `ENUM_MT5_ERR_OP_TRADE_REQUOTE` | 重新报价 |
| 66527 | `ENUM_MT5_ERR_OP_TRADE_ORDER_LOCKED` | Dealer 正在处理订单 |
| 66528 | `ENUM_MT5_ERR_OP_TRADE_LONG_ONLY` | 只允许做多单 |
| 66529 | `ENUM_MT5_ERR_OP_TRADE_TOO_MANY_REQ` | 请求频繁 |
| 66530 | `ENUM_MT5_ERR_OP_TRADE_NETWORK_ERROR` | 网络错误 |
| 66531 | `ENUM_MT5_ERR_OP_TRADE_UNKNOW_ERROR` | 未知错误 |
| 66532 | `ENUM_MT5_ERR_OP_TRADE_OPEN_OK_SLTP_ERROR` | 开仓成功，止盈止损设置失败 |
| 66533 | `ENUM_MT5_ERR_OP_TRADE_NOT_ENOUGH_RIGHTS` | 没有足够的权限 |
| 66534 | `ENUM_MT5_ERR_OP_TRADE_USER_DISABLE` | 用户被禁用，禁止开仓 |
| 66535 | `ENUM_MT5_ERR_OP_CALL_MANAGERRIGHTS` | 获取 manager 权限失败 |
| 66536 | `ENUM_MT5_ERR_OP_GET_USERGROUP` | 获取用户组信息失败 |
| 66537 | `ENUM_MT5_ERR_OP_USER_READONLY` | 用户只读 |
| 66538 | `ENUM_MT5_ERR_OP_USERGROUP_DISABLE` | 用户组被禁用 |
| 66539 | `ENUM_MT5_ERR_OP_SYMBOL_NOT_TRADE` | 该品种不可交易 |
| 66540 | `ENUM_MT5_ERR_OR_GET_SYMBOL` | 获取品种信息失败 |
| 66541 | `ENUM_MT5_ERR_OR_MANAGER_NULL` | manager 为空 |
| 66542 | `ENUM_MT5_ERR_OP_CALL_USERGET` | 获取用户失败（UsersGet） |
| 66543 | `ENUM_MT5_ERR_OP_LOGIN_EXIST` | login 已存在 |
| 66544 | `ENUM_MT5_ERR_OP_GET_ALL_GROUP` | 获取全部组失败 |
| 66545 | `ENUM_MT5_ERR_OP_CALL_USERRECORDNEW` | 新建用户失败 |
| 66546 | `ENUM_MT5_ERR_OP_GET_GROUP` | 获取组失败 |
| 66547 | `ENUM_MT5_ERR_OP_CALL_MARGINLEVELREQUEST` | 获取用户资金失败 |
| 66548 | `ENUM_MT5_ERR_OP_CALL_TRADE_OKNONE` | 开仓成功，但未返回订单号 |
| 66549 | `ENUM_MT5_ERR_OP_TRADE_UPDATE_ORDER` | 错误的修改订单参数 |
| 66550 | `ENUM_MT5_ERR_OP_TRADE_DELETE_CMD` | 错误的撤单类型 |
| 66551 | `ENUM_MT5_ERR_PARA_DEPOSIT` | 入金金额错误 |
| 66552 | `ENUM_MT5_ERR_OP_DEPOSIT_BELOW_0` | 入金金额小于 0 |
| 66556 | `ENUM_MT5_ERR_OP_LOGIN_RANGE_EXHAUSTED` | 指定范围内的所有账号都已被使用 |

### 3.4 MT5 专属 API 调用错误（66700 段）`ENUM_MT5_ERR_CODE`
| 码值 | 名称 | 说明 |
|------|------|------|
| 66700 | `ENUM_MT5_ERR_PARA_START` | MT5 错误码段起始 |
| 66701 | `ENUM_MT5_ERR_OP_CALL_UNKNOWCMD` | MT5 未知错误 |
| 66702 | `ENUM_MT5_ERR_OP_CALL_USERCREATE` | 创建用户对象失败 |
| 66703 | `ENUM_MT5_ERR_OP_CALL_USERADD` | 添加用户失败（UserAdd） |
| 66704 | `ENUM_MT5_ERR_OP_CALL_USERCREATEACCOLUNT` | 创建交易用户对象失败 |
| 66705 | `ENUM_MT5_ERR_OP_CALL_USERPWDCHANGE` | 修改用户密码失败（UserPasswordChange） |
| 66706 | `ENUM_MT5_ERR_OP_CALL_DEALERBALANCE` | 操作用户资金失败（DealerBalance） |
| 66707 | `ENUM_MT5_ERR_OP_CALL_USERACCOUNTREQUEST` | 请求用户资金信息失败（UserAccountRequest） |
| 66708 | `ENUM_MT5_ERR_OP_CALL_ONLINECREATE` | 创建在线对象失败（OnlineCreate） |
| 66709 | `ENUM_MT5_ERR_OP_CALL_GROUPCREATE` | 创建用户组对象失败（GroupCreate） |
| 66710 | `ENUM_MT5_ERR_OP_CALL_DEALERSEND` | 调用 DealerSend 失败 |
| 66711 | `ENUM_MT5_ERR_OP_CALL_GETPOSITION` | 获取持仓失败 |
| 66712 | `EBUM_MT5_ERR_OP_CALL_TICKLAST` | 调用 TickLast 失败 *(原名拼写为 EBUM)* |
| 66713 | `ENUM_MT5_ERR_PROCESS` | API 错误 |
| 66714 | `ENUM_MT5_ERR_OP_CALL_REQUEST` | 创建请求对象失败（RequestCreate） |
| 66715 | `ENUM_MT5_ERR_OP_CALL_POSITIONCREATEARRAY` | PositionCreateArray 调用失败 |
| 66716 | `ENUM_MT5_ERR_OP_CALL_POSITIONGET` | PositionGet 调用失败 |
| 66717 | `ENUM_MT5_ERR_OP_CALL_POSITIONCREATE` | PositionCreate 调用失败 |
| 66718 | `ENUM_MT5_ERR_OP_CALL_ACCOUNTCREATE` | UserCreateAccount 调用失败 |
| 66719 | `ENUM_MT5_ERR_OP_CALL_ACCOUNTREQUEST` | UserAccountRequest 调用失败 |
| 66720 | `ENUM_MT5_ERR_OP_CALL_ORDERCREATE` | OrderCreate 调用失败 |
| 66721 | `ENUM_MT5_ERR_OP_CALL_ORDERGTE` | OrderGet 调用失败 |
| 66722 | `ENUM_MT5_ERR_OP_CALL_SYMBOLTOTAL` | SymbolTotal 调用失败 |
| 66723 | `ENUM_MT5_ERR_OP_CALL_CHARTTREQUEST` | ChartRequest 调用失败 |
| 66724 | `ENUM_MT5_ERR_OP_CALL_DEALREQUEST` | DealRequest 调用失败 |
| 66725 | `ENUM_MT5_ERR_OP_CALL_DEALCREATEARRAY` | DealCreateArray 调用失败 |
| 66726 | `ENUM_MT5_ERR_OP_CALL_TIMECREATE` | TimeCreate 调用失败 |
| 66727 | `ENUM_MT5_ERR_OP_CALL_SYMBOLCREATE` | SymbolCreate 调用失败 |
| 66728 | `ENUM_MT5_ERR_OP_CALL_SYMBOLSESSIONCREATE` | SymbolSessionCreate 调用失败 |
| 66729 | `ENUM_MT5_ERR_OP_CALL_UPDATEACCOUNT` | 更新用户信息调用失败 |

> ⚠️ **已知缺陷（代码原样保留）**：`ENUM_MT5_ERR_OP_CALL_USERCREATEARRAY`（注释「创建用户对象数组失败」）在头文件里被写成 **66702**，与 `ENUM_MT5_ERR_OP_CALL_USERCREATE` 重复——同一码值对应两个枚举名。排查时请以代码上下文区分。

### 3.5 MT5 原生码透传
MT5 业务层 **没有** 像 MT4 那样的集中式 `GetErrorInfo` 翻译表。交易链路（`MT5TradeRequestHandle.cpp`）在多处 **直接把 MT5 平台码 `MT_RET_*` 写入 `SetCode`**，例如：
- 成功判定：`MT_RET_REQUEST_DONE`（10009）；
- 在途/挂单：`MT_RET_REQUEST_PLACED`（10008）；
- 撤单/拒单：`MT_RET_REQUEST_CANCEL`（10007）、`MT_RET_REQUEST_REJECT`（10006）。

因此上层经常会直接收到 **10001~11002 段的 MT5 原生码**，需对照 [`mt-returncode.md`](./mt-returncode.md) 第 2 节解读。

---

## 4. 排查建议

1. **先看码段**：66400/66500/66700 → OCS 自定义码（查本文）；0~150、1000~16021、10001~11002 → MT 平台原生码（查 `mt-returncode.md`）。
2. **MT4**：交易失败的具体原因优先看 `strCodeDesc`（含 `ErrorDescription(MtCode)` 文本）及映射前的 MT4 原始码。
3. **MT5**：交易类返回常为原生 `MT_RET_REQUEST_*`，直接按平台语义解读。
4. **`bIsApiError=true`**（网络/连接类）会触发 manager 重连，频繁出现需排查与 MT 服务器的连接质量。

---

*生成日期：2026-06-12 ｜ 数据来源：`src/ocs/MT4/MT4ParaData.{h,cpp}`、`src/ocs/MT5/MT5ParaData.h`、`src/ocs/MT5/MT5TradeRequestHandle.cpp`*
