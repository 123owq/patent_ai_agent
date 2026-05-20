import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
# scripts/ 디렉터리를 임포트 가능하게 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
