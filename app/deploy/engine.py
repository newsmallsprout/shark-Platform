import os
import subprocess
from typing import List, Dict
from app.deploy.models import DeployRequest, DeployPlan, ServerConfig
from app.deploy.store import artifact_path, save_plan, load_server

class DeployEngine:
    def __init__(self):
        self._plans: Dict[str, DeployPlan] = {}

    def _stable_version_for(self, name: str) -> str:
        m = {
            "nginx": "1.25",
            "mysql": "8.0",
            "mongo": "6",
            "elasticsearch": "8.11.0",
            "rabbitmq": "3-management",
            "kafka": "3.6.1",
            "node_exporter": "v1.7.0",
            "mysqld_exporter": "v0.15.0",
            "blackbox_exporter": "v0.25.0",
            "prometheus": "v2.51.0",
            "grafana": "10.2.3",
            "alertmanager": "v0.27.0",
        }
        return m.get(name, "latest")

    def _get_optimized_defaults(self, name: str) -> Dict[str, str]:
        defaults = {}
        if name == "mysql":
            defaults = {
                "root_password": "rootpass",
                "innodb_buffer_pool_size": "512M",
                "max_connections": "500"
            }
        elif name == "mongo":
            defaults = {
                "wiredTigerCacheSizeGB": "0.5"
            }
        elif name == "elasticsearch":
            defaults = {
                "heap_size": "512m"
            }
        elif name == "prometheus":
            defaults = {
                "retention": "15d"
            }
        elif name == "grafana":
            defaults = {
                "admin_password": "admin"
            }
        return defaults

    def _compose_service(self, svc: Dict) -> str:
        n = svc["name"]
        v = svc.get("version") or ""
        cfg = svc.get("config", {})
        
        if n == "nginx":
            return f"""  nginx:
    image: nginx:{v or "1.25"}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
"""
        if n == "mysql":
            pwd = cfg.get("root_password", "rootpass")
            cmd_parts = []
            if "innodb_buffer_pool_size" in cfg:
                cmd_parts.append(f"--innodb_buffer_pool_size={cfg['innodb_buffer_pool_size']}")
            if "max_connections" in cfg:
                cmd_parts.append(f"--max_connections={cfg['max_connections']}")
            command_line = ""
            if cmd_parts:
                command_line = f"\n    command: {' '.join(cmd_parts)}"
                
            return f"""  mysql:
    image: mysql:{v or "8.0"}
    environment:
      - MYSQL_ROOT_PASSWORD={pwd}{command_line}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
"""
        if n == "mongo":
            cmd_parts = []
            if "wiredTigerCacheSizeGB" in cfg:
                cmd_parts.append(f"--wiredTigerCacheSizeGB {cfg['wiredTigerCacheSizeGB']}")
            command_line = ""
            if cmd_parts:
                command_line = f"\n    command: {' '.join(cmd_parts)}"

            return f"""  mongo:
    image: mongo:{v or "6"}{command_line}
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
"""
        if n == "elasticsearch":
            heap = cfg.get("heap_size", "512m")
            return f"""  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:{v or "8.11.0"}
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms{heap} -Xmx{heap}
    ports:
      - "9200:9200"
      - "9300:9300"
    ulimits:
      memlock:
        soft: -1
        hard: -1
    volumes:
      - es_data:/usr/share/elasticsearch/data
"""
        if n == "rabbitmq":
            return f"""  rabbitmq:
    image: rabbitmq:{v or "3-management"}
    ports:
      - "5672:5672"
      - "15672:15672"
"""
        if n == "kafka":
            return f"""  zookeeper:
    image: bitnami/zookeeper:{v or "3.8.2"}
    environment:
      - ZOO_ENABLE_AUTH=no
    ports:
      - "2181:2181"
  kafka:
    image: bitnami/kafka:{v or "3.6.1"}
    environment:
      - KAFKA_CFG_ZOOKEEPER_CONNECT=zookeeper:2181
      - KAFKA_CFG_LISTENERS=PLAINTEXT://:9092
      - KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper
"""
        if n == "node_exporter":
            return f"""  node_exporter:
    image: prom/node-exporter:{v or "v1.7.0"}
    network_mode: host
"""
        if n == "mysqld_exporter":
            dsn = cfg.get("dsn", "root:rootpass@(localhost:3306)/")
            return f"""  mysqld_exporter:
    image: prom/mysqld-exporter:{v or "v0.15.0"}
    environment:
      - DATA_SOURCE_NAME={dsn}
    ports:
      - "9104:9104"
"""
        if n == "blackbox_exporter":
            return f"""  blackbox_exporter:
    image: prom/blackbox-exporter:{v or "v0.25.0"}
    ports:
      - "9115:9115"
"""
        if n == "prometheus":
            retention = cfg.get("retention", "15d")
            return f"""  prometheus:
    image: prom/prometheus:{v or "v2.51.0"}
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time={retention}"
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
"""
        if n == "grafana":
            admin_pwd = cfg.get("admin_password", "admin")
            return f"""  grafana:
    image: grafana/grafana:{v or "10.2.3"}
    environment:
      - GF_SECURITY_ADMIN_PASSWORD={admin_pwd}
    ports:
      - "3000:3000"
"""
        if n == "alertmanager":
            return f"""  alertmanager:
    image: prom/alertmanager:{v or "v0.27.0"}
    ports:
      - "9093:9093"
"""
        return ""

    def generate_compose(self, req: DeployRequest) -> str:
        parts = []
        parts.append("version: '3.8'")
        parts.append("services:")
        for svc in req.services:
            parts.append(self._compose_service(svc.model_dump()))
        parts.append("volumes:")
        parts.append("  mysql_data:")
        parts.append("  mongo_data:")
        parts.append("  es_data:")
        return "\n".join(parts)

    def generate_k8s(self, req: DeployRequest) -> List[str]:
        manifests = []
        for svc in req.services:
            name = svc.name
            image = {
                "nginx": f"nginx:{svc.version or '1.25'}",
                "mysql": f"mysql:{svc.version or '8.0'}",
                "mongo": f"mongo:{svc.version or '6'}",
                "elasticsearch": f"docker.elastic.co/elasticsearch/elasticsearch:{svc.version or '8.11.0'}",
                "rabbitmq": f"rabbitmq:{svc.version or '3-management'}",
                "kafka": f"bitnami/kafka:{svc.version or '3.6.1'}",
                "node_exporter": f"prom/node-exporter:{svc.version or 'v1.7.0'}",
                "mysqld_exporter": f"prom/mysqld-exporter:{svc.version or 'v0.15.0'}",
                "blackbox_exporter": f"prom/blackbox-exporter:{svc.version or 'v0.25.0'}",
                "prometheus": f"prom/prometheus:{svc.version or 'v2.51.0'}",
                "grafana": f"grafana/grafana:{svc.version or '10.2.3'}",
                "alertmanager": f"prom/alertmanager:{svc.version or 'v0.27.0'}",
            }[name]
            dep = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: {req.namespace}
spec:
  replicas: {req.replicas if req.cluster else 1}
  selector:
    matchLabels:
      app: {name}
  template:
    metadata:
      labels:
        app: {name}
    spec:
      containers:
      - name: {name}
        image: {image}
"""
            svc_yaml = f"""
apiVersion: v1
kind: Service
metadata:
  name: {name}
  namespace: {req.namespace}
spec:
  selector:
    app: {name}
  ports:
  - port: 80
    targetPort: 80
"""
            manifests.append(dep.strip())
            manifests.append(svc_yaml.strip())
        return manifests

    def _ssh_cmd(self, server: ServerConfig, cmd: str) -> List[str]:
        if server.auth_method == "key" and server.key_path:
            return ["ssh","-i",server.key_path,f"{server.user}@{server.host}",cmd]
        if server.auth_method == "password" and server.password:
            return ["sshpass","-p",server.password,"ssh",f"{server.user}@{server.host}",cmd]
        return ["ssh",f"{server.user}@{server.host}",cmd]

    def _scp_cmd(self, server: ServerConfig, local: str, remote: str) -> List[str]:
        if server.auth_method == "key" and server.key_path:
            return ["scp","-i",server.key_path,local,f"{server.user}@{server.host}:{remote}"]
        if server.auth_method == "password" and server.password:
            return ["sshpass","-p",server.password,"scp",local,f"{server.user}@{server.host}:{remote}"]
        return ["scp",local,f"{server.user}@{server.host}:{remote}"]

    def _generate_systemd_unit(self, name: str, cmd: str, user: str = "root", envs: Dict[str, str] = None) -> str:
        env_lines = ""
        if envs:
            for k, v in envs.items():
                env_lines += f"Environment=\"{k}={v}\"\n"
        
        return f"""[Unit]
Description={name} Service
After=network.target

[Service]
Type=simple
User={user}
{env_lines}ExecStart={cmd}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

    def _install_mysql_script(self, svc: Dict) -> List[str]:
        version = svc.get("version") or "8.0.35"
        # Extract major.minor for URL
        # URL pattern: https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.35-linux-glibc2.17-x86_64.tar.xz
        # Simplified: We assume 8.0 series for now or use a lookup if needed.
        # For simplicity in this demo, we use a fixed pattern for 8.0.
        if version == "8.0": version = "8.0.35"
        
        url = f"https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-{version}-linux-glibc2.17-x86_64.tar.xz"
        
        cmds = []
        cmds.append("# Install MySQL via Generic Binary")
        cmds.append(f"if ! id -u mysql > /dev/null 2>&1; then groupadd mysql && useradd -r -g mysql -s /bin/false mysql; fi")
        cmds.append("apt-get install -y libaio1 libncurses5 || yum install -y libaio ncurses-libs || true") # Minimal deps
        cmds.append(f"cd /usr/local")
        cmds.append(f"if [ ! -d mysql-{version}-linux-glibc2.17-x86_64 ]; then")
        cmds.append(f"  wget -c {url} -O mysql.tar.xz")
        cmds.append(f"  tar xf mysql.tar.xz")
        cmds.append(f"  ln -sf mysql-{version}-linux-glibc2.17-x86_64 mysql")
        cmds.append(f"fi")
        cmds.append("cd mysql")
        cmds.append("mkdir -p mysql-files")
        cmds.append("chown mysql:mysql mysql-files")
        cmds.append("chmod 750 mysql-files")
        cmds.append("mkdir -p /etc/mysql")
        
        # Config
        pwd = svc.get("config", {}).get("root_password", "rootpass")
        my_cnf = f"""[mysqld]
basedir=/usr/local/mysql
datadir=/usr/local/mysql/data
socket=/tmp/mysql.sock
user=mysql
port=3306
character-set-server=utf8mb4
"""
        if "innodb_buffer_pool_size" in svc.get("config", {}):
            my_cnf += f"innodb_buffer_pool_size={svc['config']['innodb_buffer_pool_size']}\n"
        if "max_connections" in svc.get("config", {}):
            my_cnf += f"max_connections={svc['config']['max_connections']}\n"

        cmds.append(f"cat > /etc/mysql/my.cnf <<EOF\n{my_cnf}EOF")
        
        # Initialize
        cmds.append("if [ ! -d data ]; then bin/mysqld --initialize-insecure --user=mysql --basedir=/usr/local/mysql --datadir=/usr/local/mysql/data; fi")
        cmds.append("bin/mysql_ssl_rsa_setup --datadir=/usr/local/mysql/data")
        
        # Systemd
        unit = self._generate_systemd_unit("mysql", "/usr/local/mysql/bin/mysqld --defaults-file=/etc/mysql/my.cnf", "mysql")
        cmds.append(f"cat > /etc/systemd/system/mysql.service <<EOF\n{unit}EOF")
        
        # Post install setup for root password (initialize-insecure creates root with no password)
        # We need to start service first
        cmds.append("systemctl daemon-reload")
        cmds.append("systemctl enable mysql")
        cmds.append("systemctl start mysql")
        
        # Wait for start
        cmds.append("sleep 5")
        # Set password
        cmds.append(f"/usr/local/mysql/bin/mysql -u root --skip-password -e \"ALTER USER 'root'@'localhost' IDENTIFIED BY '{pwd}'; FLUSH PRIVILEGES;\" || true")
        
        return cmds

    def _install_prometheus_app(self, svc: Dict, app_type: str) -> List[str]:
        # Generic installer for prometheus/grafana/exporters which are single binary or simple tarballs
        name = svc["name"]
        version = svc.get("version")
        if not version or version == "latest":
            if name == "prometheus": version = "2.51.0"
            elif name == "node_exporter": version = "1.7.0"
            elif name == "grafana": version = "10.2.3"
            elif name == "alertmanager": version = "0.27.0"
        
        # Strip 'v' prefix if present for url construction, some use v some don't
        v_num = version.lstrip('v')
        
        url = ""
        bin_path = ""
        user = name
        
        if name == "prometheus":
            url = f"https://github.com/prometheus/prometheus/releases/download/v{v_num}/prometheus-{v_num}.linux-amd64.tar.gz"
            folder = f"prometheus-{v_num}.linux-amd64"
            bin_path = f"/usr/local/{folder}/prometheus"
            args = "--config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/var/lib/prometheus"
            if "retention" in svc.get("config", {}):
                args += f" --storage.tsdb.retention.time={svc['config']['retention']}"
        elif name == "node_exporter":
            url = f"https://github.com/prometheus/node_exporter/releases/download/v{v_num}/node_exporter-{v_num}.linux-amd64.tar.gz"
            folder = f"node_exporter-{v_num}.linux-amd64"
            bin_path = f"/usr/local/{folder}/node_exporter"
            args = ""
        elif name == "alertmanager":
            url = f"https://github.com/prometheus/alertmanager/releases/download/v{v_num}/alertmanager-{v_num}.linux-amd64.tar.gz"
            folder = f"alertmanager-{v_num}.linux-amd64"
            bin_path = f"/usr/local/{folder}/alertmanager"
            args = "--config.file=/etc/alertmanager/alertmanager.yml"
        elif name == "grafana":
            url = f"https://dl.grafana.com/oss/release/grafana-{v_num}.linux-amd64.tar.gz"
            folder = f"grafana-{v_num}"
            bin_path = f"/usr/local/{folder}/bin/grafana-server"
            args = f"--homepath=/usr/local/{folder} --config=/usr/local/{folder}/conf/defaults.ini"
            # Grafana usually runs as grafana user, data in data/
        
        cmds = []
        cmds.append(f"# Install {name} {version}")
        cmds.append(f"if ! id -u {user} > /dev/null 2>&1; then useradd --no-create-home --shell /bin/false {user}; fi")
        cmds.append("cd /usr/local")
        cmds.append(f"wget -c {url} -O {name}.tar.gz")
        cmds.append(f"tar xf {name}.tar.gz")
        
        if name == "prometheus":
            cmds.append("mkdir -p /etc/prometheus /var/lib/prometheus")
            cmds.append(f"cp -r {folder}/consoles /etc/prometheus")
            cmds.append(f"cp -r {folder}/console_libraries /etc/prometheus")
            # Config
            prom_yml = "global:\n  scrape_interval: 15s\nscrape_configs:\n  - job_name: 'prometheus'\n    static_configs:\n      - targets: ['localhost:9090']"
            cmds.append(f"cat > /etc/prometheus/prometheus.yml <<EOF\n{prom_yml}EOF")
            cmds.append("chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus")
            
        elif name == "alertmanager":
             cmds.append("mkdir -p /etc/alertmanager")
             am_yml = "route:\n  receiver: 'web.hook'\nreceivers:\n- name: 'web.hook'\n  webhook_configs:\n  - url: 'http://127.0.0.1:5001/'"
             cmds.append(f"cat > /etc/alertmanager/alertmanager.yml <<EOF\n{am_yml}EOF")
             
        elif name == "grafana":
            # Grafana config tweak if needed
            if "admin_password" in svc.get("config", {}):
                # Grafana 10 reset admin password via cli
                pass 
                
        # Systemd
        envs = {}
        if name == "grafana":
             # Need to set working dir or homepath in unit? ExecStart handles it above
             pass
             
        unit = self._generate_systemd_unit(name, f"{bin_path} {args}", user, envs)
        cmds.append(f"cat > /etc/systemd/system/{name}.service <<EOF\n{unit}EOF")
        
        cmds.append("systemctl daemon-reload")
        cmds.append(f"systemctl enable {name}")
        cmds.append(f"systemctl restart {name}")
        
        if name == "grafana" and "admin_password" in svc.get("config", {}):
            # Wait for start
            cmds.append("sleep 5")
            pwd = svc["config"]["admin_password"]
            cmds.append(f"/usr/local/{folder}/bin/grafana-cli --homepath /usr/local/{folder} admin reset-admin-password {pwd}")
            
        return cmds

    def run(self, req: DeployRequest) -> DeployPlan:
        # Normalize versions and apply optimized defaults
        for svc in req.services:
            if not svc.version or str(svc.version).strip().lower() == "latest":
                svc.version = self._stable_version_for(svc.name)
            defaults = self._get_optimized_defaults(svc.name)
            for k, v in defaults.items():
                if k not in svc.config:
                    svc.config[k] = v

        plan = DeployPlan(id=req.task_id, req=req)
        try:
            if req.environment == "docker":
                compose_text = self.generate_compose(req)
                fp = artifact_path(req.task_id, "docker-compose.yml")
                with open(fp,"w",encoding="utf-8") as f:
                    f.write(compose_text)
                plan.artifacts.append(fp)

                # Generate config files for services
                service_names = [s.name for s in req.services]
                if "nginx" in service_names:
                    conf_path = artifact_path(req.task_id, "nginx.conf")
                    with open(conf_path, "w", encoding="utf-8") as f:
                        f.write("events { worker_connections 1024; }\nhttp { server { listen 80; location / { return 200 'OK'; } } }")
                    plan.artifacts.append(conf_path)
                
                if "prometheus" in service_names:
                    prom_path = artifact_path(req.task_id, "prometheus.yml")
                    with open(prom_path, "w", encoding="utf-8") as f:
                        f.write("global:\n  scrape_interval: 15s\nscrape_configs:\n  - job_name: 'prometheus'\n    static_configs:\n      - targets: ['localhost:9090']")
                    plan.artifacts.append(prom_path)

                for sid in req.server_ids:
                    sd = load_server(sid)
                    if not sd:
                        continue
                    server = ServerConfig(**sd)
                    cmds = []
                    cmds.append("mkdir -p ~/deploy && mkdir -p ~/deploy/{tid}".format(tid=req.task_id))
                    cmds.append("docker compose version || docker-compose -v || echo no_compose")
                    
                    # Transfer all artifacts
                    for art in plan.artifacts:
                        remote_path = f"/root/deploy/{req.task_id}/{os.path.basename(art)}"
                        plan.commands.append(" ".join(self._scp_cmd(server, art, remote_path)))
                        if req.execute:
                            subprocess.run(self._scp_cmd(server, art, remote_path), check=False)

                    cmds.append("cd ~/deploy/{tid} && docker compose up -d || docker-compose up -d".format(tid=req.task_id))
                    
                    for c in cmds:
                        plan.commands.append(" ".join(self._ssh_cmd(server, c)))
                    if req.execute:
                        for c in cmds:
                            subprocess.run(self._ssh_cmd(server, c), check=False)
            elif req.environment == "k8s":
                mfs = self.generate_k8s(req)
                idx = 0
                for text in mfs:
                    fp = artifact_path(req.task_id, f"{req.task_id}_{idx}.yaml")
                    with open(fp,"w",encoding="utf-8") as f:
                        f.write(text)
                    plan.artifacts.append(fp)
                    idx += 1
                for sid in req.server_ids:
                    sd = load_server(sid)
                    if not sd:
                        continue
                    server = ServerConfig(**sd)
                    for fp in plan.artifacts:
                        remote = f"/root/deploy/{os.path.basename(fp)}"
                        plan.commands.append(" ".join(self._scp_cmd(server, fp, remote)))
                        plan.commands.append(" ".join(self._ssh_cmd(server, f"kubectl apply -f {remote}")))
                        if req.execute:
                            subprocess.run(self._scp_cmd(server, fp, remote), check=False)
                            subprocess.run(self._ssh_cmd(server, f"kubectl apply -f {remote}"), check=False)
            elif req.environment == "helm":
                values_fp = artifact_path(req.task_id, "values.yaml")
                lines = []
                lines.append("global:")
                lines.append("  imagePullPolicy: IfNotPresent")
                for svc in req.services:
                    if svc.name == "prometheus":
                        lines.append("prometheus:")
                        lines.append("  enabled: true")
                        if svc.config.get("retention"):
                            lines.append(f"  retention: \"{svc.config['retention']}\"")
                    elif svc.name == "grafana":
                        lines.append("grafana:")
                        lines.append("  enabled: true")
                        if svc.config.get("admin_password"):
                            lines.append("  adminPassword: \"" + svc.config["admin_password"] + "\"")
                    elif svc.name == "alertmanager":
                        lines.append("alertmanager:")
                        lines.append("  enabled: true")
                with open(values_fp, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                plan.artifacts.append(values_fp)
                for sid in req.server_ids:
                    sd = load_server(sid)
                    if not sd:
                        continue
                    server = ServerConfig(**sd)
                    remote_values = f"/root/deploy/{req.task_id}_values.yaml"
                    plan.commands.append(" ".join(self._scp_cmd(server, values_fp, remote_values)))
                    helm_cmd = f"helm upgrade --install {req.task_id} prometheus-community/kube-prometheus-stack -f {remote_values} -n {req.namespace} --create-namespace"
                    plan.commands.append(" ".join(self._ssh_cmd(server, helm_cmd)))
                    if req.execute:
                        subprocess.run(self._scp_cmd(server, values_fp, remote_values), check=False)
                        subprocess.run(self._ssh_cmd(server, helm_cmd), check=False)
            else:
                fp = artifact_path(req.task_id, "install.sh")
                lines = []
                lines.append("set -e")
                lines.append("# Auto-generated install script using TGZ binaries")
                lines.append("mkdir -p /root/deploy")
                
                # Check for wget/curl/tar
                lines.append("if ! command -v wget >/dev/null 2>&1; then")
                lines.append("  if command -v yum >/dev/null 2>&1; then yum install -y wget; fi")
                lines.append("  if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y wget; fi")
                lines.append("fi")
                
                for svc in req.services:
                    if svc.name == "mysql":
                        lines.extend(self._install_mysql_script(svc.model_dump()))
                    elif svc.name in ["prometheus", "grafana", "node_exporter", "alertmanager"]:
                        lines.extend(self._install_prometheus_app(svc.model_dump(), svc.name))
                    elif svc.name == "nginx":
                        lines.append("echo 'Nginx tgz install not fully implemented yet, use package manager or docker'")
                    else:
                        lines.append(f"echo 'Service {svc.name} not supported for tgz install yet'")
                        
                with open(fp,"w",encoding="utf-8") as f:
                    f.write("\n".join(lines))
                plan.artifacts.append(fp)
                for sid in req.server_ids:
                    sd = load_server(sid)
                    if not sd:
                        continue
                    server = ServerConfig(**sd)
                    remote = f"/root/deploy/{req.task_id}_install.sh"
                    plan.commands.append(" ".join(self._scp_cmd(server, fp, remote)))
                    plan.commands.append(" ".join(self._ssh_cmd(server, f"bash {remote}")))
                    if req.execute:
                        subprocess.run(self._scp_cmd(server, fp, remote), check=False)
                        subprocess.run(self._ssh_cmd(server, f"bash {remote}"), check=False)
            plan.status = "completed"
        except Exception as e:
            plan.status = "error"
            plan.error = str(e)
        save_plan(plan)
        self._plans[plan.id] = plan
        return plan

    def get_plan(self, pid: str) -> Dict:
        return self._plans.get(pid).model_dump() if self._plans.get(pid) else {}

deploy_engine = DeployEngine()
