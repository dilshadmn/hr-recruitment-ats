from django.apps import AppConfig
from django.db.models.signals import post_migrate


def create_default_groups(sender, **kwargs):
    from django.contrib.auth.models import Group

    from .permissions import ALL_GROUPS

    for name in ALL_GROUPS:
        Group.objects.get_or_create(name=name)


class CandidatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'candidates'

    def ready(self):
        post_migrate.connect(create_default_groups, sender=self)
