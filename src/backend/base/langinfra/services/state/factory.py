from typing_extensions import override

from langinfra.services.factory import ServiceFactory
from langinfra.services.settings.service import SettingsService
from langinfra.services.state.service import InMemoryStateService


class StateServiceFactory(ServiceFactory):
    def __init__(self) -> None:
        super().__init__(InMemoryStateService)

    @override
    def create(self, settings_service: SettingsService):
        return InMemoryStateService(
            settings_service,
        )
