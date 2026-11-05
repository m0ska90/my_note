import sys
import os

# Добавляем корень проекта в sys.path для корректных импортов
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from main import is_already_running, main
from ui.main_window import NotesApp


if __name__ == "__main__":
    main()
