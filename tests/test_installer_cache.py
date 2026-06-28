"""D23 通用安装器 · 第 2 步离线单测：本地缓存 + 原子写 + D14 卫生。

全离线：cache_* 纯文件读写（不联网/不调 LLM/不耗配额，D18 不破）。用 monkeypatch
把 ``config.install_cache_path`` 指到 tmp_path，绝不碰真实 ``data/install_cache.json``。

核心不变式（D14）：缓存文件 grep 不到任何真实 key 指纹；env_template 只存变量名、
值恒空串。
"""

from __future__ import annotations

from skillbrew import config, installer
from skillbrew.installer import InstallSpec


def _spec(**kw) -> InstallSpec:
    """造一个最小可存的 InstallSpec，默认填好必填字段，kw 覆盖。"""
    base = dict(name="x", command="npx", args=("-y", "x"), invoke_hint="提示")
    base.update(kw)
    return InstallSpec(**base)


def test_install_cache_path_under_data():
    p = config.install_cache_path()
    assert p.name == "install_cache.json"
    assert p.parent.name == "data"


def test_has_tty_returns_bool():
    assert isinstance(config.has_tty(), bool)


def test_cache_store_lookup_roundtrip(monkeypatch, tmp_path):
    cache_file = tmp_path / "install_cache.json"
    monkeypatch.setattr(config, "install_cache_path", lambda: cache_file)

    spec = _spec(
        name="foo",
        env_template={"FOO_KEY": "should-be-zeroed"},
        credential_env=("FOO_KEY",),
        needs_config=True,
        post_install_steps=("做点什么",),
    )
    installer.cache_store(spec)

    got = installer.cache_lookup("foo")
    assert got is not None
    assert got.name == "foo"
    assert got.command == "npx"
    assert got.args == ("-y", "x")
    assert got.credential_env == ("FOO_KEY",)
    assert got.needs_config is True
    assert got.post_install_steps == ("做点什么",)
    # provenance 改写为 cache
    assert got.provenance == "cache"
    # trace 追加缓存命中
    assert any("缓存命中" in t for t in got.trace)


def test_cache_lookup_miss_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "install_cache_path", lambda: tmp_path / "install_cache.json")
    assert installer.cache_lookup("ghost") is None


def test_cache_stores_no_key_fingerprints_d14(monkeypatch, tmp_path):
    """D14 核心：env 值带真实 key 指纹，卫生器清零，落盘文本 grep 不到指纹。"""
    cache_file = tmp_path / "install_cache.json"
    monkeypatch.setattr(config, "install_cache_path", lambda: cache_file)

    spec = _spec(
        name="leaky",
        env_template={"OPENAI_API_KEY": "sk-leaky-1234567890abcdef"},
        credential_env=("OPENAI_API_KEY",),
    )
    installer.cache_store(spec)

    raw = cache_file.read_text(encoding="utf-8")
    # 真实 key 指纹绝不进缓存
    assert "sk-leaky" not in raw
    assert "sk-" not in raw
    # 但变量名要保留（只存名不存值）
    assert "OPENAI_API_KEY" in raw
    # 读回的 env_template 值为空串
    got = installer.cache_lookup("leaky")
    assert got.env_template == {"OPENAI_API_KEY": ""}


def test_cache_store_refuses_fingerprint_in_nonenv_field(monkeypatch, tmp_path):
    """D14 防线：非环境变量字段（如 invoke_hint）混入指纹 → 拒绝写入，绝不崩。"""
    cache_file = tmp_path / "install_cache.json"
    monkeypatch.setattr(config, "install_cache_path", lambda: cache_file)

    spec = _spec(name="bad", invoke_hint="see sk-badkey here")
    installer.cache_store(spec)  # 不抛异常
    assert not cache_file.exists()  # 拒绝写入
    assert installer.cache_lookup("bad") is None


def test_cache_lookup_corrupt_file_returns_none(monkeypatch, tmp_path):
    """缓存文件损坏不当死路：返回 None，绝不抛裸异常。"""
    cache_file = tmp_path / "install_cache.json"
    cache_file.write_text("{不是合法 json", encoding="utf-8")
    monkeypatch.setattr(config, "install_cache_path", lambda: cache_file)
    assert installer.cache_lookup("anything") is None


def test_cache_invalidate_and_idempotent(monkeypatch, tmp_path):
    cache_file = tmp_path / "install_cache.json"
    monkeypatch.setattr(config, "install_cache_path", lambda: cache_file)

    installer.cache_store(_spec(name="a"))
    installer.cache_store(_spec(name="b"))
    assert installer.cache_lookup("a") is not None

    installer.cache_invalidate("a")
    assert installer.cache_lookup("a") is None
    assert installer.cache_lookup("b") is not None  # 其它条目不受影响

    # 幂等：再删不存在的也不崩
    installer.cache_invalidate("a")
    installer.cache_invalidate("ghost")


def test_cache_store_preserves_multiple_entries(monkeypatch, tmp_path):
    """多次 store 累加，不覆盖整张表（读-改-写）。"""
    monkeypatch.setattr(config, "install_cache_path", lambda: tmp_path / "install_cache.json")
    installer.cache_store(_spec(name="a", invoke_hint="A"))
    installer.cache_store(_spec(name="b", invoke_hint="B"))
    assert installer.cache_lookup("a").invoke_hint == "A"
    assert installer.cache_lookup("b").invoke_hint == "B"
