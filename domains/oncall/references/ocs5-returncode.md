# OCS5 返回码列表（Return Code）

> 本文整理 **OCS5（mt-tools）** 业务层统一返回码，即 `result_code` 枚举值。
> OCS5 与 OCS4 的返回码体系**完全不同**——OCS5 使用统一的 `result_code` 枚举，不再有 66400/66500/66700 段的 OCS 自定义业务码，而是直接将 MT4/MT5 平台原生返回码映射到 4000/5000 段的 OCS5 内部码。
>
> 如需查 MT 平台原生返回码含义，见 [`mt-returncode.md`](./mt-returncode.md)。
>
> 来源文件：
> - `fp-common/fp-common/result_code.h` — `result_code` 枚举 + `error_description()`
> - `fp-common/fp-common/mt_utils/utils.cpp` — `mt4_return_to_result_code()` / `mt5_return_to_result_code()` 映射表

---

## 1. 返回码体系概览

### 1.1 与 OCS4 的关键差异

| 特性 | OCS4 | OCS5 |
|------|------|------|
| 错误码类型 | 分 MT4/MT5 两套枚举 (`ENUM_MT4_ERR_CODE`/`ENUM_ERR_MT5_CODE`) | 统一 `result_code` 枚举 |
| OCS 自定义码段 | 66400~66556、66700~66729、66302/68302 | **无**——不再自定义参数/业务错误码段 |
| MT 平台码处理 | MT4 有 `GetErrorInfo` 翻译表；MT5 常透传原生码 | 统一通过 `mt4_return_to_result_code()` / `mt5_return_to_result_code()` 映射到 OCS5 内部码 |
| 成功码 | `0` (OK) | `0` (`success`)；MT4 `RET_OK`/`RET_OK_NONE` 和 MT5 `MT_RET_OK`/`MT_RET_OK_NONE` 均映射到 `success` |
| 未识别码处理 | MT4 default 分支原样透传 | 返回 `mt4_sdk_version_incompatible_can_not_hash_return_code`(5) 或 `mt5_sdk_version_incompatible_can_not_hash_return_code`(6)，并打印 WARN 日志 |

### 1.2 码段划分

| 段位 | 用途 |
|------|------|
| `0` | 成功 (`success`) |
| `1 ~ 19` | **OCS5 通用业务错误码**（参数校验、基础设施、幂等性等） |
| `4000 ~ 4038` | **MT4 平台原生码映射**（`RET_*` → `mt4_*`） |
| `5000 ~ 5174` | **MT5 平台原生码映射**（`MT_RET_*` → `mt5_*`） |

---

## 2. OCS5 通用业务错误码（0 ~ 19）

这些是 OCS5 自身的业务逻辑/基础设施错误，不来自 MT 平台。

| 码值 | 枚举名 | 说明 |
|------|--------|------|
| 0 | `success` | 成功 |
| 1 | `common_error` | 通用错误 |
| 2 | `no_impl` | 尚未实现 |
| 3 | `invalid_param` | 参数无效 |
| 4 | `network_error` | 网络错误 |
| 5 | `mt4_sdk_version_incompatible_can_not_hash_return_code` | MT4 SDK 版本不兼容，无法映射返回码（收到未识别的 MT4 原生码时返回） |
| 6 | `mt5_sdk_version_incompatible_can_not_hash_return_code` | MT5 SDK 版本不兼容，无法映射返回码（收到未识别的 MT5 原生码时返回） |
| 7 | `account_not_exist` | 账号不存在 |
| 8 | `no_available_login` | 无可用 login |
| 9 | `redis_error` | Redis 错误 |
| 10 | `idempotence_error` | 幂等性检测错误 |
| 11 | `retry_later` | 请稍后重试 |
| 12 | `not_executed` | 未执行 |
| 13 | `not_found` | 未找到 |
| 14 | `idempotence_retry_later` | 幂等性：uncertain 状态在静默期内，需稍后重试 |
| 15 | `idempotence_retry_allowed` | 幂等性：uncertain 状态且 OB 已覆盖但未找到，允许重试 |
| 16 | `idempotence_duplicate` | 幂等性：检测到重复请求（已有结果） |
| 17 | `mysql_error` | MySQL 数据库错误 |
| 18 | `serverid_mapping_not_fount` | 找不到对应的 serverid 映射 |
| 19 | `mt_unavailable` | MT 服务器不可用 |

---

## 3. MT4 平台原生码 → OCS5 映射（4000 ~ 4038）

> 映射来源：`utils.cpp` → `mt4_return_to_result_code()`
> MT4 原生码定义：`MT4ManagerAPI.h` 匿名 `enum`（`RET_*`）

### 3.1 通用状态码映射

| MT4 原生码 | MT4 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `RET_OK` | 0 | 0 | `success` | 成功 |
| `RET_OK_NONE` | 1 | 0 | `success` | 成功，但无操作/无数据（OCS5 统一视为成功） |
| `RET_ERROR` | 2 | 4002 | `mt4_error` | 通用错误 |
| `RET_INVALID_DATA` | 3 | 4003 | `mt4_invalid_data` | 无效数据 |
| `RET_TECH_PROBLEM` | 4 | 4004 | `mt4_tech_problem` | 服务器技术故障 |
| `RET_OLD_VERSION` | 5 | 4005 | `mt4_old_version` | 客户端版本过旧 |
| `RET_NO_CONNECT` | 6 | 4006 | `mt4_no_connect` | 无连接 |
| `RET_NOT_ENOUGH_RIGHTS` | 7 | 4007 | `mt4_not_enough_rights` | 权限不足 |
| `RET_TOO_FREQUENT` | 8 | 4008 | `mt4_too_frequent` | 访问过于频繁 |
| `RET_MALFUNCTION` | 9 | 4009 | `mt4_malfunction` | 操作异常/故障 |
| `RET_GENERATE_KEY` | 10 | 4010 | `mt4_generate_key` | 需要发送公钥 |
| `RET_SECURITY_SESSION` | 11 | 4011 | `mt4_security_session` | 安全会话已开始 |
| `RET_INVALID_COMPANY` | 15 | 4038 | `mt4_invalid_company` | 公司名不属于该 license 或白标 |

### 3.2 账号状态码映射

| MT4 原生码 | MT4 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `RET_ACCOUNT_DISABLED` | 64 | 4012 | `mt4_account_disabled` | 账号被封禁 |
| `RET_BAD_ACCOUNT_INFO` | 65 | 4013 | `mt4_bad_account_info` | 账号信息错误 |
| `RET_PUBLIC_KEY_MISSING` | 66 | 4014 | `mt4_public_key_missing` | 缺少公钥 |

### 3.3 交易错误码映射

| MT4 原生码 | MT4 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `RET_TRADE_TIMEOUT` | 128 | 4015 | `mt4_trade_timeout` | 交易事务超时 |
| `RET_TRADE_BAD_PRICES` | 129 | 4016 | `mt4_trade_bad_prices` | 订单价格错误 |
| `RET_TRADE_BAD_STOPS` | 130 | 4017 | `mt4_trade_bad_stops` | 止损/止盈水平无效 |
| `RET_TRADE_BAD_VOLUME` | 131 | 4018 | `mt4_trade_bad_volume` | 手数错误 |
| `RET_TRADE_MARKET_CLOSED` | 132 | 4019 | `mt4_trade_market_closed` | 市场关闭 |
| `RET_TRADE_DISABLE` | 133 | 4020 | `mt4_trade_disable` | 交易被禁止 |
| `RET_TRADE_NO_MONEY` | 134 | 4021 | `mt4_trade_no_money` | 保证金不足 |
| `RET_TRADE_PRICE_CHANGED` | 135 | 4022 | `mt4_trade_price_changed` | 价格已变更 |
| `RET_TRADE_OFFQUOTES` | 136 | 4023 | `mt4_trade_offquotes` | 没有报价 |
| `RET_TRADE_BROKER_BUSY` | 137 | 4024 | `mt4_trade_broker_busy` | broker 忙 |
| `RET_TRADE_REQUOTE` | 138 | 4025 | `mt4_trade_requote` | 重新报价 |
| `RET_TRADE_ORDER_LOCKED` | 139 | 4026 | `mt4_trade_order_locked` | 订单正被 dealer 处理，无法修改 |
| `RET_TRADE_LONG_ONLY` | 140 | 4027 | `mt4_trade_long_only` | 仅允许买单 |
| `RET_TRADE_TOO_MANY_REQ` | 141 | 4028 | `mt4_trade_too_many_req` | 单客户端请求过多 |

### 3.4 订单状态通知码映射

| MT4 原生码 | MT4 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `RET_TRADE_ACCEPTED` | 142 | 4029 | `mt4_trade_accepted` | 请求已被服务器接受并进入请求队列 |
| `RET_TRADE_PROCESS` | 143 | 4030 | `mt4_trade_process` | 请求已被 dealer 接受处理中 |
| `RET_TRADE_USER_CANCEL` | 144 | 4031 | `mt4_trade_user_cancel` | 请求被客户端取消 |

### 3.5 附加返回码映射

| MT4 原生码 | MT4 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `RET_TRADE_MODIFY_DENIED` | 145 | 4032 | `mt4_trade_modify_denied` | 订单修改被拒绝 |
| `RET_TRADE_CONTEXT_BUSY` | 146 | 4033 | `mt4_trade_context_busy` | 交易上下文忙 |
| `RET_TRADE_EXPIRATION_DENIED` | 147 | 4034 | `mt4_trade_expiration_denied` | 不允许使用过期时间 |
| `RET_TRADE_TOO_MANY_ORDERS` | 148 | 4035 | `mt4_trade_too_many_orders` | 订单过多 |
| `RET_TRADE_HEDGE_PROHIBITED` | 149 | 4036 | `mt4_trade_hedge_prohibited` | 禁止对冲 |
| `RET_TRADE_PROHIBITED_BY_FIFO` | 150 | 4037 | `mt4_trade_prohibited_by_fifo` | 被 FIFO 规则禁止 |

> ⚠️ **注意**：OCS5 不再有 OCS4 那样的 66515~66548 段翻译层。MT4 原生码直接通过 `mt4_return_to_result_code()` 一步映射到 `result_code`。未被映射的 MT4 原生码会返回 `mt4_sdk_version_incompatible_can_not_hash_return_code`(5) 并打印 WARN 日志。

---

## 4. MT5 平台原生码 → OCS5 映射（5000 ~ 5174）

> 映射来源：`utils.cpp` → `mt5_return_to_result_code()`
> MT5 原生码定义：`MT5APIConstants.h` → `EnMTAPIRetCode`（`MT_RET_*`）

### 4.1 通用结果码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_OK` | 0 | 0 | `success` | 成功 |
| `MT_RET_OK_NONE` | 1 | 0 | `success` | 成功，无数据 |
| `MT_RET_ERROR` | 2 | 5002 | `mt5_error` | 通用错误 |
| `MT_RET_ERR_PARAMS` | 3 | 5003 | `mt5_err_params` | 参数无效 |
| `MT_RET_ERR_DATA` | 4 | 5004 | `mt5_err_data` | 数据无效 |
| `MT_RET_ERR_DISK` | 5 | 5005 | `mt5_err_disk` | 磁盘错误 |
| `MT_RET_ERR_MEM` | 6 | 5006 | `mt5_err_mem` | 内存错误 |
| `MT_RET_ERR_NETWORK` | 7 | 5007 | `mt5_err_network` | 网络错误 |
| `MT_RET_ERR_PERMISSIONS` | 8 | 5008 | `mt5_err_permissions` | 权限不足 |
| `MT_RET_ERR_TIMEOUT` | 9 | 5009 | `mt5_err_timeout` | 操作超时 |
| `MT_RET_ERR_CONNECTION` | 10 | 5010 | `mt5_err_connection` | 无连接 |
| `MT_RET_ERR_NOSERVICE` | 11 | 5011 | `mt5_err_noservice` | 服务不可用 |
| `MT_RET_ERR_FREQUENT` | 12 | 5012 | `mt5_err_frequent` | 请求过于频繁 |
| `MT_RET_ERR_NOTFOUND` | 13 | 5013 | `mt5_err_notfound` | 未找到 |
| `MT_RET_ERR_PARTIAL` | 14 | 5014 | `mt5_err_partial` | 部分错误 |
| `MT_RET_ERR_SHUTDOWN` | 15 | 5015 | `mt5_err_shutdown` | 服务器正在关闭 |
| `MT_RET_ERR_CANCEL` | 16 | 5016 | `mt5_err_cancel` | 操作被取消 |
| `MT_RET_ERR_DUPLICATE` | 17 | 5017 | `mt5_err_duplicate` | 数据重复 |

### 4.2 认证/连接码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_AUTH_CLIENT_INVALID` | 1000 | 5018 | `mt5_auth_client_invalid` | 终端类型无效 |
| `MT_RET_AUTH_ACCOUNT_INVALID` | 1001 | 5019 | `mt5_auth_account_invalid` | 账号无效 |
| `MT_RET_AUTH_ACCOUNT_DISABLED` | 1002 | 5020 | `mt5_auth_account_disabled` | 账号被禁用 |
| `MT_RET_AUTH_ADVANCED` | 1003 | 5021 | `mt5_auth_advanced` | 需要高级授权 |
| `MT_RET_AUTH_CERTIFICATE` | 1004 | 5022 | `mt5_auth_certificate` | 需要证书 |
| `MT_RET_AUTH_CERTIFICATE_BAD` | 1005 | 5023 | `mt5_auth_certificate_bad` | 证书无效 |
| `MT_RET_AUTH_NOTCONFIRMED` | 1006 | 5024 | `mt5_auth_notconfirmed` | 证书未确认 |
| `MT_RET_AUTH_SERVER_INTERNAL` | 1007 | 5025 | `mt5_auth_server_internal` | 试图连接非接入服务器 |
| `MT_RET_AUTH_SERVER_BAD` | 1008 | 5026 | `mt5_auth_server_bad` | 服务器未认证 |
| `MT_RET_AUTH_UPDATE_ONLY` | 1009 | 5027 | `mt5_auth_update_only` | 仅有更新可用 |
| `MT_RET_AUTH_CLIENT_OLD` | 1010 | 5028 | `mt5_auth_client_old` | 客户端版本过旧 |
| `MT_RET_AUTH_MANAGER_NOCONFIG` | 1011 | 5029 | `mt5_auth_manager_noconfig` | manager 账号无 manager 配置 |
| `MT_RET_AUTH_MANAGER_IPBLOCK` | 1012 | 5030 | `mt5_auth_manager_ipblock` | manager IP 不被允许 |
| `MT_RET_AUTH_GROUP_INVALID` | 1013 | 5031 | `mt5_auth_group_invalid` | 组未初始化 |
| `MT_RET_AUTH_CA_DISABLED` | 1014 | 5032 | `mt5_auth_ca_disabled` | 证书生成被禁用 |
| `MT_RET_AUTH_INVALID_ID` | 1015 | 5033 | `mt5_auth_invalid_id` | server id 无效或禁用 |
| `MT_RET_AUTH_INVALID_IP` | 1016 | 5034 | `mt5_auth_invalid_ip` | 地址不被允许 |
| `MT_RET_AUTH_INVALID_TYPE` | 1017 | 5035 | `mt5_auth_invalid_type` | 服务器类型无效 |
| `MT_RET_AUTH_SERVER_BUSY` | 1018 | 5036 | `mt5_auth_server_busy` | 服务器忙 |
| `MT_RET_AUTH_SERVER_CERT` | 1019 | 5037 | `mt5_auth_server_cert` | 服务器证书无效 |
| `MT_RET_AUTH_ACCOUNT_UNKNOWN` | 1020 | 5038 | `mt5_auth_account_unknown` | 未知账号 |
| `MT_RET_AUTH_SERVER_OLD` | 1021 | 5039 | `mt5_auth_server_old` | 服务器版本过旧 |
| `MT_RET_AUTH_SERVER_LIMIT` | 1022 | 5040 | `mt5_auth_server_limit` | license 限制无法连接 |
| `MT_RET_AUTH_MOBILE_DISABLED` | 1023 | 5041 | `mt5_auth_mobile_disabled` | license 不允许移动端连接 |
| `MT_RET_AUTH_MANAGER_TYPE` | 1024 | 5042 | `mt5_auth_manager_type` | manager 不允许该连接类型 |
| `MT_RET_AUTH_DEMO_DISABLED` | 1025 | 5043 | `mt5_auth_demo_disabled` | demo 分配被禁用 |
| `MT_RET_AUTH_RESET_PASSWORD` | 1026 | 5044 | `mt5_auth_reset_password` | 必须修改主密码 |
| `MT_RET_AUTH_OTP_INVALID` | 1027 | 5045 | `mt5_auth_otp_invalid` | 一次性密码无效 |
| `MT_RET_AUTH_OTP_NEED_SECRET` | 1028 | 5046 | `mt5_auth_otp_need_secret` | 需要一次性密码密钥 |
| `MT_RET_AUTH_MIGRATION_MT4` | 1029 | 5047 | `mt5_auth_migration_mt4` | 需要 MT4 密码迁移 |
| `MT_RET_AUTH_MIGRATION_MT5` | 1030 | 5048 | `mt5_auth_migration_mt5` | 需要 MT5 密码迁移 |
| `MT_RET_AUTH_INVALID_VERIFY` | 1031 | 5049 | `mt5_auth_invalid_verify` | 确认码无效或过期 |
| `MT_RET_AUTH_VERIFY_BAD_EMAIL` | 1032 | 5050 | `mt5_auth_verify_bad_email` | 邮件验证码无法发送 |
| `MT_RET_AUTH_VERIFY_BAD_PHONE` | 1033 | 5051 | `mt5_auth_verify_bad_phone` | 手机验证码无法发送 |
| `MT_RET_AUTH_API_DISABLED` | 1034 | 5052 | `mt5_auth_api_disabled` | 账号 API 连接被禁用 |

### 4.3 配置管理码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_CFG_LAST_ADMIN` | 2000 | 5053 | `mt5_cfg_last_admin` | 删除最后一个 admin 配置 |
| `MT_RET_CFG_LAST_ADMIN_GROUP` | 2001 | 5054 | `mt5_cfg_last_admin_group` | 最后一个 admin 组不能删除 |
| `MT_RET_CFG_NOT_EMPTY` | 2003 | 5055 | `mt5_cfg_not_empty` | 组/品种中仍有账户或交易 |
| `MT_RET_CFG_INVALID_RANGE` | 2004 | 5056 | `mt5_cfg_invalid_range` | 账户或交易范围无效 |
| `MT_RET_CFG_NOT_MANAGER_LOGIN` | 2005 | 5057 | `mt5_cfg_not_manager_login` | manager 账号不属于 manager 组 |
| `MT_RET_CFG_BUILTIN` | 2006 | 5058 | `mt5_cfg_builtin` | 内置受保护配置 |
| `MT_RET_CFG_DUPLICATE` | 2007 | 5059 | `mt5_cfg_duplicate` | 配置重复 |
| `MT_RET_CFG_LIMIT_REACHED` | 2008 | 5060 | `mt5_cfg_limit_reached` | 配置数量达到上限 |
| `MT_RET_CFG_NO_ACCESS_TO_MAIN` | 2009 | 5061 | `mt5_cfg_no_access_to_main` | 网络配置无效 |
| `MT_RET_CFG_DEALER_ID_EXIST` | 2010 | 5062 | `mt5_cfg_dealer_id_exist` | 相同 ID 的 dealer 已存在 |
| `MT_RET_CFG_BIND_ADDR_EXIST` | 2011 | 5063 | `mt5_cfg_bind_addr_exist` | 绑定地址已存在 |
| `MT_RET_CFG_WORKING_TRADE` | 2012 | 5064 | `mt5_cfg_working_trade` | 试图删除运行中的交易服务器 |
| `MT_RET_CFG_GATEWAY_NAME_EXIST` | 2013 | 5065 | `mt5_cfg_gateway_name_exist` | 相同名称的 gateway 已存在 |
| `MT_RET_CFG_SWITCH_TO_BACKUP` | 2014 | 5066 | `mt5_cfg_switch_to_backup` | 服务器必须切换到备份模式 |
| `MT_RET_CFG_NO_BACKUP_MODULE` | 2015 | 5067 | `mt5_cfg_no_backup_module` | 缺少备份服务器模块 |
| `MT_RET_CFG_NO_TRADE_MODULE` | 2016 | 5068 | `mt5_cfg_no_trade_module` | 缺少交易服务器模块 |
| `MT_RET_CFG_NO_HISTORY_MODULE` | 2017 | 5069 | `mt5_cfg_no_history_module` | 缺少历史服务器模块 |
| `MT_RET_CFG_ANOTHER_SWITCH` | 2018 | 5070 | `mt5_cfg_another_switch` | 另一切换过程进行中 |
| `MT_RET_CFG_NO_LICENSE_FILE` | 2019 | 5071 | `mt5_cfg_no_license_file` | 缺少 license 文件 |
| `MT_RET_CFG_GATEWAY_LOGIN_EXIST` | 2020 | 5072 | `mt5_cfg_gateway_login_exist` | 相同 login 的 gateway 已存在 |
| `MT_RET_CFG_INVALID_COMPANY` | 2021 | 5073 | `mt5_cfg_invalid_company` | 公司名不属于该 license 或白标 |

### 4.4 用户管理码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_USR_LAST_ADMIN` | 3001 | 5074 | `mt5_usr_last_admin` | 删除最后一个 admin 账号 |
| `MT_RET_USR_LOGIN_EXHAUSTED` | 3002 | 5075 | `mt5_usr_login_exhausted` | login 范围已耗尽 |
| `MT_RET_USR_LOGIN_PROHIBITED` | 3003 | 5076 | `mt5_usr_login_prohibited` | login 已被其它服务器保留 |
| `MT_RET_USR_LOGIN_EXIST` | 3004 | 5077 | `mt5_usr_login_exist` | 账号已存在 |
| `MT_RET_USR_SUICIDE` | 3005 | 5078 | `mt5_usr_suicide` | 试图自删除 |
| `MT_RET_USR_INVALID_PASSWORD` | 3006 | 5079 | `mt5_usr_invalid_password` | 账号密码无效 |
| `MT_RET_USR_LIMIT_REACHED` | 3007 | 5080 | `mt5_usr_limit_reached` | 用户数量达到上限 |
| `MT_RET_USR_HAS_TRADES` | 3008 | 5081 | `mt5_usr_has_trades` | 账号有未平仓交易 |
| `MT_RET_USR_DIFFERENT_SERVERS` | 3009 | 5082 | `mt5_usr_different_servers` | 试图把账号移到不同服务器 |
| `MT_RET_USR_DIFFERENT_CURRENCY` | 3010 | 5083 | `mt5_usr_different_currency` | 试图把账号移到不同币种组 |
| `MT_RET_USR_IMPORT_BALANCE` | 3011 | 5084 | `mt5_usr_import_balance` | 账号余额导入错误 |
| `MT_RET_USR_IMPORT_GROUP` | 3012 | 5085 | `mt5_usr_import_group` | 账号导入组无效 |
| `MT_RET_USR_ACCOUNT_EXIST` | 3013 | 5086 | `mt5_usr_account_exist` | 账号已存在 |
| `MT_RET_USR_IMPORT_ACCOUNT` | 3014 | 5087 | `mt5_usr_import_account` | 账号交易数据导入错误 |
| `MT_RET_USR_IMPORT_POSITIONS` | 3015 | 5088 | `mt5_usr_import_positions` | 账号持仓导入错误 |
| `MT_RET_USR_IMPORT_ORDERS` | 3016 | 5089 | `mt5_usr_import_orders` | 账号挂单导入错误 |
| `MT_RET_USR_IMPORT_DEALS` | 3017 | 5090 | `mt5_usr_import_deals` | 账号成交历史导入错误 |
| `MT_RET_USR_IMPORT_HISTORY` | 3018 | 5091 | `mt5_usr_import_history` | 账号订单历史导入错误 |
| `MT_RET_USR_API_LIMIT_REACHED` | 3019 | 5092 | `mt5_usr_api_limit_reached` | 启用 API 的用户数达到上限 |

### 4.5 交易记录管理码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_TRADE_LIMIT_REACHED` | 4001 | 5093 | `mt5_trade_limit_reached` | 订单或成交数量达到上限 |
| `MT_RET_TRADE_ORDER_EXIST` | 4002 | 5094 | `mt5_trade_order_exist` | 订单已存在 |
| `MT_RET_TRADE_ORDER_EXHAUSTED` | 4003 | 5095 | `mt5_trade_order_exhausted` | 订单号范围耗尽 |
| `MT_RET_TRADE_DEAL_EXHAUSTED` | 4004 | 5096 | `mt5_trade_deal_exhausted` | 成交号范围耗尽 |
| `MT_RET_TRADE_MAX_MONEY` | 4005 | 5097 | `mt5_trade_max_money` | 资金达到上限 |
| `MT_RET_TRADE_DEAL_EXIST` | 4006 | 5098 | `mt5_trade_deal_exist` | 成交已存在 |
| `MT_RET_TRADE_ORDER_PROHIBITED` | 4007 | 5099 | `mt5_trade_order_prohibited` | 订单号被其它服务器保留 |
| `MT_RET_TRADE_DEAL_PROHIBITED` | 4008 | 5100 | `mt5_trade_deal_prohibited` | 成交号被其它服务器保留 |
| `MT_RET_TRADE_SPLIT_VOLUME` | 4009 | 5101 | `mt5_trade_split_volume` | 新持仓量小于最小允许量 |

### 4.6 报表/历史码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_REPORT_SNAPSHOT` | 5001 | 5102 | `mt5_report_snapshot` | base 快照错误 |
| `MT_RET_REPORT_NOTSUPPORTED` | 5002 | 5103 | `mt5_report_notsupported` | 该报表不支持此方法 |
| `MT_RET_REPORT_NODATA` | 5003 | 5104 | `mt5_report_nodata` | 无报表数据 |
| `MT_RET_REPORT_TEMPLATE_BAD` | 5004 | 5105 | `mt5_report_template_bad` | 模板错误 |
| `MT_RET_REPORT_TEMPLATE_END` | 5005 | 5106 | `mt5_report_template_end` | 模板结束（处理成功） |
| `MT_RET_REPORT_INVALID_ROW` | 5006 | 5107 | `mt5_report_invalid_row` | 行大小无效 |
| `MT_RET_REPORT_LIMIT_REPEAT` | 5007 | 5108 | `mt5_report_limit_repeat` | tag 重复次数达到上限 |
| `MT_RET_REPORT_LIMIT_REPORT` | 5008 | 5109 | `mt5_report_limit_report` | 报表大小达到上限 |
| `MT_RET_HST_SYMBOL_NOTFOUND` | 6001 | 5110 | `mt5_hst_symbol_notfound` | 品种未找到，尝试重启历史服务器 |

### 4.7 交易请求结果码映射 ★ 交易链路核心

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_REQUEST_INWAY` | 10001 | 5111 | `mt5_request_inway` | 请求在途 |
| `MT_RET_REQUEST_ACCEPTED` | 10002 | 5112 | `mt5_request_accepted` | 请求已接受 |
| `MT_RET_REQUEST_PROCESS` | 10003 | 5113 | `mt5_request_process` | 请求处理中 |
| `MT_RET_REQUEST_REQUOTE` | 10004 | 5114 | `mt5_request_requote` | 请求重新报价 |
| `MT_RET_REQUEST_PRICES` | 10005 | 5115 | `mt5_request_prices` | 请求报价 |
| `MT_RET_REQUEST_REJECT` | 10006 | 5116 | `mt5_request_reject` | 请求被拒绝 |
| `MT_RET_REQUEST_CANCEL` | 10007 | 5117 | `mt5_request_cancel` | 请求被取消 |
| `MT_RET_REQUEST_PLACED` | 10008 | 5118 | `mt5_request_placed` | 请求下的订单已挂出（在途/挂单） |
| `MT_RET_REQUEST_DONE` | 10009 | 5119 | `mt5_request_done` | **请求执行完成（成功）** |
| `MT_RET_REQUEST_DONE_PARTIAL` | 10010 | 5120 | `mt5_request_done_partial` | 请求部分执行 |
| `MT_RET_REQUEST_ERROR` | 10011 | 5121 | `mt5_request_error` | 请求通用错误 |
| `MT_RET_REQUEST_TIMEOUT` | 10012 | 5122 | `mt5_request_timeout` | 请求超时 |
| `MT_RET_REQUEST_INVALID` | 10013 | 5123 | `mt5_request_invalid` | 请求无效 |
| `MT_RET_REQUEST_INVALID_VOLUME` | 10014 | 5124 | `mt5_request_invalid_volume` | 手数无效 |
| `MT_RET_REQUEST_INVALID_PRICE` | 10015 | 5125 | `mt5_request_invalid_price` | 价格无效 |
| `MT_RET_REQUEST_INVALID_STOPS` | 10016 | 5126 | `mt5_request_invalid_stops` | 止损/止盈无效 |
| `MT_RET_REQUEST_TRADE_DISABLED` | 10017 | 5127 | `mt5_request_trade_disabled` | 交易被禁用 |
| `MT_RET_REQUEST_MARKET_CLOSED` | 10018 | 5128 | `mt5_request_market_closed` | 市场关闭 |
| `MT_RET_REQUEST_NO_MONEY` | 10019 | 5129 | `mt5_request_no_money` | 资金不足 |
| `MT_RET_REQUEST_PRICE_CHANGED` | 10020 | 5130 | `mt5_request_price_changed` | 价格已变更 |
| `MT_RET_REQUEST_PRICE_OFF` | 10021 | 5131 | `mt5_request_price_off` | 无报价 |
| `MT_RET_REQUEST_INVALID_EXP` | 10022 | 5132 | `mt5_request_invalid_exp` | 订单过期时间无效 |
| `MT_RET_REQUEST_ORDER_CHANGED` | 10023 | 5133 | `mt5_request_order_changed` | 订单已被修改 |
| `MT_RET_REQUEST_TOO_MANY` | 10024 | 5134 | `mt5_request_too_many` | 交易请求过多 |
| `MT_RET_REQUEST_NO_CHANGES` | 10025 | 5135 | `mt5_request_no_changes` | 请求不包含变更 |
| `MT_RET_REQUEST_AT_DISABLED_SERVER` | 10026 | 5136 | `mt5_request_at_disabled_server` | 服务器禁用自动交易 |
| `MT_RET_REQUEST_AT_DISABLED_CLIENT` | 10027 | 5137 | `mt5_request_at_disabled_client` | 客户端禁用自动交易 |
| `MT_RET_REQUEST_LOCKED` | 10028 | 5138 | `mt5_request_locked` | 请求被 dealer 锁定 |
| `MT_RET_REQUEST_FROZEN` | 10029 | 5139 | `mt5_request_frozen` | 订单或持仓被冻结 |
| `MT_RET_REQUEST_INVALID_FILL` | 10030 | 5140 | `mt5_request_invalid_fill` | 不支持的成交模式 |
| `MT_RET_REQUEST_CONNECTION` | 10031 | 5141 | `mt5_request_connection` | 无连接 |
| `MT_RET_REQUEST_ONLY_REAL` | 10032 | 5142 | `mt5_request_only_real` | 仅真实账户允许 |
| `MT_RET_REQUEST_LIMIT_ORDERS` | 10033 | 5143 | `mt5_request_limit_orders` | 订单数达到上限 |
| `MT_RET_REQUEST_LIMIT_VOLUME` | 10034 | 5144 | `mt5_request_limit_volume` | 手数达到上限 |
| `MT_RET_REQUEST_INVALID_ORDER` | 10035 | 5145 | `mt5_request_invalid_order` | 订单类型无效或被禁止 |
| `MT_RET_REQUEST_POSITION_CLOSED` | 10036 | 5146 | `mt5_request_position_closed` | 持仓不存在 |
| `MT_RET_REQUEST_EXECUTION_SKIPPED` | 10037 | 5147 | `mt5_request_execution_skipped` | 执行不属于此服务器 |
| `MT_RET_REQUEST_INVALID_CLOSE_VOLUME` | 10038 | 5148 | `mt5_request_invalid_close_volume` | 平仓量超过持仓量 |
| `MT_RET_REQUEST_CLOSE_ORDER_EXIST` | 10039 | 5149 | `mt5_request_close_order_exist` | 平此持仓的订单已存在 |
| `MT_RET_REQUEST_LIMIT_POSITIONS` | 10040 | 5150 | `mt5_request_limit_positions` | 持仓数达到上限 |
| `MT_RET_REQUEST_REJECT_CANCEL` | 10041 | 5151 | `mt5_request_reject_cancel` | 请求被拒绝，订单将被取消 |
| `MT_RET_REQUEST_LONG_ONLY` | 10042 | 5152 | `mt5_request_long_only` | 仅允许多头持仓 |
| `MT_RET_REQUEST_SHORT_ONLY` | 10043 | 5153 | `mt5_request_short_only` | 仅允许空头持仓 |
| `MT_RET_REQUEST_CLOSE_ONLY` | 10044 | 5154 | `mt5_request_close_only` | 仅允许平仓 |
| `MT_RET_REQUEST_PROHIBITED_BY_FIFO` | 10045 | 5155 | `mt5_request_prohibited_by_fifo` | 平仓被 FIFO 规则禁止 |
| `MT_RET_REQUEST_HEDGE_PROHIBITED` | 10046 | 5156 | `mt5_request_hedge_prohibited` | 禁止对冲 |

### 4.8 交易请求队列/Dealer 码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_REQUEST_RETURN` | 11000 | 5157 | `mt5_request_return` | 请求返回队列 |
| `MT_RET_REQUEST_DONE_CANCEL` | 11001 | 5158 | `mt5_request_done_cancel` | 请求部分成交，剩余已取消 |
| `MT_RET_REQUEST_REQUOTE_RETURN` | 11002 | 5159 | `mt5_request_requote_return` | 请求重新报价并以新价返回队列 |

### 4.9 其它 API/服务码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_ERR_NOTIMPLEMENT` | 12000 | 5160 | `mt5_err_notimplement` | 尚未实现 |
| `MT_RET_ERR_NOTMAIN` | 12001 | 5161 | `mt5_err_notmain` | 操作必须在主服务器执行 |
| `MT_RET_ERR_NOTSUPPORTED` | 12002 | 5162 | `mt5_err_notsupported` | 命令不支持 |
| `MT_RET_ERR_DEADLOCK` | 12003 | 5163 | `mt5_err_deadlock` | 因可能死锁而取消操作 |
| `MT_RET_ERR_LOCKED` | 12004 | 5164 | `mt5_err_locked` | 对锁定实体的操作 |

### 4.10 消息/订阅/支付码映射

| MT5 原生码 | MT5 值 | OCS5 码值 | OCS5 枚举名 | 说明 |
|-----------|--------|----------|------------|------|
| `MT_RET_MESSENGER_INVALID_PHONE` | 14000 | 5165 | `mt5_messenger_invalid_phone` | 手机号无效 |
| `MT_RET_MESSENGER_NOT_MOBILE` | 14001 | 5166 | `mt5_messenger_not_mobile` | 该号码不是手机号 |
| `MT_RET_SUBS_NOT_FOUND` | 15000 | 5167 | `mt5_subs_not_found` | 订阅未找到 |
| `MT_RET_SUBS_NOT_FOUND_CFG` | 15001 | 5168 | `mt5_subs_not_found_cfg` | 订阅配置未找到 |
| `MT_RET_SUBS_NOT_FOUND_USER` | 15002 | 5169 | `mt5_subs_not_found_user` | 订阅用户未找到 |
| `MT_RET_SUBS_DISABLED` | 15003 | 5170 | `mt5_subs_disabled` | 订阅被禁用 |
| `MT_RET_SUBS_PERMISSION_USER` | 15004 | 5171 | `mt5_subs_permission_user` | 用户不允许订阅 |
| `MT_RET_SUBS_PERMISSION_SUBSCRIBE` | 15005 | 5172 | `mt5_subs_permission_subscribe` | 不允许订阅 |
| `MT_RET_SUBS_PERMISSION_UNSUBSCRIBE` | 15006 | 5173 | `mt5_subs_permission_unsubscribe` | 不允许取消订阅 |
| `MT_RET_SUBS_REAL_ONLY` | 15007 | 5174 | `mt5_subs_real_only` | 订阅仅对真实用户可用 |

> ⚠️ **注意**：MT5 支付相关码（`MT_RET_PAY_*`，16000~16021）**未**在 OCS5 映射表中——若收到这些码会返回 `mt5_sdk_version_incompatible_can_not_hash_return_code`(6)。

---

## 5. 速查

| 看到的码 | 来源 | 查阅 |
|----------|------|------|
| `0` | 成功 | 本文 §2 |
| `1 ~ 19` | OCS5 通用业务错误 | 本文 §2 |
| `4000 ~ 4038` | MT4 平台原生码映射 | 本文 §3 |
| `5000 ~ 5174` | MT5 平台原生码映射 | 本文 §4 |
| 非上述段位的原始码（如 10001~11002） | MT5 原生码**未被映射**（应检查为何未走 `mt5_return_to_result_code`） | [`mt-returncode.md`](./mt-returncode.md) §2 |

> ⚠️ **关键差异提醒**：OCS4 的 66xxx 段错误码（66400~66729、66302/68302）在 OCS5 中**不存在**。OCS5 不再自定义参数/业务错误码段，而是通过统一 `result_code` 枚举直接映射 MT 平台原生码。排查时务必先确认是 OCS4 还是 OCS5 环境。

---

## 6. 排查建议

1. **先看码段**：0~19 → OCS5 自身错误；4000~4038 → MT4 平台错误；5000~5174 → MT5 平台错误。
2. **收到 5 (`mt4_sdk_version_incompatible_can_not_hash_return_code`)**：说明 MT4 返回了 OCS5 映射表未覆盖的原生码，需检查 WARN 日志中的原始 `code` 值，对照 `mt-returncode.md` 确认是否需要补充映射。
3. **收到 6 (`mt5_sdk_version_incompatible_can_not_hash_return_code`)**：同上，MT5 返回了未覆盖的原生码（常见于支付 `MT_RET_PAY_*` 段），需检查 WARN 日志。
4. **`result_code` 枚举值可直接用 `error_description(code)` 获取英文描述文本**，便于日志/调试。

---

*生成日期：2026-06-12 ｜ 数据来源：`fp-common/fp-common/result_code.h`（枚举定义）、`fp-common/fp-common/mt_utils/utils.cpp`（`mt4_return_to_result_code` / `mt5_return_to_result_code` 映射表）*
