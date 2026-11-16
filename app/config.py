from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    db_path: str = "./data/loghour.db"
    rule_version: str = "2026.11"
    timezone: str = "Asia/Shanghai"
    # 撤回指纹盐：生产必须经环境变量注入；默认值仅供本地演示与测试。
    withdraw_salt: str = "dev-withdraw-salt"

    @classmethod
    def from_env(cls):
        return cls(db_path=os.getenv("DB_PATH", cls.db_path),
                   rule_version=os.getenv("RULE_VERSION", cls.rule_version),
                   withdraw_salt=os.getenv("WITHDRAW_SALT", cls.withdraw_salt))
