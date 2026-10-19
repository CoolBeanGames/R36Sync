"""
R36Sync Entry Point
Run with: py main.py
"""
import sys
from r36sync.gui import R36SyncApp


def main():
    app = R36SyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
