"""Unit tests for K8sEnvService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rock.actions import EnvCloseRequest, EnvMakeRequest, EnvResetRequest, EnvStepRequest
from rock.config import K8sConfig
from rock.sandbox.service.env_service import K8sEnvService


@pytest.fixture
def k8s_env_service():
    """Create K8sEnvService instance with mock provider."""
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
    service = K8sEnvService(k8s_config=k8s_config)
    return service


@pytest.fixture
def mock_runtime():
    """Create mock runtime."""
    runtime = AsyncMock()
    return runtime


class TestK8sEnvService:
    """Test cases for K8sEnvService."""

    def test_initialization(self, k8s_env_service):
        """Test K8sEnvService initialization."""
        assert k8s_env_service._k8s_config is not None
        assert k8s_env_service._k8s_config.namespace == "rock-test"
        assert k8s_env_service._k8s_config.kubeconfig_path is None
        assert k8s_env_service._provider is not None

    @pytest.mark.asyncio
    async def test_env_make_success(self, k8s_env_service, mock_runtime):
        """Test env_make successfully."""
        # Mock runtime response
        mock_runtime.env_make = AsyncMock(
            return_value=AsyncMock(sandbox_id="test-sandbox-123")
        )
        
        # Mock provider to return runtime
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        request = EnvMakeRequest(env_id="test-env", sandbox_id="test-sandbox-123")
        result = await k8s_env_service.env_make(request)
        
        assert result.sandbox_id == "test-sandbox-123"
        mock_runtime.env_make.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_env_make_no_runtime(self, k8s_env_service):
        """Test env_make fails when runtime is not available."""
        # Mock provider to return None
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=None)
        
        request = EnvMakeRequest(env_id="test-env", sandbox_id="test-sandbox-123")
        
        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_env_service.env_make(request)

    @pytest.mark.asyncio
    async def test_env_step_success(self, k8s_env_service, mock_runtime):
        """Test env_step successfully."""
        # Mock runtime response
        mock_runtime.env_step = AsyncMock(
            return_value=AsyncMock(
                observation="test_obs",
                reward=1.0,
                terminated=False,
                truncated=False,
                info={}
            )
        )
        
        # Mock provider to return runtime
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        request = EnvStepRequest(sandbox_id="test-sandbox-123", action="test_action")
        result = await k8s_env_service.env_step(request)
        
        assert result.reward == 1.0
        assert result.observation == "test_obs"
        mock_runtime.env_step.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_env_step_no_runtime(self, k8s_env_service):
        """Test env_step fails when runtime is not available."""
        # Mock provider to return None
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=None)
        
        request = EnvStepRequest(sandbox_id="test-sandbox-123", action="test_action")
        
        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_env_service.env_step(request)

    @pytest.mark.asyncio
    async def test_env_reset_success(self, k8s_env_service, mock_runtime):
        """Test env_reset successfully."""
        # Mock runtime response
        mock_runtime.env_reset = AsyncMock(
            return_value=AsyncMock(observation="initial_obs", info={})
        )
        
        # Mock provider to return runtime
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        request = EnvResetRequest(sandbox_id="test-sandbox-123", seed=42)
        result = await k8s_env_service.env_reset(request)
        
        assert result.observation == "initial_obs"
        mock_runtime.env_reset.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_env_reset_no_runtime(self, k8s_env_service):
        """Test env_reset fails when runtime is not available."""
        # Mock provider to return None
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=None)
        
        request = EnvResetRequest(sandbox_id="test-sandbox-123")
        
        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_env_service.env_reset(request)

    @pytest.mark.asyncio
    async def test_env_close_success(self, k8s_env_service, mock_runtime):
        """Test env_close successfully."""
        # Mock runtime response
        mock_runtime.env_close = AsyncMock(
            return_value=AsyncMock(sandbox_id="test-sandbox-123")
        )
        
        # Mock provider to return runtime
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        request = EnvCloseRequest(sandbox_id="test-sandbox-123")
        result = await k8s_env_service.env_close(request)
        
        assert result.sandbox_id == "test-sandbox-123"
        mock_runtime.env_close.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_env_close_no_runtime(self, k8s_env_service):
        """Test env_close fails when runtime is not available."""
        # Mock provider to return None
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=None)
        
        request = EnvCloseRequest(sandbox_id="test-sandbox-123")
        
        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_env_service.env_close(request)

    @pytest.mark.asyncio
    async def test_env_list_success(self, k8s_env_service, mock_runtime):
        """Test env_list successfully."""
        # Mock runtime response
        mock_runtime.env_list = AsyncMock(
            return_value=AsyncMock(env_id=["env1", "env2"])
        )
        
        # Mock provider to return runtime
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=mock_runtime)
        
        result = await k8s_env_service.env_list("test-sandbox-123")
        
        assert result.env_id == ["env1", "env2"]
        mock_runtime.env_list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_env_list_no_runtime(self, k8s_env_service):
        """Test env_list fails when runtime is not available."""
        # Mock provider to return None
        k8s_env_service._provider.get_runtime = AsyncMock(return_value=None)
        
        with pytest.raises(Exception, match="Failed to get runtime"):
            await k8s_env_service.env_list("test-sandbox-123")
