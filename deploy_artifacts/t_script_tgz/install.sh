set -e
# Auto-generated install script using TGZ binaries
mkdir -p /root/deploy
if ! command -v wget >/dev/null 2>&1; then
  if command -v yum >/dev/null 2>&1; then yum install -y wget; fi
  if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y wget; fi
fi
# Install MySQL via Generic Binary
if ! id -u mysql > /dev/null 2>&1; then groupadd mysql && useradd -r -g mysql -s /bin/false mysql; fi
apt-get install -y libaio1 libncurses5 || yum install -y libaio ncurses-libs || true
cd /usr/local
if [ ! -d mysql-8.0.35-linux-glibc2.17-x86_64 ]; then
  wget -c https://dev.mysql.com/get/Downloads/MySQL-8.0/mysql-8.0.35-linux-glibc2.17-x86_64.tar.xz -O mysql.tar.xz
  tar xf mysql.tar.xz
  ln -sf mysql-8.0.35-linux-glibc2.17-x86_64 mysql
fi
cd mysql
mkdir -p mysql-files
chown mysql:mysql mysql-files
chmod 750 mysql-files
mkdir -p /etc/mysql
cat > /etc/mysql/my.cnf <<EOF
[mysqld]
basedir=/usr/local/mysql
datadir=/usr/local/mysql/data
socket=/tmp/mysql.sock
user=mysql
port=3306
character-set-server=utf8mb4
innodb_buffer_pool_size=1G
max_connections=500
EOF
if [ ! -d data ]; then bin/mysqld --initialize-insecure --user=mysql --basedir=/usr/local/mysql --datadir=/usr/local/mysql/data; fi
bin/mysql_ssl_rsa_setup --datadir=/usr/local/mysql/data
cat > /etc/systemd/system/mysql.service <<EOF
[Unit]
Description=mysql Service
After=network.target

[Service]
Type=simple
User=mysql
ExecStart=/usr/local/mysql/bin/mysqld --defaults-file=/etc/mysql/my.cnf
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable mysql
systemctl start mysql
sleep 5
/usr/local/mysql/bin/mysql -u root --skip-password -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'secure'; FLUSH PRIVILEGES;" || true
# Install prometheus v2.51.0
if ! id -u prometheus > /dev/null 2>&1; then useradd --no-create-home --shell /bin/false prometheus; fi
cd /usr/local
wget -c https://github.com/prometheus/prometheus/releases/download/v2.51.0/prometheus-2.51.0.linux-amd64.tar.gz -O prometheus.tar.gz
tar xf prometheus.tar.gz
mkdir -p /etc/prometheus /var/lib/prometheus
cp -r prometheus-2.51.0.linux-amd64/consoles /etc/prometheus
cp -r prometheus-2.51.0.linux-amd64/console_libraries /etc/prometheus
cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']EOF
chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
cat > /etc/systemd/system/prometheus.service <<EOF
[Unit]
Description=prometheus Service
After=network.target

[Service]
Type=simple
User=prometheus
ExecStart=/usr/local/prometheus-2.51.0.linux-amd64/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/var/lib/prometheus --storage.tsdb.retention.time=15d
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable prometheus
systemctl restart prometheus
# Install grafana 10.2.3
if ! id -u grafana > /dev/null 2>&1; then useradd --no-create-home --shell /bin/false grafana; fi
cd /usr/local
wget -c https://dl.grafana.com/oss/release/grafana-10.2.3.linux-amd64.tar.gz -O grafana.tar.gz
tar xf grafana.tar.gz
cat > /etc/systemd/system/grafana.service <<EOF
[Unit]
Description=grafana Service
After=network.target

[Service]
Type=simple
User=grafana
ExecStart=/usr/local/grafana-10.2.3/bin/grafana-server --homepath=/usr/local/grafana-10.2.3 --config=/usr/local/grafana-10.2.3/conf/defaults.ini
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable grafana
systemctl restart grafana
sleep 5
/usr/local/grafana-10.2.3/bin/grafana-cli --homepath /usr/local/grafana-10.2.3 admin reset-admin-password admin_new