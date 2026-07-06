from django.apps import AppConfig
from django.db.models.signals import post_migrate


def create_default_groups(sender, **kwargs):
    from django.contrib.auth.models import Group

    for name in ('Admin', 'HR User'):
        Group.objects.get_or_create(name=name)


class RecruitmentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recruitment'

    def ready(self):
        post_migrate.connect(create_default_groups, sender=self)
