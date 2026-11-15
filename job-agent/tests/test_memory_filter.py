"""记忆污染过滤单元测试。"""
import asyncio

from app.memory.filter import rule_filter


def test_filter_chitchat():
    assert rule_filter("你好") is True
    assert rule_filter("谢谢") is True
    assert rule_filter("哈哈") is True


def test_filter_secret():
    assert rule_filter("我的密码是 abc123456") is True
    assert rule_filter("token=sk-abcdefghijklmnopqrstuvwxyz123456") is True
    assert rule_filter("手机号 13800138000") is True
    assert rule_filter("身份证 110101199001011234") is True


def test_filter_valid():
    assert rule_filter("我想找北京的算法工程师岗位，硕士学历") is False
    assert rule_filter("我有3年Java开发经验，熟悉Spring") is False


def test_filter_empty():
    assert rule_filter("") is True
    assert rule_filter("  ") is True
    assert rule_filter("ok") is True


if __name__ == "__main__":
    # 手动运行：python -m pytest tests/
    test_filter_chitchat()
    test_filter_secret()
    test_filter_valid()
    test_filter_empty()
    print("all memory filter tests passed")
