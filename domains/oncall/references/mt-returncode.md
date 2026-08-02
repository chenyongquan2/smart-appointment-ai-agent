# MT4 / MT5 平台 API 返回码（Return Code）

> 本文整理 **MetaTrader 平台 API 原生返回码**：
> - **MT4 Manager API**：`RET_*` 枚举（`MT4ManagerAPI.h`，SDK 版本 1430）
> - **MT5 API**：`MT_RET_*` 枚举 `EnMTAPIRetCode`（`MT5APIConstants.h`，SDK 版本约 5430+，枚举跨版本稳定）
>
> 这些是 MT 平台/服务器直接返回的码，OCS 业务层在交易链路中会 **透传或翻译** 这些码。OCS 自定义的 66xxx 段错误码见 [`ocs4-returncode.md`](./ocs4-returncode.md)。
>
> 取文本描述：MT4 用 `CManagerInterface::ErrorDescription(code)`；MT5 用 `SMTRetCode::GetError(code)` / `IMTManagerAPI` 相关接口。

---

## 1. MT4 Manager API 返回码（`RET_*`）

`MT4ManagerAPI.h` 中匿名 `enum`，是 `CManagerInterface::TradeTransaction`、`Login`、`UserRecordNew` 等几乎所有接口的统一返回类型。`RET_OK(0)` 表示成功，其余为错误或状态码。

### 1.1 通用错误（0 ~ 15）
| 码值 | 名称 | 说明 |
|------|------|------|
| 0 | `RET_OK` | 成功，一切正常 |
| 1 | `RET_OK_NONE` | 成功，但无操作 / 无数据（OCS 视为"开仓成功未返回订单号"） |
| 2 | `RET_ERROR` | 通用错误（OCS 视为网络类错误） |
| 3 | `RET_INVALID_DATA` | 无效数据 |
| 4 | `RET_TECH_PROBLEM` | 服务器技术故障 |
| 5 | `RET_OLD_VERSION` | 客户端版本过旧 |
| 6 | `RET_NO_CONNECT` | 无连接（网络类错误） |
| 7 | `RET_NOT_ENOUGH_RIGHTS` | 权限不足 |
| 8 | `RET_TOO_FREQUENT` | 访问服务器过于频繁 |
| 9 | `RET_MALFUNCTION` | 操作异常/故障 |
| 10 | `RET_GENERATE_KEY` | 需要发送公钥 |
| 11 | `RET_SECURITY_SESSION` | 安全会话已开始 |
| 15 | `RET_INVALID_COMPANY` | 公司名不属于该 license 或白标 |

### 1.2 账号状态（64 ~ 66）
| 码值 | 名称 | 说明 |
|------|------|------|
| 64 | `RET_ACCOUNT_DISABLED` | 账号被封禁 |
| 65 | `RET_BAD_ACCOUNT_INFO` | 账号信息错误（网络类错误） |
| 66 | `RET_PUBLIC_KEY_MISSING` | 缺少公钥 |

### 1.3 交易（128 ~ 141）
| 码值 | 名称 | 说明 |
|------|------|------|
| 128 | `RET_TRADE_TIMEOUT` | 交易事务超时（网络类错误） |
| 129 | `RET_TRADE_BAD_PRICES` | 订单价格错误 |
| 130 | `RET_TRADE_BAD_STOPS` | 止损/止盈水平无效 |
| 131 | `RET_TRADE_BAD_VOLUME` | 手数错误 |
| 132 | `RET_TRADE_MARKET_CLOSED` | 市场关闭 |
| 133 | `RET_TRADE_DISABLE` | 交易被禁止 |
| 134 | `RET_TRADE_NO_MONEY` | 保证金不足 |
| 135 | `RET_TRADE_PRICE_CHANGED` | 价格已变更 |
| 136 | `RET_TRADE_OFFQUOTES` | 没有报价 |
| 137 | `RET_TRADE_BROKER_BUSY` | broker 忙 |
| 138 | `RET_TRADE_REQUOTE` | 重新报价 |
| 139 | `RET_TRADE_ORDER_LOCKED` | 订单正被 dealer 处理，无法修改 |
| 140 | `RET_TRADE_LONG_ONLY` | 仅允许买单 |
| 141 | `RET_TRADE_TOO_MANY_REQ` | 单客户端请求过多 |

### 1.4 订单状态通知（142 ~ 144）
| 码值 | 名称 | 说明 |
|------|------|------|
| 142 | `RET_TRADE_ACCEPTED` | 请求已被服务器接受并进入请求队列（OCS 据此触发回查重试） |
| 143 | `RET_TRADE_PROCESS` | 请求已被 dealer 接受处理中 |
| 144 | `RET_TRADE_USER_CANCEL` | 请求被客户端取消 |

### 1.5 附加返回码（145 ~ 150）
| 码值 | 名称 | 说明 |
|------|------|------|
| 145 | `RET_TRADE_MODIFY_DENIED` | 订单修改被拒绝 |
| 146 | `RET_TRADE_CONTEXT_BUSY` | 交易上下文忙（客户端终端用） |
| 147 | `RET_TRADE_EXPIRATION_DENIED` | 不允许使用过期时间 |
| 148 | `RET_TRADE_TOO_MANY_ORDERS` | 订单过多 |
| 149 | `RET_TRADE_HEDGE_PROHIBITED` | 禁止对冲 |
| 150 | `RET_TRADE_PROHIBITED_BY_FIFO` | 被 FIFO 规则禁止 |

> **OCS 关联**：交易接口返回的 `RET_*`，OCS 会在 `CMT4ParaData::GetErrorInfo` 中翻译为 66515~66548 段码（详见 `ocs4-returncode.md` §2.4）。未被翻译的码（如 142~150、64~66）会被原样透传给上层。

---

## 2. MT5 API 返回码（`MT_RET_*` / `EnMTAPIRetCode`）

`MT5APIConstants.h` 中的 `enum EnMTAPIRetCode`。按功能域分段编号，OCS 交易链路常 **直接透传** 10001~11002 段（请求结果码）。

### 2.1 通用结果（0 ~ 17）
| 码值 | 名称 | 说明 |
|------|------|------|
| 0 | `MT_RET_OK` | 成功 |
| 1 | `MT_RET_OK_NONE` | 成功，无数据 |
| 2 | `MT_RET_ERROR` | 通用错误 |
| 3 | `MT_RET_ERR_PARAMS` | 参数无效 |
| 4 | `MT_RET_ERR_DATA` | 数据无效 |
| 5 | `MT_RET_ERR_DISK` | 磁盘错误 |
| 6 | `MT_RET_ERR_MEM` | 内存错误 |
| 7 | `MT_RET_ERR_NETWORK` | 网络错误 |
| 8 | `MT_RET_ERR_PERMISSIONS` | 权限不足 |
| 9 | `MT_RET_ERR_TIMEOUT` | 操作超时 |
| 10 | `MT_RET_ERR_CONNECTION` | 无连接 |
| 11 | `MT_RET_ERR_NOSERVICE` | 服务不可用 |
| 12 | `MT_RET_ERR_FREQUENT` | 请求过于频繁 |
| 13 | `MT_RET_ERR_NOTFOUND` | 未找到 |
| 14 | `MT_RET_ERR_PARTIAL` | 部分错误 |
| 15 | `MT_RET_ERR_SHUTDOWN` | 服务器正在关闭 |
| 16 | `MT_RET_ERR_CANCEL` | 操作被取消 |
| 17 | `MT_RET_ERR_DUPLICATE` | 数据重复 |

### 2.2 认证/连接（1000 ~ 1034）
| 码值 | 名称 | 说明 |
|------|------|------|
| 1000 | `MT_RET_AUTH_CLIENT_INVALID` | 终端类型无效 |
| 1001 | `MT_RET_AUTH_ACCOUNT_INVALID` | 账号无效 |
| 1002 | `MT_RET_AUTH_ACCOUNT_DISABLED` | 账号被禁用 |
| 1003 | `MT_RET_AUTH_ADVANCED` | 需要高级授权 |
| 1004 | `MT_RET_AUTH_CERTIFICATE` | 需要证书 |
| 1005 | `MT_RET_AUTH_CERTIFICATE_BAD` | 证书无效 |
| 1006 | `MT_RET_AUTH_NOTCONFIRMED` | 证书未确认 |
| 1007 | `MT_RET_AUTH_SERVER_INTERNAL` | 试图连接非接入服务器 |
| 1008 | `MT_RET_AUTH_SERVER_BAD` | 服务器未认证 |
| 1009 | `MT_RET_AUTH_UPDATE_ONLY` | 仅有更新可用 |
| 1010 | `MT_RET_AUTH_CLIENT_OLD` | 客户端版本过旧 |
| 1011 | `MT_RET_AUTH_MANAGER_NOCONFIG` | manager 账号无 manager 配置 |
| 1012 | `MT_RET_AUTH_MANAGER_IPBLOCK` | manager IP 不被允许 |
| 1013 | `MT_RET_AUTH_GROUP_INVALID` | 组未初始化（需重启服务器） |
| 1014 | `MT_RET_AUTH_CA_DISABLED` | 证书生成被禁用 |
| 1015 | `MT_RET_AUTH_INVALID_ID` | server id 无效或禁用 |
| 1016 | `MT_RET_AUTH_INVALID_IP` | 地址不被允许 |
| 1017 | `MT_RET_AUTH_INVALID_TYPE` | 服务器类型无效 |
| 1018 | `MT_RET_AUTH_SERVER_BUSY` | 服务器忙 |
| 1019 | `MT_RET_AUTH_SERVER_CERT` | 服务器证书无效 |
| 1020 | `MT_RET_AUTH_ACCOUNT_UNKNOWN` | 未知账号 |
| 1021 | `MT_RET_AUTH_SERVER_OLD` | 服务器版本过旧 |
| 1022 | `MT_RET_AUTH_SERVER_LIMIT` | license 限制无法连接 |
| 1023 | `MT_RET_AUTH_MOBILE_DISABLED` | license 不允许移动端连接 |
| 1024 | `MT_RET_AUTH_MANAGER_TYPE` | manager 不允许该连接类型 |
| 1025 | `MT_RET_AUTH_DEMO_DISABLED` | demo 分配被禁用 |
| 1026 | `MT_RET_AUTH_RESET_PASSWORD` | 必须修改主密码 |
| 1027 | `MT_RET_AUTH_OTP_INVALID` | 一次性密码无效 |
| 1028 | `MT_RET_AUTH_OTP_NEED_SECRET` | 需要一次性密码密钥 |
| 1029 | `MT_RET_AUTH_MIGRATION_MT4` | 需要 MT4 密码迁移 |
| 1030 | `MT_RET_AUTH_MIGRATION_MT5` | 需要 MT5 密码迁移 |
| 1031 | `MT_RET_AUTH_INVALID_VERIFY` | 确认码无效或过期 |
| 1032 | `MT_RET_AUTH_VERIFY_BAD_EMAIL` | 邮件验证码无法发送 |
| 1033 | `MT_RET_AUTH_VERIFY_BAD_PHONE` | 手机验证码无法发送 |
| 1034 | `MT_RET_AUTH_API_DISABLED` | 账号 API 连接被禁用 |

### 2.3 配置（2000 ~ 2021）
| 码值 | 名称 | 说明 |
|------|------|------|
| 2000 | `MT_RET_CFG_LAST_ADMIN` | 删除最后一个 admin 配置 |
| 2001 | `MT_RET_CFG_LAST_ADMIN_GROUP` | 最后一个 admin 组不能删除 |
| 2003 | `MT_RET_CFG_NOT_EMPTY` | 组/品种中仍有账户或交易 |
| 2004 | `MT_RET_CFG_INVALID_RANGE` | 账户或交易范围无效 |
| 2005 | `MT_RET_CFG_NOT_MANAGER_LOGIN` | manager 账号不属于 manager 组 |
| 2006 | `MT_RET_CFG_BUILTIN` | 内置受保护配置 |
| 2007 | `MT_RET_CFG_DUPLICATE` | 配置重复 |
| 2008 | `MT_RET_CFG_LIMIT_REACHED` | 配置数量达到上限 |
| 2009 | `MT_RET_CFG_NO_ACCESS_TO_MAIN` | 网络配置无效 |
| 2010 | `MT_RET_CFG_DEALER_ID_EXIST` | 相同 ID 的 dealer 已存在 |
| 2011 | `MT_RET_CFG_BIND_ADDR_EXIST` | 绑定地址已存在 |
| 2012 | `MT_RET_CFG_WORKING_TRADE` | 试图删除运行中的交易服务器 |
| 2013 | `MT_RET_CFG_GATEWAY_NAME_EXIST` | 相同名称的 gateway 已存在 |
| 2014 | `MT_RET_CFG_SWITCH_TO_BACKUP` | 服务器必须切换到备份模式 |
| 2015 | `MT_RET_CFG_NO_BACKUP_MODULE` | 缺少备份服务器模块 |
| 2016 | `MT_RET_CFG_NO_TRADE_MODULE` | 缺少交易服务器模块 |
| 2017 | `MT_RET_CFG_NO_HISTORY_MODULE` | 缺少历史服务器模块 |
| 2018 | `MT_RET_CFG_ANOTHER_SWITCH` | 另一切换过程进行中 |
| 2019 | `MT_RET_CFG_NO_LICENSE_FILE` | 缺少 license 文件 |
| 2020 | `MT_RET_CFG_GATEWAY_LOGIN_EXIST` | 相同 login 的 gateway 已存在 |
| 2021 | `MT_RET_CFG_INVALID_COMPANY` | 公司名不属于该 license 或白标 |

### 2.4 用户（3001 ~ 3019）
| 码值 | 名称 | 说明 |
|------|------|------|
| 3001 | `MT_RET_USR_LAST_ADMIN` | 删除最后一个 admin 账号 |
| 3002 | `MT_RET_USR_LOGIN_EXHAUSTED` | login 范围已耗尽 |
| 3003 | `MT_RET_USR_LOGIN_PROHIBITED` | login 已被其它服务器保留 |
| 3004 | `MT_RET_USR_LOGIN_EXIST` | 账号已存在 |
| 3005 | `MT_RET_USR_SUICIDE` | 试图自删除 |
| 3006 | `MT_RET_USR_INVALID_PASSWORD` | 账号密码无效 |
| 3007 | `MT_RET_USR_LIMIT_REACHED` | 用户数量达到上限 |
| 3008 | `MT_RET_USR_HAS_TRADES` | 账号有未平仓交易 |
| 3009 | `MT_RET_USR_DIFFERENT_SERVERS` | 试图把账号移到不同服务器 |
| 3010 | `MT_RET_USR_DIFFERENT_CURRENCY` | 试图把账号移到不同币种组 |
| 3011 | `MT_RET_USR_IMPORT_BALANCE` | 账号余额导入错误 |
| 3012 | `MT_RET_USR_IMPORT_GROUP` | 账号导入组无效 |
| 3013 | `MT_RET_USR_ACCOUNT_EXIST` | 账号已存在 |
| 3014 | `MT_RET_USR_IMPORT_ACCOUNT` | 账号交易数据导入错误 |
| 3015 | `MT_RET_USR_IMPORT_POSITIONS` | 账号持仓导入错误 |
| 3016 | `MT_RET_USR_IMPORT_ORDERS` | 账号挂单导入错误 |
| 3017 | `MT_RET_USR_IMPORT_DEALS` | 账号成交历史导入错误 |
| 3018 | `MT_RET_USR_IMPORT_HISTORY` | 账号订单历史导入错误 |
| 3019 | `MT_RET_USR_API_LIMIT_REACHED` | 启用 API 的用户数达到上限 |

### 2.5 交易记录（4001 ~ 4009）
| 码值 | 名称 | 说明 |
|------|------|------|
| 4001 | `MT_RET_TRADE_LIMIT_REACHED` | 订单或成交数量达到上限 |
| 4002 | `MT_RET_TRADE_ORDER_EXIST` | 订单已存在 |
| 4003 | `MT_RET_TRADE_ORDER_EXHAUSTED` | 订单号范围耗尽 |
| 4004 | `MT_RET_TRADE_DEAL_EXHAUSTED` | 成交号范围耗尽 |
| 4005 | `MT_RET_TRADE_MAX_MONEY` | 资金达到上限 |
| 4006 | `MT_RET_TRADE_DEAL_EXIST` | 成交已存在 |
| 4007 | `MT_RET_TRADE_ORDER_PROHIBITED` | 订单号被其它服务器保留 |
| 4008 | `MT_RET_TRADE_DEAL_PROHIBITED` | 成交号被其它服务器保留 |
| 4009 | `MT_RET_TRADE_SPLIT_VOLUME` | 新持仓量小于最小允许量 |

### 2.6 报表（5001 ~ 5008）/ 历史（6001）
| 码值 | 名称 | 说明 |
|------|------|------|
| 5001 | `MT_RET_REPORT_SNAPSHOT` | base 快照错误 |
| 5002 | `MT_RET_REPORT_NOTSUPPORTED` | 该报表不支持此方法 |
| 5003 | `MT_RET_REPORT_NODATA` | 无报表数据 |
| 5004 | `MT_RET_REPORT_TEMPLATE_BAD` | 模板错误 |
| 5005 | `MT_RET_REPORT_TEMPLATE_END` | 模板结束（处理成功） |
| 5006 | `MT_RET_REPORT_INVALID_ROW` | 行大小无效 |
| 5007 | `MT_RET_REPORT_LIMIT_REPEAT` | tag 重复次数达到上限 |
| 5008 | `MT_RET_REPORT_LIMIT_REPORT` | 报表大小达到上限 |
| 6001 | `MT_RET_HST_SYMBOL_NOTFOUND` | 品种未找到，尝试重启历史服务器 |

### 2.7 交易请求结果（10001 ~ 10046）★ OCS 交易链路常透传
| 码值 | 名称 | 说明 |
|------|------|------|
| 10001 | `MT_RET_REQUEST_INWAY` | 请求在途 |
| 10002 | `MT_RET_REQUEST_ACCEPTED` | 请求已接受 |
| 10003 | `MT_RET_REQUEST_PROCESS` | 请求处理中 |
| 10004 | `MT_RET_REQUEST_REQUOTE` | 请求重新报价 |
| 10005 | `MT_RET_REQUEST_PRICES` | 请求报价 |
| 10006 | `MT_RET_REQUEST_REJECT` | 请求被拒绝 |
| 10007 | `MT_RET_REQUEST_CANCEL` | 请求被取消 |
| 10008 | `MT_RET_REQUEST_PLACED` | 请求下的订单已挂出（OCS：在途/挂单，触发回查） |
| 10009 | `MT_RET_REQUEST_DONE` | **请求执行完成（OCS 视为成功）** |
| 10010 | `MT_RET_REQUEST_DONE_PARTIAL` | 请求部分执行 |
| 10011 | `MT_RET_REQUEST_ERROR` | 请求通用错误 |
| 10012 | `MT_RET_REQUEST_TIMEOUT` | 请求超时 |
| 10013 | `MT_RET_REQUEST_INVALID` | 请求无效 |
| 10014 | `MT_RET_REQUEST_INVALID_VOLUME` | 手数无效 |
| 10015 | `MT_RET_REQUEST_INVALID_PRICE` | 价格无效 |
| 10016 | `MT_RET_REQUEST_INVALID_STOPS` | 止损/价格无效 |
| 10017 | `MT_RET_REQUEST_TRADE_DISABLED` | 交易被禁用 |
| 10018 | `MT_RET_REQUEST_MARKET_CLOSED` | 市场关闭 |
| 10019 | `MT_RET_REQUEST_NO_MONEY` | 资金不足 |
| 10020 | `MT_RET_REQUEST_PRICE_CHANGED` | 价格已变更 |
| 10021 | `MT_RET_REQUEST_PRICE_OFF` | 无报价 |
| 10022 | `MT_RET_REQUEST_INVALID_EXP` | 订单过期时间无效 |
| 10023 | `MT_RET_REQUEST_ORDER_CHANGED` | 订单已被修改 |
| 10024 | `MT_RET_REQUEST_TOO_MANY` | 交易请求过多 |
| 10025 | `MT_RET_REQUEST_NO_CHANGES` | 请求不包含变更 |
| 10026 | `MT_RET_REQUEST_AT_DISABLED_SERVER` | 服务器禁用自动交易 |
| 10027 | `MT_RET_REQUEST_AT_DISABLED_CLIENT` | 客户端禁用自动交易 |
| 10028 | `MT_RET_REQUEST_LOCKED` | 请求被 dealer 锁定 |
| 10029 | `MT_RET_REQUEST_FROZEN` | 订单或持仓被冻结 |
| 10030 | `MT_RET_REQUEST_INVALID_FILL` | 不支持的成交模式 |
| 10031 | `MT_RET_REQUEST_CONNECTION` | 无连接 |
| 10032 | `MT_RET_REQUEST_ONLY_REAL` | 仅真实账户允许 |
| 10033 | `MT_RET_REQUEST_LIMIT_ORDERS` | 订单数达到上限 |
| 10034 | `MT_RET_REQUEST_LIMIT_VOLUME` | 手数达到上限 |
| 10035 | `MT_RET_REQUEST_INVALID_ORDER` | 订单类型无效或被禁止 |
| 10036 | `MT_RET_REQUEST_POSITION_CLOSED` | 持仓不存在 |
| 10037 | `MT_RET_REQUEST_EXECUTION_SKIPPED` | 执行不属于此服务器 |
| 10038 | `MT_RET_REQUEST_INVALID_CLOSE_VOLUME` | 平仓量超过持仓量 |
| 10039 | `MT_RET_REQUEST_CLOSE_ORDER_EXIST` | 平此持仓的订单已存在 |
| 10040 | `MT_RET_REQUEST_LIMIT_POSITIONS` | 持仓数达到上限 |
| 10041 | `MT_RET_REQUEST_REJECT_CANCEL` | 请求被拒绝，订单将被取消 |
| 10042 | `MT_RET_REQUEST_LONG_ONLY` | 仅允许多头持仓 |
| 10043 | `MT_RET_REQUEST_SHORT_ONLY` | 仅允许空头持仓 |
| 10044 | `MT_RET_REQUEST_CLOSE_ONLY` | 仅允许平仓 |
| 10045 | `MT_RET_REQUEST_PROHIBITED_BY_FIFO` | 平仓被 FIFO 规则禁止 |
| 10046 | `MT_RET_REQUEST_HEDGE_PROHIBITED` | 禁止对冲 |

### 2.8 交易请求队列（11000 ~ 11002）
| 码值 | 名称 | 说明 |
|------|------|------|
| 11000 | `MT_RET_REQUEST_RETURN` | 请求返回队列 |
| 11001 | `MT_RET_REQUEST_DONE_CANCEL` | 请求部分成交，剩余已取消 |
| 11002 | `MT_RET_REQUEST_REQUOTE_RETURN` | 请求重新报价并以新价返回队列 |

### 2.9 其它实现/服务（12000 ~ 16021）
| 码值 | 名称 | 说明 |
|------|------|------|
| 12000 | `MT_RET_ERR_NOTIMPLEMENT` | 尚未实现 |
| 12001 | `MT_RET_ERR_NOTMAIN` | 操作必须在主服务器执行 |
| 12002 | `MT_RET_ERR_NOTSUPPORTED` | 命令不支持 |
| 12003 | `MT_RET_ERR_DEADLOCK` | 因可能死锁而取消操作 |
| 12004 | `MT_RET_ERR_LOCKED` | 对锁定实体的操作 |
| 14000 | `MT_RET_MESSENGER_INVALID_PHONE` | 手机号无效 |
| 14001 | `MT_RET_MESSENGER_NOT_MOBILE` | 该号码不是手机号 |
| 15000 | `MT_RET_SUBS_NOT_FOUND` | 订阅未找到 |
| 15001 | `MT_RET_SUBS_NOT_FOUND_CFG` | 订阅配置未找到 |
| 15002 | `MT_RET_SUBS_NOT_FOUND_USER` | 订阅用户未找到 |
| 15003 | `MT_RET_SUBS_DISABLED` | 订阅被禁用 |
| 15004 | `MT_RET_SUBS_PERMISSION_USER` | 用户不允许订阅 |
| 15005 | `MT_RET_SUBS_PERMISSION_SUBSCRIBE` | 不允许订阅 |
| 15006 | `MT_RET_SUBS_PERMISSION_UNSUBSCRIBE` | 不允许取消订阅 |
| 15007 | `MT_RET_SUBS_REAL_ONLY` | 订阅仅对真实用户可用 |
| 15008 | `MT_RET_SUBS_PAYMENT_METHOD` | 不支持的支付方式 |
| 16000 | `MT_RET_PAY_REAL_ONLY` | 仅真实账户 |
| 16001 | `MT_RET_PAY_INVALID_AMOUNT` | 支付金额无效 |
| 16002 | `MT_RET_PAY_NOT_ALLOWED_DEPOSIT` | 不允许入金操作 |
| 16003 | `MT_RET_PAY_NOT_ALLOWED_WITHDRAWAL` | 不允许出金操作 |
| 16004 | `MT_RET_PAY_NOT_ALLOWED_GROUP` | 账户组不被允许 |
| 16005 | `MT_RET_PAY_NOT_ALLOWED_COUNTRY` | 账户国家不被允许 |
| 16006 | `MT_RET_PAY_DECLINE_BY_RULES` | 被支付规则拒绝 |
| 16007 | `MT_RET_PAY_DECLINE_BY_AML` | 被 AML 检查拒绝 |
| 16008 | `MT_RET_PAY_LIMIT_DEPOSIT_MIN` | 入金金额低于允许下限 |
| 16009 | `MT_RET_PAY_LIMIT_DEPOSIT_MAX` | 入金金额高于允许上限 |
| 16010 | `MT_RET_PAY_LIMIT_WITHDRAWAL_MIN` | 出金金额低于允许下限 |
| 16011 | `MT_RET_PAY_LIMIT_WITHDRAWAL_MAX` | 出金金额高于允许上限 |
| 16012 | `MT_RET_PAY_PROVIDER_PAYMENT` | 支付提供商处理错误 |
| 16013 | `MT_RET_PAY_PROVIDER_STATUS` | 支付提供商状态请求错误 |
| 16014 | `MT_RET_PAY_CONVERSION` | 支付货币转换错误 |
| 16015 | `MT_RET_PAY_NOT_WAITING` | 支付未在等待验证 |
| 16016 | `MT_RET_PAY_VERIFICATION` | 支付未通过验证 |
| 16017 | `MT_RET_PAY_INVOICE` | 应调用 Invoice 方法获取发票 |
| 16018 | `MT_RET_PAY_INVALID_CURRENCY` | 支付货币错误 |
| 16019 | `MT_RET_PAY_LIMIT_REACHED` | 支付达到上限 |
| 16020 | `MT_RET_PAY_PROVIDER_REFUND` | 支付提供商退款处理错误 |
| 16021 | `MT_RET_PAY_DECLINE_BY_CARDHOLDER_NAME` | 被持卡人姓名验证拒绝 |

> **OCS 关联**：MT5 业务层在交易链路中常直接把 `MT_RET_REQUEST_*` 写入响应（见 `MT5TradeRequestHandle.cpp`）。成功判定为 `MT_RET_REQUEST_DONE(10009)`；`MT_RET_REQUEST_PLACED(10008)` 表示订单可能被插件拦截、需主动回查订单号。详见 `ocs4-returncode.md` §3.5。

---

## 3. 速查

| 看到的码 | 来源 | 查阅 |
|----------|------|------|
| `0`、`1~15`、`64~66`、`128~150` | MT4 平台原生 | 本文 §1 |
| `0~17`、`1000~1034`、`2000~2021`、`3001~3019`、`4001~4009`、`5001~6001`、`10001~11002`、`12000~16021` | MT5 平台原生 | 本文 §2 |
| `66400~66556`、`66700~66729`、`66302`、`68302` | OCS 自定义 | [`ocs4-returncode.md`](./ocs4-returncode.md) |

> 注意：MT4 的 0/1/2 与 MT5 的 0/1/2 含义基本一致（OK / OK_NONE / ERROR），但 **其余段位编号体系完全不同**——判断时务必先确认是 MT4 还是 MT5 链路。

---

*生成日期：2026-06-12 ｜ 数据来源：MT4 Manager API SDK `MT4ManagerAPI.h`（1430）、MT5 SDK `MT5APIConstants.h`（5430，枚举跨版本稳定）；经 `mt4-docs` / `mt5-docs` 技能与 OCS 源码交叉核对。*
