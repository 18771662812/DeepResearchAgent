import os
import tempfile
from pathlib import Path

# 必须在导入 app 之前设置：测试使用临时数据库，不碰开发时的 data/research.db
_tmp = Path(tempfile.mkdtemp(prefix="dra-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}"
