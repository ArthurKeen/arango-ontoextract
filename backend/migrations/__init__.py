"""Database migration framework for AOE.

Migrations are numbered Python modules with an ``up(db)`` function.
The runner applies them in filename order and tracks state in ``_system_meta``.
"""
