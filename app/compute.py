"""GCP Compute Engine ops: status, start, stop. Wraps google-cloud-compute."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import compute_v1

from app.config import get_app_config, get_demo

logger = logging.getLogger(__name__)

_client: Optional[compute_v1.InstancesClient] = None


def _instances() -> compute_v1.InstancesClient:
    global _client
    if _client is None:
        _client = compute_v1.InstancesClient()
    return _client


@dataclass
class VmStatus:
    state: str  # e.g. RUNNING, TERMINATED, PROVISIONING, STAGING, STOPPING
    external_ip: Optional[str]


def get_vm_status(demo_id: str) -> VmStatus:
    demo = get_demo(demo_id)
    project = get_app_config().gcp_project_id
    try:
        instance = _instances().get(project=project, zone=demo.zone, instance=demo.instance)
    except gcp_exceptions.NotFound:
        logger.error("VM not found: %s in %s", demo.instance, demo.zone)
        raise
    ip = None
    if instance.network_interfaces and instance.network_interfaces[0].access_configs:
        ip = instance.network_interfaces[0].access_configs[0].nat_i_p or None
    return VmStatus(state=instance.status, external_ip=ip)


def start_vm(demo_id: str) -> None:
    demo = get_demo(demo_id)
    project = get_app_config().gcp_project_id
    try:
        _instances().start(project=project, zone=demo.zone, instance=demo.instance)
        logger.info("start initiated for %s", demo.instance)
    except gcp_exceptions.GoogleAPIError:
        logger.exception("start failed for %s", demo.instance)
        raise


def stop_vm(demo_id: str) -> None:
    demo = get_demo(demo_id)
    project = get_app_config().gcp_project_id
    try:
        _instances().stop(project=project, zone=demo.zone, instance=demo.instance)
        logger.info("stop initiated for %s", demo.instance)
    except gcp_exceptions.GoogleAPIError:
        logger.exception("stop failed for %s", demo.instance)
        raise