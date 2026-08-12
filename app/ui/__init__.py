"""BriizFlow's own UI design system (native PySide6, no Fluent).

This package replaces the qfluentwidgets layer. It provides the theme
(``app.ui.theme``), the reusable components (``app.ui.components``), the
repeated page scaffolding (``app.ui.layouts``) and the two pages themselves
(``app.ui.pages``). Pages are composed from the components instead of hand-
styling raw Qt widgets, so global design changes live in one place
(``app.ui.theme``).
"""
