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
innodb_buffer_pool_size=512M
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
/usr/local/mysql/bin/mysql -u root --skip-password -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'rootpass'; FLUSH PRIVILEGES;" || true