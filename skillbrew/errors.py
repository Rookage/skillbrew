"""skillbrew 异常体系（结构化错误，D21/D22 友好报错）。

用法：
    from .errors import SkillbrewError, StepFailed, ConfigError, NetworkError
    raise StepFailed("字幕和视觉都为空，无法生成消化计划。"，
                     hint="先跑 skillbrew understand 生成字幕，或配置视觉模型。")
"""


class SkillbrewError(Exception):
    """所有 skillbrew 异常的基类。CLI 顶层 catch 时打印中文报错，不显示 traceback。"""
    def __init__(self, message: str = "", *, hint: str = ""):
        super().__init__(message)
        self.hint = hint  # 给用户的下一步建议


class StepFailed(SkillbrewError):
    """管线步骤可恢复的失败（文件缺失、LLM 调用缺 key 等）。"""


class ConfigError(SkillbrewError):
    """配置问题：缺少 .env、key 缺失、模型 ID 无效。"""


class NetworkError(SkillbrewError):
    """网络问题：连接失败、超时、远端关闭。通常可退避重试，用尽后抛出。"""
