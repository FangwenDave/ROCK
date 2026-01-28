"""K8S template loader for BatchSandbox manifests."""

import copy
from typing import Any, Dict

from rock.deployments.constants import Port
from rock.logger import init_logger

logger = init_logger(__name__)


class K8sTemplateLoader:
    """Loader for K8S BatchSandbox templates."""
    
    def __init__(self, templates: Dict[str, Any], default_namespace: str = "rock"):
        """Initialize template loader.
        
        Args:
            templates: Templates dictionary from K8sConfig (required).
            default_namespace: Default K8S namespace.
        """
        if not templates:
            raise ValueError(
                "No templates provided. "
                "At least one template must be defined under 'k8s.templates' in config."
            )
        
        self._templates: Dict[str, Dict[str, Any]] = templates
        self._default_namespace = default_namespace
        
        logger.info(f"Loaded {len(self._templates)} K8S templates from config")
    

    
    def get_template(self, template_name: str = 'default') -> Dict[str, Any]:
        """Get a template by name.
        
        Args:
            template_name: Name of the template
            
        Returns:
            Deep copy of the template dictionary
            
        Raises:
            ValueError: If template not found
        """
        if template_name not in self._templates:
            available = ', '.join(self._templates.keys())
            raise ValueError(f"Template '{template_name}' not found. Available: {available}")
        
        return copy.deepcopy(self._templates[template_name])
    
    def build_manifest(
        self,
        template_name: str = 'default',
        sandbox_id: str = None,
        namespace: str = None,
        image: str = None,
        cpus: float = None,
        memory: str = None,
        auto_clear_time_minutes: int = None,
    ) -> Dict[str, Any]:
        """Build a complete BatchSandbox manifest from template.
        
        Template structure:
        - ports: custom port configuration (not part of K8S manifest)
        - template: corresponds to spec.template in BatchSandbox CRD
          - template.metadata -> spec.template.metadata
          - template.spec -> spec.template.spec (Pod spec)
        
        Top-level fields are hardcoded:
        - apiVersion: sandbox.opensandbox.io/v1alpha1
        - kind: BatchSandbox
        - metadata: constructed from parameters
        - spec.replicas: always 1
        
        Args:
            template_name: Name of the template to use
            sandbox_id: Sandbox identifier
            namespace: K8S namespace
            image: Container image
            cpus: CPU resource limit
            memory: Memory resource limit (normalized format like '2Gi')
            auto_clear_time_minutes: Auto cleanup time in minutes
            
        Returns:
            Complete BatchSandbox manifest
        """
        import uuid
        
        # Get template configuration
        config = self.get_template(template_name)
        
        # Get enable_resource_speedup from template (default to True)
        enable_resource_speedup = config.get('enable_resource_speedup', True)
        
        # Extract template (corresponds to spec.template in BatchSandbox)
        pod_template = config.get('template', {})
        template_metadata = copy.deepcopy(pod_template.get('metadata', {}))
        pod_spec = copy.deepcopy(pod_template.get('spec', {}))
        
        # Generate sandbox_id if not provided
        if not sandbox_id:
            sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"
        
        # Build top-level BatchSandbox manifest (hardcoded structure)
        manifest = {
            'apiVersion': 'sandbox.opensandbox.io/v1alpha1',
            'kind': 'BatchSandbox',
            'metadata': {
                'name': sandbox_id,
                'namespace': namespace or self._default_namespace,
                'labels': {
                    'sandbox-id': sandbox_id,
                    'template': template_name,
                },
                'annotations': {
                    'rock.sandbox/template': template_name,
                }
            },
            'spec': {
                'replicas': 1,  # Always 1 for sandbox
                'template': {
                    'metadata': template_metadata,
                    'spec': pod_spec
                }
            }
        }
        
        # Add resource speedup label if enabled
        if enable_resource_speedup:
            manifest['metadata']['labels']['batchsandbox.alibabacloud.com/resource-speedup'] = 'true'
        
        # Add sandbox-id label to template metadata
        if 'labels' not in manifest['spec']['template']['metadata']:
            manifest['spec']['template']['metadata']['labels'] = {}
        manifest['spec']['template']['metadata']['labels']['sandbox-id'] = sandbox_id
        
        # Set image annotation
        if image:
            manifest['metadata']['annotations']['rock.sandbox/image'] = image
        
        # Set container image
        if image:
            containers = pod_spec.get('containers', [])
            if containers and len(containers) > 0:
                containers[0]['image'] = image
        
        # Set resources if provided
        if cpus is not None or memory is not None:
            containers = pod_spec.get('containers', [])
            if containers and len(containers) > 0:
                if 'resources' not in containers[0]:
                    containers[0]['resources'] = {}
                
                if cpus is not None or memory is not None:
                    containers[0]['resources']['requests'] = {}
                    containers[0]['resources']['limits'] = {}
                    
                    if cpus is not None:
                        containers[0]['resources']['requests']['cpu'] = str(cpus)
                        containers[0]['resources']['limits']['cpu'] = str(cpus)
                    
                    if memory is not None:
                        containers[0]['resources']['requests']['memory'] = memory
                        containers[0]['resources']['limits']['memory'] = memory
        
        return manifest
    
    @property
    def available_templates(self) -> list[str]:
        """Get list of available template names."""
        return list(self._templates.keys())
    
    @property
    def default_namespace(self) -> str:
        """Get default namespace."""
        return self._default_namespace
    
    def get_ports(self, template_name: str = 'default') -> Dict[str, int]:
        """Get port configuration from template.
        
        Args:
            template_name: Name of the template
            
        Returns:
            Dictionary with port configuration (proxy, server, ssh)
            
        Raises:
            ValueError: If template not found or ports not configured
        """
        if template_name not in self._templates:
            available = ', '.join(self._templates.keys())
            raise ValueError(f"Template '{template_name}' not found. Available: {available}")
        
        template = self._templates[template_name]
        ports = template.get('ports', {})
        
        if not ports:
            # Return default ports if not configured in template
            logger.warning(f"Template '{template_name}' has no port configuration, using defaults")
            return {
                'proxy': Port.PROXY.value,
                'server': Port.SERVER.value,
                'ssh': Port.SSH.value,
            }
        
        return ports.copy()
