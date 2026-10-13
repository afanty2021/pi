# local-patches

orphan 分支，只托管本机已安装 pi 的补丁脚本，与源码树无关。

- `patch_codemode_cap.py` — 对 `D:\scoop\persist\nodejs-lts\bin\node_modules\@earendil-works\pi-coding-agent\dist` 的幂等补丁（一键重打、带备份、node --check 自检、失败自动回滚）：
  1. codemode 输出顶 8k 字符（原 40k）
  2. 摘要（压缩/bug 上报）不带 thinking，普通会话照常
  3. 历史 thinking 不占上下文：估算器不计、anthropic 序列化器只保留最后一条 assistant 的 thinking、摘要 prompt 不序列化
- 工作副本在 `C:/Users/Berton/probe8765/patch_codemode_cap.py`，pi 升级后重打：`python C:/Users/Berton/probe8765/patch_codemode_cap.py`
- 修改流程：改 probe8765 工作副本 → 同步提交回本分支
- 注意：PATCH 3b 仅适用于不验签的 anthropic 兼容端点（omlx）；勿将 pi 指向真 Anthropic（preserved-thinking 前缀绑定会 400）
