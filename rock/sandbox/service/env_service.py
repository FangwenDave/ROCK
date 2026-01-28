from abc import ABC, abstractmethod

from rock.actions.envs.request import EnvCloseRequest, EnvMakeRequest, EnvResetRequest, EnvStepRequest
from rock.actions.envs.response import EnvCloseResponse, EnvListResponse, EnvMakeResponse, EnvResetResponse, EnvStepResponse
from rock.admin.core.ray_service import RayService
from rock.config import K8sConfig
from rock.logger import init_logger
from rock.sandbox.sandbox_actor import SandboxActor

logger = init_logger(__name__)


class AbstractEnvService(ABC):
    @abstractmethod
    async def env_step(self, request: EnvStepRequest) -> EnvStepResponse:
        ...

    @abstractmethod
    async def env_make(self, request: EnvMakeRequest) -> EnvMakeResponse:
        ...
    
    @abstractmethod
    async def env_reset(self, request: EnvResetRequest) -> EnvResetResponse:
        ...

    @abstractmethod
    async def env_close(self, request: EnvCloseRequest) -> EnvCloseResponse:
        ...
    
    @abstractmethod
    async def env_list(self, sandbox_id) -> EnvListResponse:
        ...


class RayEnvService(AbstractEnvService):
    def __init__(self, ray_namespace: str, ray_service: RayService):
        self._ray_namespace = ray_namespace
        self._ray_service = ray_service

    def _get_actor_name(self, sandbox_id):
        return f"sandbox-{sandbox_id}"

    async def env_step(self, request: EnvStepRequest) -> EnvStepResponse:
        sandbox_id = request.sandbox_id
        actor: SandboxActor = await self._ray_service.async_ray_get_actor(self._get_actor_name(sandbox_id))
        result = await self._ray_service.async_ray_get(actor.env_step.remote(request))
        logger.info(f"env_step: {result}")
        return result

    async def env_make(self, request: EnvMakeRequest) -> EnvMakeResponse:
        sandbox_id = request.sandbox_id
        actor: SandboxActor = await self._ray_service.async_ray_get_actor(self._get_actor_name(sandbox_id))
        result = await self._ray_service.async_ray_get(actor.env_make.remote(request))
        logger.info(f"env_make: {result}")
        return result

    async def env_reset(self, request: EnvResetRequest) -> EnvResetResponse:
        sandbox_id = request.sandbox_id
        actor: SandboxActor = await self._ray_service.async_ray_get_actor(self._get_actor_name(sandbox_id))
        result = await self._ray_service.async_ray_get(actor.env_reset.remote(request))
        logger.info(f"env_reset: {result}")
        return result

    async def env_close(self, request: EnvCloseRequest) -> EnvCloseResponse:
        sandbox_id = request.sandbox_id
        actor: SandboxActor = await self._ray_service.async_ray_get_actor(self._get_actor_name(sandbox_id))
        result = await self._ray_service.async_ray_get(actor.env_close.remote(request))
        logger.info(f"env_close: {result}")
        return result

    async def env_list(self, sandbox_id) -> EnvListResponse:
        actor: SandboxActor = await self._ray_service.async_ray_get_actor(self._get_actor_name(sandbox_id))
        result = await self._ray_service.async_ray_get(actor.env_list.remote())
        logger.info(f"env_list: {result}")
        return result


class K8sEnvService(AbstractEnvService):
    """K8S-based environment service implementation."""
    
    def __init__(self, k8s_config: K8sConfig):
        """Initialize K8S environment service.
        
        Args:
            k8s_config: K8S configuration from RockConfig
        """
        from rock.sandbox.service.k8s.k8s_provider import BatchSandboxProvider
        
        self._k8s_config = k8s_config
        
        # Create provider instance once during initialization
        # Currently only batchsandbox provider is supported
        self._provider = BatchSandboxProvider(k8s_config=k8s_config)
    
    async def _get_runtime(self, sandbox_id: str):
        """Get runtime for sandbox.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            RemoteSandboxRuntime instance
            
        Raises:
            Exception: If runtime not found
        """
        runtime = await self._provider.get_runtime(sandbox_id)
        if not runtime:
            raise Exception(f"Failed to get runtime for sandbox {sandbox_id}")
        return runtime
    
    async def env_step(self, request: EnvStepRequest) -> EnvStepResponse:
        """Execute environment step.
        
        Args:
            request: EnvStepRequest with sandbox_id and action
            
        Returns:
            EnvStepResponse with observation, reward, terminated, truncated, info
        """
        runtime = await self._get_runtime(request.sandbox_id)
        result = await runtime.env_step(request)
        logger.info(f"env_step: {result}")
        return result
    
    async def env_make(self, request: EnvMakeRequest) -> EnvMakeResponse:
        """Create new environment instance.
        
        Args:
            request: EnvMakeRequest with env_id and sandbox_id
            
        Returns:
            EnvMakeResponse with sandbox_id
        """
        runtime = await self._get_runtime(request.sandbox_id)
        result = await runtime.env_make(request)
        logger.info(f"env_make: {result}")
        return result
    
    async def env_reset(self, request: EnvResetRequest) -> EnvResetResponse:
        """Reset environment to initial state.
        
        Args:
            request: EnvResetRequest with sandbox_id and optional seed
            
        Returns:
            EnvResetResponse with observation and info
        """
        runtime = await self._get_runtime(request.sandbox_id)
        result = await runtime.env_reset(request)
        logger.info(f"env_reset: {result}")
        return result
    
    async def env_close(self, request: EnvCloseRequest) -> EnvCloseResponse:
        """Close environment and release resources.
        
        Args:
            request: EnvCloseRequest with sandbox_id
            
        Returns:
            EnvCloseResponse with sandbox_id
        """
        runtime = await self._get_runtime(request.sandbox_id)
        result = await runtime.env_close(request)
        logger.info(f"env_close: {result}")
        return result
    
    async def env_list(self, sandbox_id: str) -> EnvListResponse:
        """List all available environments.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            EnvListResponse with list of environment IDs
        """
        runtime = await self._get_runtime(sandbox_id)
        result = await runtime.env_list()
        logger.info(f"env_list: {result}")
        return result