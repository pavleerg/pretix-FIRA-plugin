from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_FIRA_plugin"
    verbose_name = "FIRAPlugin"

    class PretixPluginMeta:
        name = gettext_lazy("FIRAPlugin")
        author = "Pavle Ergović"
        description = gettext_lazy("A pretix plugin that integrates FIRA v1.0")
        visible = True
        version = __version__
        category = "INTEGRATION"
        compatibility = "pretix>=2.7.0"
        settings_links = []
        navigation_links = []

    def ready(self):
        from . import signals  # NOQA
