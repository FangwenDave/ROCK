import uuid

from rock import env_vars
from rock.config import RockConfig
from rock.deployments.config import AbstractDeployment, DeploymentConfig, DockerDeploymentConfig, RayDeploymentConfig, K8sDeploymentConfig
from rock.logger import init_logger
from rock.utils import sandbox_id_ctx_var

logger = init_logger(__name__)


class DeploymentManager:
    rock_config: RockConfig | None = None

    def __init__(self, rock_config: RockConfig, enable_runtime_auto_clear: bool = False, deployment_mode: str = "ray"):
        self._enable_runtime_auto_clear = enable_runtime_auto_clear
        self.rock_config = rock_config
        self._deployment_mode = deployment_mode

    def _generate_sandbox_id(self, config: DeploymentConfig) -> str:
        # Support both DockerDeploymentConfig and K8sDeploymentConfig
        if isinstance(config, (DockerDeploymentConfig, K8sDeploymentConfig)) and config.container_name:
            return config.container_name
        return uuid.uuid4().hex

    async def init_config(self, config: DeploymentConfig) -> DeploymentConfig:
        _role = env_vars.ROCK_ADMIN_ROLE
        _env = env_vars.ROCK_ADMIN_ENV
        sandbox_id = self._generate_sandbox_id(config)
        sandbox_id_ctx_var.set(sandbox_id)

        # Choose config type based on deployment mode
        if self._deployment_mode == "k8s":
            # K8S mode: convert DockerDeploymentConfig to K8sDeploymentConfig
            if isinstance(config, K8sDeploymentConfig):
                deployment_config = config
            else:
                # Convert from DockerDeploymentConfig to K8sDeploymentConfig
                k8s_fields = {
                    'image': config.image if hasattr(config, 'image') else "hub.docker.alibaba-inc.com/chatos/python:3.11",
                    'memory': config.memory if hasattr(config, 'memory') else "2g",
                    'cpus': config.cpus if hasattr(config, 'cpus') else 1.0,
                    'auto_clear_time_minutes': config.auto_clear_time_minutes if hasattr(config, 'auto_clear_time_minutes') else 30,
                    'template_name': getattr(config, 'template_name', 'default'),
                }
                deployment_config = K8sDeploymentConfig(**k8s_fields)
            
            deployment_config.container_name = sandbox_id
            # Note: K8S config doesn't need role/env/actor_resource fields
        else:
            # Ray mode
            deployment_config = RayDeploymentConfig(**config.model_dump())
            deployment_config.role = _role
            deployment_config.env = _env
            deployment_config.container_name = sandbox_id
            deployment_config.enable_auto_clear = self._enable_runtime_auto_clear
            deployment_config.runtime_config = self.rock_config.runtime

            await self.rock_config.update()
            deployment_config.actor_resource = self.rock_config.sandbox_config.actor_resource
            deployment_config.actor_resource_num = self.rock_config.sandbox_config.actor_resource_num
        
        return deployment_config

    def get_deployment(self, config: DeploymentConfig) -> AbstractDeployment:
        assert isinstance(config, RayDeploymentConfig)
        return config.get_deployment()

    def get_actor_name(self, sandbox_id):
        return f"sandbox-{sandbox_id}"
