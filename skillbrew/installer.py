"""installer.py —— 向后兼容 shim。

D23 架构重构后，原 installer.py 的全部内容（InstallSpec / resolve_install_spec / cache_lookup
等推断安装器逻辑）已迁入 install/spec.py；本文件仅做 re-export，保证老代码
``from skillbrew import installer``、``from skillbrew.installer import InstallSpec`` 继续可用。

注意：这里必须直接从 ``.install.spec`` 导入，**不能** 从 ``.install`` 包层导入，否则会触发
install/__init__.py → executor → installer → install 的循环导入。
"""

from __future__ import annotations

from .install.spec import (
    _CANDIDATE_BASES,
    _INFER_SYSTEM,
    _KEY_FINGERPRINTS,
    _NOT_FOUND_SIGNALS,
    _PLACEHOLDER_RE,
    _TRIAL_TIMEOUT,
    InstallSpec,
    PromptResult,
    ResolveResult,
    VerifyResult,
    _atomic_write_json,
    _build_infer_prompt,
    _fetch_install_hints,
    _has_key_fingerprint,
    _load_cache,
    _owner_repo,
    _sanitize_env_values,
    _snippet,
    _spec_from_ai_dict,
    _spec_from_cache_dict,
    _spec_to_cache_dict,
    _trial_arg,
    _trial_commands,
    _usability_of,
    cache_invalidate,
    cache_lookup,
    cache_store,
    from_catalog_entry,
    infer_install_spec,
    prompt_missing,
    resolve_install_spec,
    spec_to_item,
    verify_install_spec,
)

__all__ = [
    "InstallSpec",
    "VerifyResult",
    "PromptResult",
    "ResolveResult",
    "from_catalog_entry",
    "spec_to_item",
    "_sanitize_env_values",
    "_has_key_fingerprint",
    "_spec_to_cache_dict",
    "_spec_from_cache_dict",
    "_load_cache",
    "_atomic_write_json",
    "cache_lookup",
    "cache_store",
    "cache_invalidate",
    "resolve_install_spec",
    "_owner_repo",
    "_snippet",
    "_fetch_install_hints",
    "_build_infer_prompt",
    "_spec_from_ai_dict",
    "infer_install_spec",
    "_trial_arg",
    "_trial_commands",
    "verify_install_spec",
    "prompt_missing",
    "_KEY_FINGERPRINTS",
    "_CANDIDATE_BASES",
    "_INFER_SYSTEM",
    "_TRIAL_TIMEOUT",
    "_PLACEHOLDER_RE",
    "_NOT_FOUND_SIGNALS",
    "_usability_of",
]
