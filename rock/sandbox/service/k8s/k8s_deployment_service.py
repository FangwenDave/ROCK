"""K8s Deployment Service implementation."""

from typing import Any, Dict

from rock.actions.sandbox.response import State, SystemResourceMetrics
from rock.actions.sandbox.sandbox_info import SandboxInfo
from rock.config import K8sConfig
from rock.deployments.config import K8sDeploymentConfig
from rock.logger import init_logger
from rock.sandbox.remote_sandbox import RemoteSandboxRuntime
from rock.sandbox.service.deployment.abstract import AbstractDeploymentService
from rock.utils import wait_until_alive

from .k8s_provider import BatchSandboxProvider

logger = init_logger(__name__)


class K8sDeploymentService(AbstractDeploymentService):
    """K8s-based deployment service."""
    
    def __init__(self, k8s_config: K8sConfig):
        """Initialize K8s deployment service.
        
        Args:
            k8s_config: K8S configuration from RockConfig
        """
        self._k8s_config = k8s_config
        
        # Create provider instance once during initialization
        # Currently only batchsandbox provider is supported
        self._provider = BatchSandboxProvider(k8s_config=k8s_config)
        
        # Load template loader for port configuration (uses same templates)
        from rock.sandbox.service.k8s.template_loader import K8sTemplateLoader
        self._template_loader = K8sTemplateLoader(templates=k8s_config.templates, default_namespace=k8s_config.namespace)
        
        logger.info(f"Initialized K8sDeploymentService in namespace: {k8s_config.namespace}")
    
    async def _wait_until_alive(self, sandbox_id: str, timeout: float = 30.0):
        """Wait until the sandbox is alive.
        
        Args:
            sandbox_id: Sandbox identifier
            timeout: Maximum time to wait for sandbox to become alive
        """
        try:
            runtime = await self._provider.get_runtime(sandbox_id)
            if runtime:
                # Wait until the runtime is alive
                # Lambda needs to accept timeout parameter from wait_until_alive
                await wait_until_alive(
                    lambda timeout=None: runtime.is_alive(timeout=timeout), 
                    timeout=timeout, 
                    function_timeout=5.0
                )
                logger.info(f"Sandbox {sandbox_id} is alive")
            else:
                logger.warning(f"Could not get runtime for sandbox {sandbox_id}, skipping alive check")
        except TimeoutError:
            logger.error(f"Sandbox {sandbox_id} did not become alive within {timeout}s timeout")
            raise
        except Exception as e:
            logger.error(f"Error while waiting for sandbox {sandbox_id} to become alive: {e}", exc_info=True)
            raise
    
    async def submit(self, config: K8sDeploymentConfig, user_info: dict = {}) -> SandboxInfo:
        """Submit a new sandbox deployment to Kubernetes.
        
        Args:
            config: K8s deployment configuration
            user_info: User metadata (user_id, experiment_id, namespace)
            
        Returns:
            SandboxInfo with sandbox metadata
        """
        sandbox_id = config.container_name
        logger.info(f"Submitting sandbox {sandbox_id} to K8s")
        
        try:
            # Create the sandbox resource (this will wait for IP allocation)
            created_sandbox_id = await self._provider.create(config)
            
            # Get sandbox info with IP from K8S
            sandbox_info = await self._provider.get_sandbox_info(created_sandbox_id)
            host_ip = sandbox_info.get("host_ip", "")
            
            if not host_ip:
                raise Exception(f"Failed to get host IP for sandbox {created_sandbox_id}")
            
            logger.info(f"Got sandbox info for {created_sandbox_id} with IP: {host_ip}")
            
            # Extract user info
            user_id = user_info.get("user_id", "default")
            experiment_id = user_info.get("experiment_id", "default")
            namespace = user_info.get("namespace", "default")
            rock_authorization = user_info.get("rock_authorization", "default")
            
            # Update sandbox_info with user metadata and config
            sandbox_info["user_id"] = user_id
            sandbox_info["experiment_id"] = experiment_id
            sandbox_info["namespace"] = namespace
            sandbox_info["rock_authorization"] = rock_authorization
            sandbox_info["image"] = config.image
            sandbox_info["cpus"] = config.cpus
            sandbox_info["memory"] = config.memory
            
            # Convert to SandboxInfo object
            result = SandboxInfo(**sandbox_info)
            
            # Wait until the sandbox is alive before returning
            await self._wait_until_alive(created_sandbox_id, timeout=30.0)
            
            logger.info(f"Sandbox {created_sandbox_id} submitted successfully")
            return result
            
        except Exception as e:
            logger.error(f"Failed to submit sandbox {sandbox_id}: {e}", exc_info=True)
            # Clean up K8s resource if submission failed after creation
            try:
                await self._provider.delete(created_sandbox_id)
                logger.info(f"Cleaned up failed sandbox {created_sandbox_id}")
            except:
                pass
            raise
    
    async def get_status(self, sandbox_id: str) -> SandboxInfo:
        """Get sandbox status.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            SandboxInfo with current status
        """
        try:
            sandbox_info = await self._provider.get_sandbox_info(sandbox_id)
            
            # Check if sandbox was not found
            if sandbox_info.get("_k8s_not_found"):
                raise Exception(f"Sandbox {sandbox_id} not found")
            
            # Determine if it's alive by trying to get runtime
            is_alive = False
            runtime = await self._provider.get_runtime(sandbox_id)
            if runtime:
                try:
                    is_alive_response = await runtime.is_alive(timeout=5.0)
                    is_alive = is_alive_response.is_alive
                except Exception as e:
                    logger.debug(f"Failed to check is_alive for {sandbox_id}: {e}")
            
            # Update state and alive status based on runtime
            updated_state = State.RUNNING if is_alive else State.PENDING
            
            # Create updated SandboxInfo with correct state and alive status
            # Remove internal K8S fields before returning
            updated_info = {k: v for k, v in sandbox_info.items() if not k.startswith("_k8s_")}
            updated_info['state'] = updated_state
            updated_info['alive'] = is_alive
            
            return SandboxInfo(**updated_info)
            
        except Exception as e:
            logger.error(f"Failed to get status for sandbox {sandbox_id}: {e}", exc_info=True)
            raise
    
    async def is_alive(self, sandbox_id: str) -> bool:
        """Check if sandbox is alive.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            True if sandbox is alive, False otherwise
        """
        try:
            runtime = await self._provider.get_runtime(sandbox_id)
            
            if runtime:
                is_alive_response = await runtime.is_alive(timeout=5.0)
                return is_alive_response.is_alive
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check is_alive for sandbox {sandbox_id}: {e}", exc_info=True)
            return False
    
    async def stop(self, sandbox_id: str) -> None:
        """Stop and delete a sandbox.
        
        Args:
            sandbox_id: Sandbox identifier
        """
        logger.info(f"Stopping sandbox {sandbox_id}")
        
        try:
            success = await self._provider.delete(sandbox_id)
            
            if success:
                logger.info(f"Sandbox {sandbox_id} stopped successfully")
            else:
                raise Exception(f"Failed to stop sandbox {sandbox_id}")
                
        except Exception as e:
            logger.error(f"Error stopping sandbox {sandbox_id}: {e}", exc_info=True)
            raise
    
    async def get_sandbox_statistics(self, sandbox_id: str) -> Dict[str, Any]:
        """Get sandbox resource statistics.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            Resource statistics dictionary with cpu, mem, disk, net metrics
        """
        logger.info(f"Getting statistics for sandbox {sandbox_id}")
        
        try:
            # Get runtime for the sandbox
            runtime = await self._provider.get_runtime(sandbox_id)
            if not runtime:
                raise Exception(f"Failed to get runtime for sandbox {sandbox_id}")
            
            # Call runtime's get_statistics() method
            result = await runtime.get_statistics()
            logger.info(f"get_sandbox_statistics: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to get statistics for sandbox {sandbox_id}: {e}", exc_info=True)
            raise
    
    async def get_runtime(self, sandbox_id: str) -> RemoteSandboxRuntime | None:
        """Get RemoteSandboxRuntime for direct communication with sandbox.
        
        Args:
            sandbox_id: Sandbox identifier
            
        Returns:
            RemoteSandboxRuntime instance or None if not found
        """
        try:
            runtime = await self._provider.get_runtime(sandbox_id)
            if runtime:
                logger.info(f"Got runtime for sandbox {sandbox_id}")
            return runtime
        except Exception as e:
            logger.warning(f"Failed to get runtime for sandbox {sandbox_id}: {e}")
            return None
    
    async def collect_system_resource_metrics(self) -> SystemResourceMetrics:
        """Collect system resource metrics.
        
        For K8S deployment mode, this is a mock implementation.
        TODO: Implement actual K8S cluster resource collection via Kubernetes Metrics API.
        
        Returns:
            SystemResourceMetrics with mock values
        """
        logger.debug("Collecting system resource metrics (mock implementation)")
        
        # Mock values - return empty metrics
        # In the future, this should query K8S cluster resources via:
        # - Kubernetes Metrics API (metrics.k8s.io/v1beta1)
        # - kubectl top nodes equivalent
        # - Custom Resource Definitions or Prometheus metrics
        return SystemResourceMetrics(
            total_cpu=0.0,
            total_memory=0.0,
            available_cpu=0.0,
            available_memory=0.0,
            gpu_count=0,
            available_gpu=0,
        )