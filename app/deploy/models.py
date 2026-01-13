from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field

AuthMethod = Literal["password", "key"]
DeployEnv = Literal["machine", "docker", "k8s", "helm"]

class ServerConfig(BaseModel):
    id: str
    name: str
    host: str
    port: int = 22
    user: str = "root"
    auth_method: AuthMethod = "key"
    password: Optional[str] = None
    key_path: Optional[str] = None

class DeployService(BaseModel):
    name: Literal["nginx","mysql","mongo","elasticsearch","rabbitmq","kafka","node_exporter","mysqld_exporter","blackbox_exporter","prometheus","grafana","alertmanager"]
    version: Optional[str] = None
    config: Dict[str, str] = Field(default_factory=dict)

class DeployRequest(BaseModel):
    task_id: str
    server_ids: List[str]
    environment: DeployEnv = "docker"
    services: List[DeployService]
    cluster: bool = False
    replicas: int = 1
    namespace: str = "default"
    execute: bool = False

class DeployPlan(BaseModel):
    id: str
    req: DeployRequest
    artifacts: List[str] = Field(default_factory=list)
    commands: List[str] = Field(default_factory=list)
    status: Literal["pending","running","completed","error"] = "pending"
    error: Optional[str] = None
