#!/bin/bash
# PRD 内网巡检：日常 kubectl 串起来，输出稍作排版。只读。
# 拷到 ops-host → kauth-prd-admin <MFA码> → bash inspect-prd.sh
# 报告写在当前目录。INSPECT_OUT=/tmp/prd.md 可改路径。
# Prometheus（可选，失败不挡 kubectl）：默认 monitor/prometheus:9090
# 覆盖：PROM_NS PROM_SVC PROM_PORT（kube-prometheus-stack 用 prometheus-k8s）
#
# 与 Shark Platform「System Inspection」同一套清单：
#   PVC 用量优先 pvc_stats_*（prd 已部署的 pvc-stats-exporter）
#   已知常态：撮合引擎 Chronicle PVC、ES/JumpServer 内存、Traefik 日志
# 平台侧看 Web 报告；本脚本是 ops-host 上的 kubectl 只读版，不替代 Alertmanager。

set -u
set -o pipefail

K=(kubectl)
[ "${1:-}" != "" ] && K=(kubectl --kubeconfig "$1")
T=--request-timeout=20s

NOW=$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M')
STAMP=$(TZ=Asia/Shanghai date '+%Y%m%d-%H%M')
HOST=$(hostname 2>/dev/null || echo unknown)
OUT="${INSPECT_OUT:-$PWD/PRD巡检-${STAMP}.md}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

if ! "${K[@]}" $T cluster-info >/dev/null 2>&1; then
    echo "集群不可达。在 ops-host 先执行: kauth-prd-admin <MFA码>" >&2
    exit 1
fi
CTX=$("${K[@]}" $T config current-context 2>/dev/null || echo unknown)
echo "采集中，报告将写入: $OUT"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

save() {
    local name=$1; shift
    echo "kubectl $*" >"$TMP/$name.cmd"
    "${K[@]}" $T "$@" >"$TMP/$name.out" 2>"$TMP/$name.err"
    echo $? >"$TMP/$name.rc"
}
failed() { [ "$(cat "$TMP/$1.rc")" != "0" ]; }
body_n() { awk 'NR>1 && NF{n++} END{print n+0}' "$1"; }
dump() {
    echo "命令: \`$(cat "$TMP/$1.cmd")\`"
    echo; echo '```'
    cat "$TMP/$1.out"
    [ -s "$TMP/$1.err" ] && { echo "----- stderr -----"; cat "$TMP/$1.err"; }
    failed "$1" && echo "[失败 exit $(cat "$TMP/$1.rc")]"
    echo '```'
}

save nodes get nodes -o wide
save rofs get nodes -o jsonpath='{range .items[*]}{.metadata.name}={.status.conditions[?(@.type=="ReadonlyFilesystem")].status}{"\n"}{end}'
save pods get pods -A
save oom get events -A --field-selector reason=OOMKilling
save warn get events -A --field-selector type=Warning --sort-by=.lastTimestamp
save pvc get pvc -A
save pv get pv
save apps get applications -A
save deploy get deploy -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,SPEC:.spec.replicas,READY:.status.readyReplicas'
save logging get pods,pvc -n logging-system
save traefik get pods,pvc -n traefik-system

awk 'NR==1 || ($4!="Running" && $4!="Completed" && $4!="Succeeded")' "$TMP/pods.out" >"$TMP/abn.out"
awk 'NR==1 || $5+0>10' "$TMP/pods.out" >"$TMP/restart.out"
awk 'NR==1 || $0 !~ /Bound/' "$TMP/pvc.out" >"$TMP/pvc_bad.out"
awk 'NR==1 || $0 !~ /Synced/' "$TMP/apps.out" >"$TMP/apps_bad.out"
awk 'NR>1 && $2 !~ /^Ready/' "$TMP/nodes.out" >"$TMP/notready.out"
grep '=True' "$TMP/rofs.out" >"$TMP/rofs_true.out" || true
awk 'NR>1 && $3+0==0' "$TMP/deploy.out" >"$TMP/zero.out"
awk 'NR>1 && $3+0==1' "$TMP/deploy.out" >"$TMP/one.out"
tail -20 "$TMP/warn.out" >"$TMP/warn_tail.out"

# PVC / 节点盘用量：每节点拉一次 stats/summary，jq 拆 JSON，awk 排成表
echo "kubectl get --raw /api/v1/nodes/<node>/proxy/stats/summary" >"$TMP/usage.cmd"
mkdir -p "$TMP/summary"
: >"$TMP/usage.fail"
"${K[@]}" $T get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' >"$TMP/nodelist"
while IFS= read -r node; do
    [ -z "$node" ] && continue
    echo "  用量: $node"
    "${K[@]}" $T get --raw "/api/v1/nodes/${node}/proxy/stats/summary" \
        >"$TMP/summary/${node}.json" 2>/dev/null \
        || echo "$node" >>"$TMP/usage.fail"
done <"$TMP/nodelist"

fmt_rows() {
    awk -F'\t' '
    function fmt(n,  u, i) {
        n = n + 0
        split("B Ki Mi Gi Ti", u, " ")
        i = 1
        while (n >= 1024 && i < 5) { n = n / 1024; i++ }
        return sprintf("%.1f%s", n, u[i])
    }
    {
        p = ($3+0 > 0) ? int($2 / $3 * 100) : -1
        printf "%d\t%4s  %7s  %7s  %s  %s\n", p, (p<0 ? "-" : p"%"), fmt($2), fmt($3), $1, $4
    }' | sort -nr | cut -f2-
}

if command -v jq >/dev/null 2>&1; then
    : >"$TMP/pvc_raw"
    : >"$TMP/disk_raw"
    for f in "$TMP/summary"/*.json; do
        [ -f "$f" ] || continue
        jq -r '.node.nodeName as $n |
            (.pods[]? | .volume[]? | select(.pvcRef) |
             "\(.pvcRef.namespace)/\(.pvcRef.name)\t\(.usedBytes // 0)\t\(.capacityBytes // 0)\t\($n)")' "$f" >>"$TMP/pvc_raw" 2>/dev/null || true
        jq -r '.node.nodeName as $n |
            "\($n)\t\(.node.fs.usedBytes // 0)\t\(.node.fs.capacityBytes // 0)\troot",
            "\($n)\t\(.node.runtime.imageFs.usedBytes // 0)\t\(.node.runtime.imageFs.capacityBytes // 0)\timagefs"' "$f" >>"$TMP/disk_raw" 2>/dev/null || true
    done
    # 同一 PVC 多节点只留 used 更大的那条
    awk -F'\t' '{
        k=$1
        if (!(k in u) || $2+0 > u[k]) { u[k]=$2; c[k]=$3; n[k]=$4 }
    } END { for (k in u) print k "\t" u[k] "\t" c[k] "\t" n[k] }
    ' "$TMP/pvc_raw" >"$TMP/pvc_uniq"
    fmt_rows <"$TMP/pvc_uniq" >"$TMP/pvc_tbl" 2>/dev/null || :
    fmt_rows <"$TMP/disk_raw" >"$TMP/disk_tbl" 2>/dev/null || :
    {
        echo "PVC 用量（kubelet stats/summary，使用率从高到低）"
        echo "USE%     USED      CAP       PVC  NODE"
        if [ -s "$TMP/pvc_tbl" ]; then cat "$TMP/pvc_tbl"
        else echo "(stats/summary 里没有 PVC 用量)"; fi
        echo
        echo "节点磁盘（kubelet root / imagefs）"
        echo "USE%     USED      CAP       NODE  KIND"
        if [ -s "$TMP/disk_tbl" ]; then cat "$TMP/disk_tbl"
        else echo "(没有节点磁盘数据)"; fi
    } >"$TMP/usage.out"
    echo 0 >"$TMP/usage.rc"
else
    echo "用量在 stats/summary 的 JSON 里，这台机器没有 jq，没法排成表。装 jq 即可（yum/apt install jq）。" >"$TMP/usage.out"
    echo 1 >"$TMP/usage.rc"
fi
[ -s "$TMP/usage.fail" ] && echo 1 >"$TMP/usage.rc"

# Prometheus：告警快照 + 节点内存 + PVC 用量 + blackbox 失败（只读 API）
PROM_NS="${PROM_NS:-monitor}"
PROM_SVC="${PROM_SVC:-prometheus}"
PROM_PORT="${PROM_PORT:-9090}"
PROM_BASE="/api/v1/namespaces/${PROM_NS}/services/${PROM_SVC}:${PROM_PORT}/proxy"
echo "kubectl get --raw ${PROM_BASE}/api/v1/query?query=..." >"$TMP/prom.cmd"

prom_query() {
    local q="$1" dest="$2"
    local enc
    enc=$(jq -nr --arg q "$q" '$q|@uri')
    "${K[@]}" $T get --raw "${PROM_BASE}/api/v1/query?query=${enc}" >"$dest" 2>"${dest}.err"
}

# 两个 instant vector：used.json + cap.json → name \t used \t cap
# mode=avail_total 时 used.json 其实是 available，cap.json 是 total
prom_join() {
    jq -r -n --slurpfile used "$1" --slurpfile cap "$2" --arg mode "${3:-pair}" '
      def idx(j):
        [ ((j.data.result) // [])[] | {
            key: (
              if .metric.persistentvolumeclaim then
                "\(.metric.namespace // "-")/\(.metric.persistentvolumeclaim)"
              elif ((.metric.mountpoint // "") != "") then
                "\(.metric.instance // "-") \(.metric.mountpoint)"
              else (.metric.instance // "series")
              end
            ),
            value: ((.value[1] // "0") | tonumber)
          }
        ] | from_entries;
      ($used[0] // {}) as $uj | ($cap[0] // {}) as $cj |
      if $mode == "avail_total" then
        (idx($cj) as $t | idx($uj) as $a |
          $t | to_entries[] |
          .key as $k | .value as $tot |
          (($tot - ($a[$k] // 0)) as $raw | if $raw < 0 then 0 else $raw end) as $u |
          "\($k)\t\($u)\t\($tot)\t")
      else
        (idx($uj) as $u | idx($cj) as $c |
          ($u | keys[]) as $k |
          "\($k)\t\($u[$k] // 0)\t\($c[$k] // 0)\t")
      end
    ' 2>/dev/null
}

prom_table() {
    jq -r '
      if .status != "success" then "(prometheus 返回失败)"
      elif (.data.result|length) == 0 then "(无数据)"
      else
        .data.result[] |
        (
          (.metric.alertname // .metric.instance // .metric.job // "series")
          + (if ((.metric.namespace // "") != "") then " ns=" + .metric.namespace else "" end)
          + (if ((.metric.severity // "") != "") then " sev=" + .metric.severity else "" end)
          + (if .metric.alertname and ((.metric.instance // "") != "") then " " + .metric.instance else "" end)
        )
      end
    ' "$1" 2>/dev/null
}

if command -v jq >/dev/null 2>&1; then
    prom_query 'ALERTS{alertstate="firing"}' "$TMP/prom_alerts.json"; echo $? >"$TMP/prom_alerts.rc"
    prom_query 'node_memory_MemAvailable_bytes' "$TMP/prom_mem_avail.json"; echo $? >"$TMP/prom_mem.rc"
    prom_query 'node_memory_MemTotal_bytes' "$TMP/prom_mem_total.json"
    prom_query 'pvc_stats_used_bytes' "$TMP/prom_pvc_used.json"; echo $? >"$TMP/prom_pvc.rc"
    prom_query 'pvc_stats_capacity_bytes' "$TMP/prom_pvc_cap.json"
    prom_query 'node_filesystem_avail_bytes{fstype=~"ext4|xfs",mountpoint="/"}' "$TMP/prom_fs_avail.json"
    prom_query 'node_filesystem_size_bytes{fstype=~"ext4|xfs",mountpoint="/"}' "$TMP/prom_fs_size.json"
    prom_query 'probe_success == 0' "$TMP/prom_probe.json"

    if [ "$(cat "$TMP/prom_alerts.rc")" != "0" ]; then
        echo 1 >"$TMP/prom.rc"
        echo "Prometheus 代理拉不到（默认 ${PROM_NS}/${PROM_SVC}:${PROM_PORT}）。kubectl 段仍有效。" >"$TMP/prom.out"
    else
        echo 0 >"$TMP/prom.rc"
        prom_join "$TMP/prom_mem_avail.json" "$TMP/prom_mem_total.json" avail_total >"$TMP/prom_mem_raw"
        prom_join "$TMP/prom_pvc_used.json" "$TMP/prom_pvc_cap.json" pair >"$TMP/prom_pvc_raw"
        prom_join "$TMP/prom_fs_avail.json" "$TMP/prom_fs_size.json" avail_total >"$TMP/prom_fs_raw"
        {
            echo "# firing 告警（快照，不替代 Alertmanager）"
            prom_table "$TMP/prom_alerts.json" | sed 's/^/  /'
            echo
            echo "# 节点内存（MemTotal - MemAvailable）"
            echo "USE%     USED      CAP       INSTANCE"
            if [ -s "$TMP/prom_mem_raw" ]; then fmt_rows <"$TMP/prom_mem_raw" | head -15
            else echo "(无数据)"; fi
            echo
            echo "# 节点根盘 /（node-exporter）"
            echo "USE%     USED      CAP       INSTANCE  MOUNT"
            if [ -s "$TMP/prom_fs_raw" ]; then fmt_rows <"$TMP/prom_fs_raw" | head -15
            else echo "(无数据，看上面 kubelet 磁盘表)"; fi
            echo
            echo "# PVC 用量（pvc_stats_* used/capacity）"
            echo "USE%     USED      CAP       PVC"
            if [ -s "$TMP/prom_pvc_raw" ]; then fmt_rows <"$TMP/prom_pvc_raw" | head -15
            else echo "(无 pvc_stats 指标，看 kubelet 表)"; fi
            echo
            echo "# blackbox 失败（probe_success==0）"
            prom_table "$TMP/prom_probe.json" | sed 's/^/  /'
        } >"$TMP/prom.out"
    fi
else
    echo 1 >"$TMP/prom.rc"
    echo "没有 jq，跳过 Prometheus 段。" >"$TMP/prom.out"
fi
N_FIRING=0
if [ -f "$TMP/prom_alerts.json" ] && command -v jq >/dev/null 2>&1; then
    N_FIRING=$(jq -r '(.data.result // []) | length' "$TMP/prom_alerts.json" 2>/dev/null || echo 0)
fi

N_NODE=$(body_n "$TMP/nodes.out")
N_NOTREADY=$(awk 'NF{n++} END{print n+0}' "$TMP/notready.out")
N_ROFS=$(awk 'NF{n++} END{print n+0}' "$TMP/rofs_true.out")
N_ABN=$(body_n "$TMP/abn.out")
N_OOM=$(body_n "$TMP/oom.out")
N_RESTART=$(body_n "$TMP/restart.out")
N_PVC=$(body_n "$TMP/pvc_bad.out")
N_APP=$(body_n "$TMP/apps_bad.out")
N_ZERO=$(awk 'NF{n++} END{print n+0}' "$TMP/zero.out")
N_ONE=$(awk 'NF{n++} END{print n+0}' "$TMP/one.out")

PVC_TOP=$(head -1 "$TMP/pvc_tbl" 2>/dev/null || true)
DISK_TOP=$(head -1 "$TMP/disk_tbl" 2>/dev/null || true)
MEM_TOP=""
PROM_PVC_TOP=""
[ -s "$TMP/prom_mem_raw" ] && MEM_TOP=$(fmt_rows <"$TMP/prom_mem_raw" | head -1)
[ -s "$TMP/prom_pvc_raw" ] && PROM_PVC_TOP=$(fmt_rows <"$TMP/prom_pvc_raw" | head -1)
[ -z "${PVC_TOP:-}" ] && PVC_TOP="无"
[ -z "${DISK_TOP:-}" ] && DISK_TOP="无"
[ -z "${MEM_TOP:-}" ] && MEM_TOP="无"
[ -z "${PROM_PVC_TOP:-}" ] && PROM_PVC_TOP="无"

cell() { if failed "$1"; then echo "采集失败"; else echo "$2"; fi; }

FINDINGS=()
failed nodes && FINDINGS+=("节点列表采集失败")
failed pods && FINDINGS+=("Pod 列表采集失败")
failed pvc && FINDINGS+=("PVC 列表采集失败")
failed apps && FINDINGS+=("ArgoCD Application 采集失败")
failed deploy && FINDINGS+=("Deployment 列表采集失败")
failed usage && FINDINGS+=("用量采集失败（部分节点 stats/summary 拉不到也算）")
! failed nodes && [ "$N_NOTREADY" -gt 0 ] && FINDINGS+=("NotReady 节点 ${N_NOTREADY} 个")
! failed rofs && [ "$N_ROFS" -gt 0 ] && FINDINGS+=("ReadonlyFilesystem=True ${N_ROFS} 个")
! failed pods && [ "$N_ABN" -gt 0 ] && FINDINGS+=("异常 Pod ${N_ABN} 个")
! failed oom && [ "$N_OOM" -gt 0 ] && FINDINGS+=("OOMKilling ${N_OOM} 条")
! failed pods && [ "$N_RESTART" -gt 0 ] && FINDINGS+=("重启>10 的 Pod ${N_RESTART} 个")
! failed pvc && [ "$N_PVC" -gt 0 ] && FINDINGS+=("未 Bound PVC ${N_PVC} 个")
! failed apps && [ "$N_APP" -gt 0 ] && FINDINGS+=("未 Synced Application ${N_APP} 个")
! failed deploy && [ "$N_ZERO" -gt 0 ] && FINDINGS+=("零副本 Deployment ${N_ZERO} 个")

if [ ${#FINDINGS[@]} -eq 0 ]; then
    VERDICT="本次 kubectl 只读项未见明显异常（中间件未查）"
else
    VERDICT="需关注（${#FINDINGS[@]} 项）"
fi

{
echo "# PRD 集群巡检报告"
echo
echo "> ${NOW} ｜ \`${HOST}\` ｜ \`${CTX}\` ｜ 只读"
echo
echo "## 总体评估"
echo
echo "**${VERDICT}**"
echo
echo "| 检查项 | 结果 |"
echo "|--------|------|"
echo "| 节点 | $(cell nodes "${N_NOTREADY} NotReady / ${N_NODE} 总") |"
echo "| ReadonlyFilesystem | $(cell rofs "${N_ROFS} True") |"
echo "| 异常 Pod | $(cell pods "$N_ABN") |"
echo "| OOM / 重启>10 | $(cell oom "$N_OOM") / $(cell pods "$N_RESTART") |"
echo "| PVC 未绑定 | $(cell pvc "$N_PVC") |"
echo "| PVC 用量最高 | $(cell usage "${PVC_TOP}") |"
echo "| PVC 用量(Prom) | $(cell prom "${PROM_PVC_TOP}") |"
echo "| 节点磁盘最高 | $(cell usage "${DISK_TOP}") |"
echo "| 节点内存最高 | $(cell prom "${MEM_TOP}") |"
echo "| Prometheus firing | $(cell prom "${N_FIRING} 条") |"
echo "| ArgoCD 未同步 | $(cell apps "$N_APP") |"
echo "| 零副本 / 单副本 | $(cell deploy "$N_ZERO") / ${N_ONE} |"
echo
echo "## 发现问题"
echo
if [ ${#FINDINGS[@]} -eq 0 ]; then
    echo "无。"
else
    i=1
    for x in "${FINDINGS[@]}"; do echo "${i}. ${x}"; i=$((i+1)); done
fi
echo
echo "## 一、节点"
echo
if failed nodes; then echo "- 采集失败"
elif [ "$N_NOTREADY" -eq 0 ]; then echo "- 全部 Ready"
else echo '```'; cat "$TMP/notready.out"; echo '```'; fi
echo
if failed rofs; then echo "- ReadonlyFilesystem 采集失败"
elif [ "$N_ROFS" -eq 0 ]; then echo "- 无 ReadonlyFilesystem=True"
else echo '```'; cat "$TMP/rofs_true.out"; echo '```'; fi
echo
dump nodes
echo
echo "## 二、异常 Pod"
echo
if failed pods; then echo "- 采集失败"
elif [ "$N_ABN" -eq 0 ]; then echo "- 无"
else echo '```'; cat "$TMP/abn.out"; echo '```'; fi
echo
echo "## 三、稳定性"
echo
echo "- OOMKilling: ${N_OOM}"
if [ "$N_RESTART" -gt 0 ]; then echo '```'; cat "$TMP/restart.out"; echo '```'; else echo "- 无重启>10"; fi
echo
echo "最近 Warning（最后 20 行）："
echo '```'
cat "$TMP/warn_tail.out"
echo '```'
echo
echo "## 四、存储"
echo
if failed pvc; then echo "- PVC 列表采集失败"
elif [ "$N_PVC" -eq 0 ]; then echo "- PVC 均为 Bound"
else echo '```'; cat "$TMP/pvc_bad.out"; echo '```'; fi
echo
echo "命令: \`$(cat "$TMP/usage.cmd")\`"
if [ -s "$TMP/usage.fail" ]; then echo; echo "节点失败: $(tr '\n' ' ' <"$TMP/usage.fail")"; fi
echo
echo '```'
cat "$TMP/usage.out"
echo '```'
echo
echo "### logging-system / traefik-system（日志相关资源，目录 du 见段末命令）"
echo
dump logging
echo
dump traefik
echo
echo '```'
echo "# Traefik 日志存量（镜像若无 du/sh 会失败，属正常）"
echo "kubectl -n traefik-system exec ds/traefik -- du -sh /data/traefik/logs"
echo '```'
echo
dump pvc
echo
dump pv
echo
echo "## 五、Prometheus（水位 / firing / 探活；告警通道仍以 Alertmanager 为准）"
echo
echo "命令: \`$(cat "$TMP/prom.cmd")\`"
echo
echo '```'
cat "$TMP/prom.out"
failed prom && echo "[失败 exit $(cat "$TMP/prom.rc")]"
echo '```'
echo
echo "## 六、ArgoCD"
echo
if failed apps; then echo "- 采集失败（无 CRD 也会失败）"
elif [ "$N_APP" -eq 0 ]; then echo "- 无未 Synced 行"
else echo '```'; cat "$TMP/apps_bad.out"; echo '```'; fi
echo
dump apps
echo
echo "## 七、副本"
echo
if failed deploy; then echo "- 采集失败"
else
    echo "- spec.replicas=0：${N_ZERO}"
    [ "$N_ZERO" -gt 0 ] && { echo '```'; cat "$TMP/zero.out"; echo '```'; }
    echo "- spec.replicas=1：${N_ONE}（故意单副本不要当故障）"
    [ "$N_ONE" -gt 0 ] && { echo '```'; cat "$TMP/one.out"; echo '```'; }
fi
echo
echo "## 八、中间件（未跑）"
echo
echo '```'
echo "aws rds describe-db-instances --query 'DBInstances[].{id:DBInstanceIdentifier,st:DBInstanceStatus}'"
echo "aws elasticache describe-cache-clusters --query 'CacheClusters[].{id:CacheClusterId,st:CacheClusterStatus}'"
echo "aws mq describe-brokers --query 'BrokerSummaries[].{id:BrokerName,st:BrokerState}'"
echo "curl -sk 'https://es.etz.com:9200/_cluster/health?pretty'"
echo "# Mongo：跳板到 mongo1/2/3 后 rs.status()"
echo '```'
echo
echo "## 九、已知常态"
echo
echo "- JumpServer 内存 80%+；ES 内存约 82%"
echo "- exchange-match-engine-major-pvc 用量高（Chronicle Queue）"
echo "- Traefik accesslog 无轮转，看 /data/traefik/logs"
echo
} >"$OUT"

echo "报告已写入: $OUT"
