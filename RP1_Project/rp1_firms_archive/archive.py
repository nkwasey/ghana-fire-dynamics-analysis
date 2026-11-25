"""Run from any working directory: python archive.py build --config configs/archive.yaml."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from ghana_fire_archive.cli import main
if __name__ == '__main__':
    main()
