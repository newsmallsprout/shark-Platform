set -e
OS=unknown
if [ -f /etc/os-release ]; then . /etc/os-release; OS=$ID; fi
if command -v lsb_release >/dev/null 2>&1; then OS=$(lsb_release -is | tr '[:upper:]' '[:lower:]'); fi
PKG_INSTALL=""
if command -v apt-get >/dev/null 2>&1; then PKG_INSTALL="apt-get update && apt-get install -y"; fi
if command -v yum >/dev/null 2>&1; then PKG_INSTALL="yum install -y"; fi
mkdir -p /root/deploy
$PKG_INSTALL mysql-server || $PKG_INSTALL mariadb-server || true
systemctl enable mysql || systemctl enable mysqld || true
systemctl start mysql || systemctl start mysqld || service mysqld start || true
$PKG_INSTALL nginx || true
systemctl enable nginx || true
systemctl start nginx || service nginx start || true