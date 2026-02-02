import pytest

from rock.actions.sandbox.sandbox_info import SandboxInfo
from rock.deployments.config import DockerDeploymentConfig
from rock.sandbox.deployment.ray import RayDeployment


@pytest.mark.asyncio
async def test_ray_deployment():
    ray_deployment = RayDeployment()
    start_response: SandboxInfo = await ray_deployment.submit(DockerDeploymentConfig())
    assert start_response.get("sandbox_id") == "test"
    assert start_response.get("host_name") == "test"
    assert start_response.get("host_ip") == "test"

    stop_response: bool = await ray_deployment.stop("test")
    assert stop_response

    status_response: SandboxInfo = await ray_deployment.get_status("test")
    assert status_response.get("sandbox_id") == "test"
    assert status_response.get("host_name") == "test"
    assert status_response.get("host_ip") == "test"