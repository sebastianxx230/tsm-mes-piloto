"""Prepara los recursos estaticos que Vercel sirve desde public/."""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'static'
TARGET = ROOT / 'public' / 'static'


def main():
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, TARGET)
    print(f'Static assets copied to {TARGET.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
