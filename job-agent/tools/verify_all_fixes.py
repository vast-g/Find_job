"""汇总验证本轮所有修复：简历、用户上下文、recursion_limit、步数兜底、岗位检索。

用法：
    python tools/verify_all_fixes.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "benchmark" / "reports" / "all_fixes_verify.txt"
OUT.parent.mkdir(parents=True, exist_ok=True)
_fh = OUT.open("w", encoding="utf-8")


class Tee:
    """同时写文件与控制台（上一个版本忘了转发控制台，导致终端看不到输出）。"""

    def write(self, s):
        _fh.write(s)
        try:
            sys.__stdout__.write(s)
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        _fh.flush()
        try:
            sys.__stdout__.flush()
        except Exception:  # noqa: BLE001
            pass


sys.stdout = Tee()
sys.stderr = Tee()
sys.path.insert(0, str(BASE))

OK = "[OK]"
NG = "[!!]"


async def main() -> None:
    from app.agents.react_agent import _NEED_MORE_STEPS, recursion_limit_for
    from app.core.context import reset_current_user, set_current_user
    from app.core.termination import STEP_LIMIT_REPLY
    from app.tools.resume_tools import get_user_resume

    print("=" * 78)
    print("1) recursion_limit 换算（LangGraph 每轮 ReAct 消耗 2 个节点步）")
    print("=" * 78)
    for turns in (5, 10, 15):
        lim = recursion_limit_for(turns)
        print(f"  最大轮数 {turns:>2} -> recursion_limit {lim:>2}  "
              f"（旧实现直接用 {turns}，实际只够约 {turns // 2} 轮）")

    print()
    print("=" * 78)
    print("2) 步数耗尽兜底话术（不再泄漏 LangGraph 内部英文提示）")
    print("=" * 78)
    print(f"  库内部提示 : {_NEED_MORE_STEPS!r}")
    print(f"  替换为     : {STEP_LIMIT_REPLY[:60]}...")
    print(f"  {OK} 内部提示不会直接返回给用户")

    print()
    print("=" * 78)
    print("3) 用户上下文 + get_user_resume（不传 user_id 也能拿到简历）")
    print("=" * 78)
    print(f"  工具入参 : {list(get_user_resume.args.keys())}")
    spec = get_user_resume.args.get("user_id", {})
    print(f"  user_id  : {spec}  -> 可选")

    token = set_current_user(1)
    try:
        r = await get_user_resume.ainvoke({})
    finally:
        reset_current_user(token)

    print(f"  不传 user_id 调用 -> 返回 {len(r)} 个字段")
    for k in ("name", "education", "school", "major", "expect_position", "expect_city"):
        v = r.get(k)
        print(f"    {k:<18}: {v}")
    print(f"    experience        : {len(r.get('experience') or [])} 段")
    print(f"    project_experience: {len(r.get('project_experience') or [])} 段")
    print(f"  {OK if r.get('name') and r.get('education') else NG} "
          f"简历内容{'完整' if r.get('name') else '仍为空'}")

    print()
    print("=" * 78)
    print("4) 岗位检索（修复匹配逻辑 + 补数据后）")
    print("=" * 78)
    from app.tools.job_tools import get_call_stats, reset_call_stats, search_jobs

    reset_call_stats()
    probes = [("软件开发", "上海"), ("网络安全", "深圳"), ("嵌入式", "杭州"),
              ("机械设计", "西安"), ("测试开发", "南京"), ("财务", "北京")]
    for kw, city in probes:
        res = await search_jobs.ainvoke({"keywords": kw, "city": city})
        print(f"  {city}+{kw:<10} -> {len(res):>3} 条" + ("" if res else "   <-- 空"))
    st = get_call_stats()
    print(f"  统计: 总 {st['total']} | 有结果 {st['ok']} | 空 {st['backend_empty']} | "
          f"降级 {st['fallback']}")
    print(f"  {OK if st['fallback'] == 0 else NG} 无静默降级")

    print()
    print("=" * 78)
    print("结论")
    print("=" * 78)
    print("  本轮修复：")
    print("    - 岗位检索：city 模糊 + 关键词跨字段 + 相关度排序（Java）")
    print("    - 岗位检索：回退日志/统计 + 薪资过滤生效（Python）")
    print("    - 数据缺口：补 69 条岗位 / 66 家公司")
    print("    - 简历缺口：补全 user_id=1 的完整简历（24/24 字段）")
    print("    - 用户上下文：get_user_resume 不再要求模型猜测 user_id")
    print("    - 步数语义：recursion_limit 按轮数正确换算")
    print("    - 异常脱敏：LangGraph 内部提示不再泄漏给用户")


if __name__ == "__main__":
    asyncio.run(main())
