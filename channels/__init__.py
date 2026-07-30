"""IM 接入层：多渠道入口并列（change: feishu-channel-integration）。

单向依赖：``channels/`` → ``executor/`` → ``harness/``。本层 MUST NOT 被 ``executor`` 或
``harness`` 反向依赖——「换掉飞书换成钉钉，Agent 层零改动」这条分层判据就落在这里。
"""
