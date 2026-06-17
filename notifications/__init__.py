"""Notifications app package (email delivery + suppression).

Must exist as a *regular* package (this file) so the local app is never
shadowed by a same-named PEP 420 namespace portion or a pip package called
``notifications`` (e.g. django-notifications-hq). Without it, Django could
resolve the ``notifications`` label to a foreign package. App config is
autodiscovered via ``notifications.apps.NotificationsConfig``.
"""
