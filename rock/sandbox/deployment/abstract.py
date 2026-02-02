from abc import ABC, abstractmethod

from rock.actions.sandbox.sandbox_info import SandboxInfo
from rock.deployments.config import DeploymentConfig


class AbstractDeployment(ABC):
    @abstractmethod
    async def submit(self, config: DeploymentConfig) -> SandboxInfo:
        ...

    @abstractmethod
    async def get_status(self, sandbox_id: str) -> SandboxInfo:
        ...

    @abstractmethod
    async def stop(self, sandbox_id: str) -> bool:
        ...