"""K8s provider implementations for managing sandbox resources."""

from abc import abstractmethod
from typing import Any, Dict, Optional, Protocol

from kubernetes import client, config as k8s_config
import json
import asyncio

from rock.config import K8sConfig
from rock.deployments.config import K8sDeploymentConfig
from rock.deployments.constants import Port
from .template_loader import K8sTemplateLoader
from rock.sandbox.remote_sandbox import RemoteSandboxRuntime
from rock.actions.sandbox.config import RemoteSandboxRuntimeConfig
from rock.actions.sandbox.sandbox_info import SandboxInfo
from rock.actions.sandbox.response import State
from rock.logger import init_logger


logger = init_logger(__name__)


class K8sProvider(Protocol):
    """Base K8s provider interface."""
    
    def __init__(self, namespace: str = "rock", kubeconfig_path: str | None = None):
        ...
    
    async def _ensure_initialized(self):
        """Ensure K8s client is initialized."""
        ...
    
    @abstractmethod
    async def create(self, config: K8sDeploymentConfig) -> str:
        """Create a sandbox resource.
        
        Args:
            config: K8s deployment configuration
            
        Returns:
            The sandbox ID (typically the resource name)
        """
        pass
    
    @abstractmethod
    async def delete(self, sandbox_id: str) -> bool:
        """Delete a sandbox resource.
        
        Args:
            sandbox_id: ID of the sandbox to delete
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_sandbox_info(self, sandbox_id: str) -> SandboxInfo:
        """Get sandbox information.
        
        Args:
            sandbox_id: ID of the sandbox
            
        Returns:
            SandboxInfo object with sandbox details
        """
        pass
    
    @abstractmethod
    async def get_runtime(self, sandbox_id: str) -> Optional[RemoteSandboxRuntime]:
        """Get runtime for communicating with the sandbox.
        
        Args:
            sandbox_id: ID of the sandbox
            
        Returns:
            RemoteSandboxRuntime instance or None if not available
        """
        pass


class BatchSandboxProvider(K8sProvider):
    """Provider for BatchSandbox CRD."""
    
    CRD_GROUP = "sandbox.opensandbox.io"
    CRD_VERSION = "v1alpha1"
    CRD_PLURAL = "batchsandboxes"
    ANNOTATION_ENDPOINTS = "sandbox.opensandbox.io/endpoints"
    
    def __init__(self, k8s_config: K8sConfig):
        """Initialize BatchSandbox provider.
        
        Args:
            k8s_config: K8S configuration from RockConfig
        """
        self.namespace = k8s_config.namespace
        self.kubeconfig_path = k8s_config.kubeconfig_path
        self._api_client = None
        self._initialized = False
        
        # Initialize template loader with templates from config
        self._template_loader = K8sTemplateLoader(templates=k8s_config.templates, default_namespace=k8s_config.namespace)
        logger.info(f"Available K8S templates: {', '.join(self._template_loader.available_templates)}")
    
    async def _ensure_initialized(self):
        """Ensure K8s client is initialized."""
        if self._initialized:
            return
            
        try:
            if self.kubeconfig_path:
                k8s_config.load_kube_config(config_file=self.kubeconfig_path)
            else:
                # Try in-cluster config first, fallback to default kubeconfig
                try:
                    k8s_config.load_incluster_config()
                except k8s_config.ConfigException:
                    k8s_config.load_kube_config()
                    
            self._api_client = client.ApiClient()
            self._initialized = True
            logger.info(f"Initialized K8s provider for namespace: {self.namespace}")
        except Exception as e:
            logger.error(f"Failed to initialize K8s client: {e}", exc_info=True)
            raise
    
    def _normalize_memory(self, memory: str) -> str:
        """Normalize memory format to Kubernetes standard.
        
        Convert formats like '2g', '2G', '2048m' to K8s format like '2Gi', '2048Mi'.
        """
        import re
        
        # Already in K8s format
        if re.match(r'^\d+(\.\d+)?(Ei|Pi|Ti|Gi|Mi|Ki)$', memory):
            return memory
        
        # Parse value and unit
        match = re.match(r'^(\d+(\.\d+)?)([a-zA-Z]*)$', memory)
        if not match:
            # Fallback: assume it's bytes and convert to Mi
            try:
                bytes_val = int(memory)
                return f"{bytes_val // (1024 * 1024)}Mi"
            except:
                return memory  # Return as-is if can't parse

        value = float(match.group(1))
        unit = match.group(3).lower()

        # Convert to K8s format - use int() for whole numbers, preserve decimals otherwise
        if unit in ('', 'b'):
            mi_value = value / (1024 * 1024)
            return f"{int(mi_value) if mi_value == int(mi_value) else mi_value:.2f}Mi"
        elif unit in ('k', 'kb'):
            return f"{int(value) if value == int(value) else value:.2f}Ki"
        elif unit in ('m', 'mb'):
            return f"{int(value) if value == int(value) else value:.2f}Mi"
        elif unit in ('g', 'gb'):
            return f"{int(value) if value == int(value) else value:.2f}Gi"
        elif unit in ('t', 'tb'):
            return f"{int(value) if value == int(value) else value:.2f}Ti"
        else:
            return memory

    def _build_batchsandbox_manifest(self, config: K8sDeploymentConfig) -> tuple[dict[str, Any], str]:
        """Build BatchSandbox manifest from template and deployment config.
        
        This method uses the template loader to get a base template and only sets
        the user-configurable parameters from SandboxStartRequest:
        - image
        - cpus
        - memory
        - auto_clear_time_minutes
        
        All other fields (command, volumes, tolerations, etc.) come from the template.
        """
        import uuid
        
        # Generate sandbox_id
        sandbox_id = config.container_name or f"sandbox-{uuid.uuid4().hex[:8]}"
        
        # Build manifest using template loader
        manifest = self._template_loader.build_manifest(
            template_name=config.template_name,
            sandbox_id=sandbox_id,
            namespace=self.namespace,
            image=config.image,
            cpus=config.cpus,
            memory=self._normalize_memory(config.memory),
            auto_clear_time_minutes=config.auto_clear_time_minutes,
        )
        
        logger.debug(f"Built BatchSandbox manifest for {sandbox_id} using template '{config.template_name}'")
        return manifest, sandbox_id

    async def create(self, config: K8sDeploymentConfig) -> str:
        """Create a BatchSandbox resource and wait for IP allocation."""
        await self._ensure_initialized()
        
        try:
            manifest, sandbox_id = self._build_batchsandbox_manifest(config)
            
            # Create BatchSandbox resource
            api_instance = client.CustomObjectsApi(self._api_client)
            await asyncio.to_thread(
                api_instance.create_namespaced_custom_object,
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                body=manifest
            )
            
            logger.info(f"Created BatchSandbox: {sandbox_id}, waiting for IP allocation...")
            
            # Wait for endpoints annotation to be set by controller
            max_retries = 30  # Wait up to 60 seconds (30 * 2s)
            retry_interval = 2.0
            
            for attempt in range(max_retries):
                try:
                    resource = await asyncio.to_thread(
                        api_instance.get_namespaced_custom_object,
                        group=self.CRD_GROUP,
                        version=self.CRD_VERSION,
                        namespace=self.namespace,
                        plural=self.CRD_PLURAL,
                        name=sandbox_id
                    )
                    
                    # Check if endpoints annotation is set
                    annotations = resource.get("metadata", {}).get("annotations", {})
                    endpoints_str = annotations.get(self.ANNOTATION_ENDPOINTS)
                    
                    if endpoints_str:
                        try:
                            pod_ips = json.loads(endpoints_str)
                            if pod_ips and pod_ips[0]:
                                logger.info(f"Got IP for sandbox {sandbox_id}: {pod_ips[0]}")
                                return sandbox_id
                        except (json.JSONDecodeError, TypeError, IndexError):
                            pass
                    
                    if attempt < max_retries - 1:
                        logger.debug(f"Attempt {attempt + 1}/{max_retries}: Waiting for IP allocation for {sandbox_id}")
                        await asyncio.sleep(retry_interval)
                    else:
                        logger.warning(f"IP not allocated for {sandbox_id} after {max_retries} attempts")
                        raise Exception(f"Timeout waiting for IP allocation for sandbox {sandbox_id}")
                        
                except client.exceptions.ApiException as e:
                    if e.status == 404:
                        logger.error(f"BatchSandbox {sandbox_id} not found during IP wait")
                        raise Exception(f"Sandbox {sandbox_id} disappeared during creation")
                    raise
            
            return sandbox_id
            
        except client.exceptions.ApiException as e:
            if e.status == 409:
                logger.warning(f"BatchSandbox {sandbox_id} already exists")
                raise Exception(f"Sandbox {sandbox_id} already exists")
            logger.error(f"Failed to create BatchSandbox: {e}", exc_info=True)
            raise Exception(f"Failed to create sandbox: {e.reason}")
        except Exception as e:
            logger.error(f"Unexpected error creating sandbox: {e}", exc_info=True)
            raise

    async def delete(self, sandbox_id: str) -> bool:
        """Delete a BatchSandbox resource."""
        await self._ensure_initialized()
        
        logger.info(f"Deleting BatchSandbox: {sandbox_id}")
        
        try:
            api_instance = client.CustomObjectsApi(self._api_client)
            await asyncio.to_thread(
                api_instance.delete_namespaced_custom_object,
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                name=sandbox_id
            )
            logger.info(f"Deleted BatchSandbox: {sandbox_id}")
            return True
            
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.warning(f"BatchSandbox {sandbox_id} not found, already deleted")
                return True
            logger.error(f"Failed to delete sandbox {sandbox_id}: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting sandbox {sandbox_id}: {e}", exc_info=True)
            return False

    async def get_sandbox_info(self, sandbox_id: str) -> SandboxInfo:
        """Get sandbox information.
        
        Args:
            sandbox_id: ID of the sandbox
            
        Returns:
            SandboxInfo object with sandbox details
        """
        await self._ensure_initialized()
        
        try:
            api_instance = client.CustomObjectsApi(self._api_client)
            resource = await asyncio.to_thread(
                api_instance.get_namespaced_custom_object,
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                name=sandbox_id
            )
            
            # Extract status information
            status = resource.get("status", {})
            metadata = resource.get("metadata", {})
            spec = resource.get("spec", {})
            
            # Parse endpoints from annotations
            annotations = metadata.get("annotations", {})
            endpoints_str = annotations.get(self.ANNOTATION_ENDPOINTS)
            pod_ips = []
            if endpoints_str:
                try:
                    pod_ips = json.loads(endpoints_str)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse endpoints for {sandbox_id}: {endpoints_str}")
            
            # Get pod IP for host_ip if available
            host_ip = pod_ips[0] if pod_ips else ""
            
            # Extract image from annotations
            image = annotations.get("rock.sandbox/image", "")
            
            # Get port configuration from template used to create this sandbox
            template_name = annotations.get("rock.sandbox/template", "default")
            ports_config = self._template_loader.get_ports(template_name)
            
            # K8S mode: Pod uses direct IP access, port_mapping maps Port enum to actual pod ports
            # Port.PROXY (22555) -> 8000, Port.SERVER (8080) -> 8080, Port.SSH (22) -> 22
            # This maintains compatibility with ServiceStatus.get_mapped_port(Port.PROXY)
            port_mapping = {
                Port.PROXY: ports_config['proxy'],      # 22555 -> 8000
                Port.SERVER: ports_config['server'],    # 8080 -> 8080  
                Port.SSH: ports_config['ssh'],          # 22 -> 22
            }
            
            return SandboxInfo(
                sandbox_id=sandbox_id,
                host_name=sandbox_id,
                host_ip=host_ip,
                state=State.RUNNING if status.get("ready", 0) > 0 else State.PENDING,
                image=image,
                port_mapping=port_mapping,
                phases={},  # K8S mode doesn't use phases, but we need to provide empty dict for compatibility
            )
            
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.warning(f"BatchSandbox {sandbox_id} not found")
                return SandboxInfo(
                    sandbox_id=sandbox_id,
                    host_name=sandbox_id,
                    host_ip="",
                    state=State.PENDING,
                    _k8s_not_found=True,  # type: ignore
                )
            logger.error(f"Failed to get status for {sandbox_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting status for {sandbox_id}: {e}", exc_info=True)
            raise

    async def get_runtime(self, sandbox_id: str) -> Optional[RemoteSandboxRuntime]:
        """Get runtime for communicating with the sandbox."""
        await self._ensure_initialized()
        
        try:
            # Get the BatchSandbox resource to find pod IP
            status_info = await self.get_sandbox_info(sandbox_id)
            
            # Check if sandbox was not found
            if status_info.get("_k8s_not_found"):
                logger.warning(f"Sandbox {sandbox_id} not found")
                return None
            
            # Use host_ip directly (it's the pod IP)
            host_ip = status_info.get("host_ip", "")
            if not host_ip:
                logger.warning(f"No host IP available for sandbox {sandbox_id}")
                return None
            
            # Create RemoteSandboxRuntime
            # Get port configuration from port_mapping
            port_mapping = status_info.get("port_mapping", {})
            # In K8S mode, port_mapping is {Port.PROXY: 8000, Port.SERVER: 8080, Port.SSH: 22}
            proxy_port = port_mapping.get(Port.PROXY, 8000)
            
            runtime_config = RemoteSandboxRuntimeConfig(
                host=f"http://{host_ip}",
                port=proxy_port,
                timeout=30.0
            )
            runtime = RemoteSandboxRuntime.from_config(runtime_config)
            
            # Test if the runtime is alive
            try:
                is_alive_response = await runtime.is_alive(timeout=5.0)
                if is_alive_response.is_alive:
                    logger.info(f"Successfully connected to runtime for sandbox {sandbox_id} at {host_ip}")
                    return runtime
                else:
                    logger.warning(f"Runtime for sandbox {sandbox_id} is not alive: {is_alive_response.message}")
                    return None
            except Exception as e:
                logger.warning(f"Failed to connect to runtime for sandbox {sandbox_id}: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get runtime for sandbox {sandbox_id}: {e}", exc_info=True)
            return None