"""Unit tests for K8sDeploymentService."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rock.actions.sandbox.response import State
from rock.actions.sandbox.sandbox_info import SandboxInfo
from rock.config import K8sConfig
from rock.deployments.config import K8sDeploymentConfig
from rock.deployments.constants import Port
from rock.sandbox.service.k8s.k8s_deployment_service import K8sDeploymentService


@pytest.fixture
def k8s_deployment_service():
    """Create K8sDeploymentService instance with mock provider."""
    # Use minimal templates for testing
    test_templates = {
        "default": {
            "enable_resource_speedup": False,
            "ports": {"proxy": 8000, "server": 8080, "ssh": 22},
            "template": {
                "metadata": {"labels": {}},
                "spec": {
                    "tolerations": [{"operator": "Exists"}],
                    "containers": [{"name": "main", "image": "python:3.11"}]
                }
            }
        }
    }
    k8s_config = K8sConfig(namespace="rock-test", kubeconfig_path=None, templates=test_templates)
    service = K8sDeploymentService(k8s_config=k8s_config)
    return service


@pytest.fixture
def k8s_deployment_config():
    """Create K8sDeploymentConfig for testing."""
    sandbox_id = f"test-sandbox-{uuid.uuid4().hex[:8]}"
    return K8sDeploymentConfig(
        container_name=sandbox_id,
        image="python:3.11",
        cpus=1.0,
        memory="2g",
    )


@pytest.fixture
def mock_sandbox_info():
    """Create mock sandbox info."""
    return {
        "sandbox_id": "test-sandbox-123",
        "host_ip": "10.0.0.1",
        "host_name": "test-pod-123",
        "port_mapping": {
            Port.PROXY: 8000,
            Port.SERVER: 8080,
            Port.SSH: 22,
        },
        "state": State.PENDING,
        "alive": False,
        "image": "python:3.11",
        "cpus": 1.0,
        "memory": "2g",
    }


class TestK8sDeploymentService:
    """Test cases for K8sDeploymentService."""

    def test_initialization(self, k8s_deployment_service):
        """Test K8sDeploymentService initialization."""
        assert k8s_deployment_service._k8s_config is not None
        assert k8s_deployment_service._k8s_config.namespace == "rock-test"
        assert k8s_deployment_service._k8s_config.kubeconfig_path is None
        assert k8s_deployment_service._provider is not None

    @pytest.mark.asyncio
    async def test_submit_success(
        self, k8s_deployment_service, k8s_deployment_config, mock_sandbox_info
    ):
        """Test successful sandbox submission."""
        # Mock provider methods
        mock_provider = AsyncMock()
        mock_provider.create = AsyncMock(return_value=k8s_deployment_config.container_name)
        mock_provider.get_sandbox_info = AsyncMock(return_value=mock_sandbox_info.copy())
        
        # Mock runtime - is_alive should accept timeout parameter
        mock_runtime = AsyncMock()
        # Create a proper async function that accepts timeout and returns the response
        async def mock_is_alive(timeout=None):
            response = AsyncMock()
            response.is_alive = True
            return response
        mock_runtime.is_alive = mock_is_alive
        mock_provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        k8s_deployment_service._provider = mock_provider

        user_info = {
            "user_id": "test_user",
            "experiment_id": "test_exp",
            "namespace": "test_ns",
            "rock_authorization": "test_auth",
        }

        result = await k8s_deployment_service.submit(k8s_deployment_config, user_info)

        assert result["sandbox_id"] == mock_sandbox_info["sandbox_id"]
        assert result["host_ip"] == mock_sandbox_info["host_ip"]
        assert result["user_id"] == "test_user"
        assert result["experiment_id"] == "test_exp"
        assert result["image"] == "python:3.11"

        mock_provider.create.assert_awaited_once_with(k8s_deployment_config)
        mock_provider.get_sandbox_info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_no_host_ip(
        self, k8s_deployment_service, k8s_deployment_config
    ):
        """Test submission fails when no host IP is returned."""
        mock_provider = AsyncMock()
        mock_provider.create = AsyncMock(return_value=k8s_deployment_config.container_name)
        mock_provider.get_sandbox_info = AsyncMock(return_value={"sandbox_id": "test", "host_ip": ""})
        mock_provider.delete = AsyncMock()
        
        k8s_deployment_service._provider = mock_provider

        with pytest.raises(Exception, match="Failed to get host IP"):
            await k8s_deployment_service.submit(k8s_deployment_config)

        # Verify cleanup was attempted
        mock_provider.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_status_success(
        self, k8s_deployment_service, mock_sandbox_info
    ):
        """Test getting sandbox status successfully."""
        mock_provider = AsyncMock()
        mock_provider.get_sandbox_info = AsyncMock(return_value=mock_sandbox_info.copy())
        
        # Mock runtime
        mock_runtime = AsyncMock()
        mock_runtime.is_alive = AsyncMock(return_value=AsyncMock(is_alive=True))
        mock_provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        k8s_deployment_service._provider = mock_provider

        result = await k8s_deployment_service.get_status("test-sandbox-123")

        # Result is a TypedDict, access fields like a dict
        assert result["sandbox_id"] == mock_sandbox_info["sandbox_id"]
        assert result["state"] == State.RUNNING
        assert result["alive"] is True

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, k8s_deployment_service):
        """Test getting status for non-existent sandbox."""
        mock_provider = AsyncMock()
        mock_provider.get_sandbox_info = AsyncMock(
            return_value={"_k8s_not_found": True}
        )
        
        k8s_deployment_service._provider = mock_provider

        with pytest.raises(Exception, match="not found"):
            await k8s_deployment_service.get_status("non-existent-sandbox")

    @pytest.mark.asyncio
    async def test_get_status_not_alive(
        self, k8s_deployment_service, mock_sandbox_info
    ):
        """Test getting status when sandbox is not alive."""
        mock_provider = AsyncMock()
        mock_provider.get_sandbox_info = AsyncMock(return_value=mock_sandbox_info.copy())
        mock_provider.get_runtime = AsyncMock(return_value=None)
        
        k8s_deployment_service._provider = mock_provider

        result = await k8s_deployment_service.get_status("test-sandbox-123")

        # Result is a TypedDict, access fields like a dict
        assert result["state"] == State.PENDING
        assert result["alive"] is False

    @pytest.mark.asyncio
    async def test_stop_success(self, k8s_deployment_service):
        """Test stopping sandbox successfully."""
        mock_provider = AsyncMock()
        mock_provider.delete = AsyncMock(return_value=True)
        
        k8s_deployment_service._provider = mock_provider

        await k8s_deployment_service.stop("test-sandbox-123")

        mock_provider.delete.assert_awaited_once_with("test-sandbox-123")

    @pytest.mark.asyncio
    async def test_stop_not_found(self, k8s_deployment_service):
        """Test stopping non-existent sandbox raises exception."""
        mock_provider = AsyncMock()
        mock_provider.delete = AsyncMock(return_value=False)
        
        k8s_deployment_service._provider = mock_provider

        # Now should raise exception when delete returns False
        with pytest.raises(Exception, match="Failed to stop sandbox"):
            await k8s_deployment_service.stop("non-existent-sandbox")

    @pytest.mark.asyncio
    async def test_get_sandbox_statistics_success(self, k8s_deployment_service):
        """Test getting sandbox statistics."""
        mock_runtime = AsyncMock()
        mock_runtime.get_statistics = AsyncMock(
            return_value={"cpu": 10.5, "mem": 20.3, "disk": 30.1, "net": 1024}
        )
        
        mock_provider = AsyncMock()
        mock_provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        k8s_deployment_service._provider = mock_provider

        result = await k8s_deployment_service.get_sandbox_statistics("test-sandbox-123")

        assert result["cpu"] == 10.5
        assert result["mem"] == 20.3
        assert result["disk"] == 30.1
        assert result["net"] == 1024

    @pytest.mark.asyncio
    async def test_get_sandbox_statistics_no_runtime(self, k8s_deployment_service):
        """Test getting statistics when runtime is not available."""
        mock_provider = AsyncMock()
        mock_provider.get_runtime = AsyncMock(return_value=None)
        
        k8s_deployment_service._provider = mock_provider

        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_deployment_service.get_sandbox_statistics("test-sandbox-123")

    @pytest.mark.asyncio
    async def test_get_runtime_success(self, k8s_deployment_service):
        """Test getting runtime successfully."""
        mock_runtime = AsyncMock()
        mock_provider = AsyncMock()
        mock_provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        k8s_deployment_service._provider = mock_provider

        result = await k8s_deployment_service.get_runtime("test-sandbox-123")

        assert result == mock_runtime

    @pytest.mark.asyncio
    async def test_get_runtime_not_found(self, k8s_deployment_service):
        """Test getting runtime for non-existent sandbox."""
        mock_provider = AsyncMock()
        mock_provider.get_runtime = AsyncMock(return_value=None)
        
        k8s_deployment_service._provider = mock_provider

        result = await k8s_deployment_service.get_runtime("non-existent-sandbox")

        assert result is None
