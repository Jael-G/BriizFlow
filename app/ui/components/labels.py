"""Text labels with a fixed typographic hierarchy.

Every label is a plain QLabel with an objectName the global QSS styles
(``QLabel#title``, ``#subtitle``, ``#body``, ``#bodyStrong``, ``#caption``,
``#pageSubtitle``). No inline styling — font sizes live in theme/dark.qss.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

_OBJECT_NAMES = {
    "title": "title",
    "subtitle": "subtitle",
    "body": "body",
    "bodyStrong": "bodyStrong",
    "caption": "caption",
    "pageSubtitle": "pageSubtitle",
}


class _Text(QLabel):
    def __init__(self, text="", parent=None, wrap=False, selectable=False):
        super().__init__(text, parent)
        if wrap:
            self.setWordWrap(True)
        if selectable:
            self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setCursor(Qt.IBeamCursor if selectable else Qt.ArrowCursor)


class Title(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["title"])


class Subtitle(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["subtitle"])


class Body(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["body"])


class BodyStrong(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["bodyStrong"])


class Caption(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["caption"])


class PageSubtitle(_Text):
    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setObjectName(_OBJECT_NAMES["pageSubtitle"])
