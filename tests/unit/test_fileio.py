"""atomic_write_text：内容正确、覆盖安全、无残留临时文件"""
from src.video_agent.utils.fileio import atomic_write_text


def test_write_and_overwrite(tmp_path):
    target = tmp_path / "sub" / "data.json"
    atomic_write_text(target, '{"v": 1}')
    assert target.read_text(encoding="utf-8") == '{"v": 1}'

    atomic_write_text(target, '{"v": 2}')
    assert target.read_text(encoding="utf-8") == '{"v": 2}'

    # 无 .tmp 残留
    assert [p for p in target.parent.iterdir() if p.suffix == ".tmp"] == []


def test_unicode_content(tmp_path):
    target = tmp_path / "中文.json"
    atomic_write_text(target, '{"名称": "测试"}')
    assert "测试" in target.read_text(encoding="utf-8")
