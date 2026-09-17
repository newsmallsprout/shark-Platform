<template>
  <div class="inspection-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">System Inspection</h2>
        <p class="page-subtitle">集群检查清单 + PVC/业务服务 + 资源告警；异常可通过「系统工单」交由人工处置。</p>
      </div>
      <div class="header-actions">
        <el-button @click="router.push('/system/tickets')" v-if="canViewInspection">系统工单</el-button>
        <el-button @click="showLogs" :icon="Document">Inspection Logs</el-button>
        <el-button @click="configVisible = true" :icon="Setting" v-if="canManage">巡检配置</el-button>
        <el-button type="primary" size="large" @click="handleRun" :loading="loading" class="action-btn shadow-btn" v-if="canManage">
          <el-icon><Search /></el-icon> Run New Inspection
        </el-button>
      </div>
    </div>
    
    <el-card shadow="never" class="table-card">
      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="report_id" label="Report Timestamp" width="220">
          <template #default="{ row }">
            <div class="report-id-cell">
              <el-icon class="report-icon"><Calendar /></el-icon>
              <span>{{ formatReportTime(row) }}</span>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Health Status" width="160">
          <template #default="{ row }">
            <div class="score-wrapper">
              <template v-if="hasScore(row.score)">
                <el-progress 
                  type="circle" 
                  :percentage="row.score" 
                  :width="40" 
                  :stroke-width="4"
                  :status="getProgressStatus(row.score)"
                />
                <el-tag :type="getScoreType(row.score)" size="small" effect="plain" class="score-tag">
                  {{ row.score }}
                </el-tag>
              </template>
              <template v-else>
                <el-icon class="status-icon-placeholder"><CircleCheck /></el-icon>
                <el-tag type="info" size="small" effect="plain" class="score-tag">未覆盖</el-tag>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="summary" label="Analysis Summary">
          <template #default="{ row }">
            <span class="summary-text">{{ row.summary || 'Awaiting full report analysis...' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" plain size="small" @click="viewReport(row)">
              View Details
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Report Detail Dialog -->
    <el-dialog 
      v-model="dialogVisible" 
      title="Inspection Report Analysis" 
      width="1120px"
      class="report-dialog"
    >
      <div v-if="currentReport" class="report-content">
        <div class="report-meta">
          <div class="meta-item">
            <span class="label">TIMESTAMP</span>
            <span class="value">{{ formatReportTime(currentReport) }}</span>
          </div>
          <div class="meta-item">
            <span class="label">HEALTH SCORE</span>
            <div class="score-display">
              <span :class="['score-value', getScoreType(currentReport.score)]">{{ hasScore(currentReport.score) ? currentReport.score : '—' }}</span>
              <span class="score-total">/100</span>
            </div>
            <div v-if="scoreReasons.length" class="score-reasons">{{ scoreReasons.join('；') }}</div>
          </div>
          <div class="meta-item">
            <span class="label">SERVERS</span>
            <span class="value">{{ currentReport.fleet_summary?.server_count ?? '-' }}</span>
          </div>
          <div class="meta-item">
            <span class="label">FIRING ALERTS</span>
            <span class="value">{{ currentReport.alerts_summary?.firing_total ?? '-' }}</span>
          </div>
          <div class="meta-item">
            <span class="label">VERDICT</span>
            <span class="value">{{ currentReport.verdict || '-' }}</span>
          </div>
        </div>

        <el-divider />

        <div class="analysis-section" v-if="(currentReport.checklist && currentReport.checklist.length) || (currentReport.findings && currentReport.findings.length)">
          <div class="section-header">
            <el-icon><List /></el-icon>
            <span>检查清单</span>
          </div>
          <el-alert
            v-if="currentReport.verdict"
            :title="currentReport.verdict"
            :type="verdictAlertType"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />
          <div v-if="currentReport.findings && currentReport.findings.length" class="findings-list">
            <div class="chart-title">发现问题</div>
            <ol>
              <li v-for="(item, idx) in currentReport.findings" :key="idx">{{ item }}</li>
            </ol>
          </div>
          <el-table v-if="checklistCovered.length" :data="checklistCovered" size="small" row-key="_key" style="width: 100%">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div v-if="!checkItems(row).length" class="form-tip">无明细</div>
                <ul v-else class="check-detail-list">
                  <li v-for="(item, idx) in checkItems(row)" :key="item.key || idx" class="check-detail-row">
                    <span>{{ item.label }}</span>
                    <el-button
                      v-if="canManage && row.level !== 'ok' && row.level !== 'skip' && item.key"
                      link
                      type="primary"
                      size="small"
                      @click="ignoreItem(item.key, item.label, row.id)"
                    >忽略</el-button>
                  </li>
                </ul>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="检查项" min-width="160" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="checkTagType(row.level)" size="small" effect="plain">{{ checkLevelLabel(row.level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="result" label="结果" min-width="240" />
            <el-table-column prop="source" label="数据源" width="160" />
            <el-table-column v-if="canManage" label="" width="72">
              <template #default="{ row }">
                <el-button
                  v-if="row.level === 'warning' || row.level === 'critical'"
                  link
                  type="primary"
                  size="small"
                  @click="ignoreItem(`check:${row.id}`, row.name, row.id)"
                >忽略</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.servers && currentReport.servers.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.nodes = !auxOpen.nodes">
            <el-icon><Monitor /></el-icon>
            <span>资源使用（{{ filteredServers.length }} / {{ currentReport.servers.length }} 台{{ nodeHotCount ? `，偏高 ${nodeHotCount}` : '' }}）</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.nodes" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <template v-if="auxOpen.nodes">
            <p class="section-hint">
              均 CPU {{ fmtPct(currentReport.fleet_summary?.avg_cpu_pct) }}%
              · 均内存 {{ fmtPct(currentReport.fleet_summary?.avg_mem_pct) }}%
              · 均磁盘 {{ fmtPct(currentReport.fleet_summary?.avg_disk_pct) }}%。
              机器名来自主机 hostname 或 kube 节点名，IP 单独一列。
              磁盘/内存旁的 Δ24h 是比昨天占比高了多少个百分点；7 日均线在下方趋势图。细曲线仍看 Grafana。
            </p>
            <div class="node-filter-row">
              <el-input
                v-model="nodeQuery"
                clearable
                size="small"
                placeholder="搜 IP / 机器名 / 角色 / nodegroup / instance-id"
                style="max-width: 320px"
              />
              <el-radio-group v-model="nodeKindFilter" size="small">
                <el-radio-button label="all">全部</el-radio-button>
                <el-radio-button label="k8s">K8s / EKS</el-radio-button>
                <el-radio-button label="host">独立主机</el-radio-button>
                <el-radio-button label="hot">偏高</el-radio-button>
              </el-radio-group>
            </div>
            <el-table :data="filteredServers" size="small" style="width: 100%" max-height="440">
              <el-table-column label="角色" min-width="120">
                <template #default="{ row }">{{ row.role || nodeKindLabel(row) }}</template>
              </el-table-column>
              <el-table-column label="机器名" min-width="160">
                <template #default="{ row }">{{ machineName(row) }}</template>
              </el-table-column>
              <el-table-column label="IP" width="130">
                <template #default="{ row }">{{ displayIp(row) }}</template>
              </el-table-column>
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain">{{ nodeKindLabel(row) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="checkTagType(row.level || 'ok')" size="small" effect="plain">{{ checkLevelLabel(row.level || 'ok') }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="CPU" min-width="170">
                <template #default="{ row }">
                  <div class="resource-cell">
                    <el-progress :percentage="clipPct(row.cpu_pct)" :stroke-width="8" :show-text="false" :color="pctColor(row.cpu_pct, 85, 95)" />
                    <span>{{ cpuResourceText(row) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="内存" min-width="190">
                <template #default="{ row }">
                  <div class="resource-cell">
                    <el-progress :percentage="clipPct(row.mem_pct)" :stroke-width="8" :show-text="false" :color="pctColor(row.mem_pct, 85, 95)" />
                    <span>{{ bytesResourceText(row.mem_used_bytes, row.mem_total_bytes, row.mem_pct) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="磁盘 /" min-width="190">
                <template #default="{ row }">
                  <div class="resource-cell">
                    <el-progress :percentage="clipPct(row.disk_pct)" :stroke-width="8" :show-text="false" :color="pctColor(row.disk_pct, 90, 95)" />
                    <span>{{ bytesResourceText(row.disk_used_bytes, row.disk_total_bytes, row.disk_pct) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="内存 Δ24h" width="100">
                <template #default="{ row }">
                  <span :class="deltaClass(row.mem_delta_24h)">{{ fmtDelta(row.mem_delta_24h) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="磁盘 Δ24h" width="100">
                <template #default="{ row }">
                  <span :class="deltaClass(row.disk_delta_24h)">{{ fmtDelta(row.disk_delta_24h) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="Load1" width="70">
                <template #default="{ row }">{{ row.load1 == null ? '-' : row.load1 }}</template>
              </el-table-column>
            </el-table>
          </template>
        </div>

        <div class="analysis-section" v-if="workloadNsGroups.length">
          <div class="section-header">
            <el-icon><Monitor /></el-icon>
            <span>工作负载（{{ workloadRows.length }} 个 / {{ workloadNsGroups.length }} 个 Namespace，默认不含 kube-system）</span>
          </div>
          <p class="section-hint">按 Namespace 折叠。先展开 ns，再展开负载看 Pod，避免一次铺开全部明细。</p>
          <el-table :data="workloadNsGroups" size="small" style="width: 100%" max-height="520" row-key="key">
            <el-table-column type="expand">
              <template #default="{ row }">
                <el-table :data="row.workloads" size="small" style="width: 100%" row-key="key">
                  <el-table-column type="expand">
                    <template #default="{ row: wl }">
                      <div v-if="!(wl.pods && wl.pods.length)" class="form-tip">无 Pod 明细</div>
                      <el-table v-else :data="wl.pods" size="small" style="width: 100%">
                        <el-table-column prop="pod" label="Pod" min-width="200" />
                        <el-table-column prop="phase" label="相位" width="100" />
                        <el-table-column label="Ready" width="80">
                          <template #default="{ row: pod }">{{ pod.ready == null ? '-' : (pod.ready ? '是' : '否') }}</template>
                        </el-table-column>
                        <el-table-column prop="pod_ip" label="Pod IP" width="130">
                          <template #default="{ row: pod }">{{ pod.pod_ip || '-' }}</template>
                        </el-table-column>
                        <el-table-column prop="node" label="节点" min-width="140">
                          <template #default="{ row: pod }">{{ pod.node || '-' }}</template>
                        </el-table-column>
                        <el-table-column prop="host_ip" label="节点 IP" width="130">
                          <template #default="{ row: pod }">{{ pod.host_ip || '-' }}</template>
                        </el-table-column>
                        <el-table-column prop="restarts" label="重启" width="70" />
                        <el-table-column prop="waiting" label="等待原因" min-width="120">
                          <template #default="{ row: pod }">{{ pod.waiting || '-' }}</template>
                        </el-table-column>
                      </el-table>
                    </template>
                  </el-table-column>
                  <el-table-column prop="service" label="服务" min-width="120" />
                  <el-table-column prop="kind" label="类型" width="110" />
                  <el-table-column label="对象" min-width="200">
                    <template #default="{ row: wl }">{{ wl.name }}</template>
                  </el-table-column>
                  <el-table-column label="Ready" width="100">
                    <template #default="{ row: wl }">
                      <el-tag :type="checkTagType(wl.level)" size="small" effect="plain">{{ wl.ready }}/{{ wl.desired }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="namespace" label="Namespace" min-width="220" />
            <el-table-column label="负载数" width="90">
              <template #default="{ row }">{{ row.count }}</template>
            </el-table-column>
            <el-table-column label="Ready" width="120">
              <template #default="{ row }">
                <el-tag :type="checkTagType(row.level)" size="small" effect="plain">{{ row.ready }}/{{ row.desired }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="checkTagType(row.level)" size="small" effect="plain">{{ checkLevelLabel(row.level) }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="analysis-section" v-if="esClusters.length">
          <div class="section-header">
            <el-icon><Box /></el-icon>
            <span>Elasticsearch（elasticsearch-exporter）</span>
          </div>
          <el-table :data="esClusters" size="small" style="width: 100%">
            <el-table-column prop="cluster" label="集群" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="esStatusType(row.status)" size="small" effect="plain">{{ row.status || '-' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="nodes" label="节点" width="80" />
            <el-table-column prop="data_nodes" label="数据节点" width="90" />
            <el-table-column prop="unassigned_shards" label="未分配分片" width="110" />
            <el-table-column prop="active_shards" label="活跃分片" width="90" />
          </el-table>
          <el-table
            v-if="esHeapNodes.length"
            :data="esHeapNodes"
            size="small"
            style="width: 100%; margin-top: 12px"
          >
            <el-table-column prop="cluster" label="集群" min-width="120" />
            <el-table-column prop="node" label="节点" min-width="160" />
            <el-table-column label="堆使用率" width="100">
              <template #default="{ row }">{{ row.heap_pct < 0 ? '-' : row.heap_pct + '%' }}</template>
            </el-table-column>
            <el-table-column label="已用" width="110">
              <template #default="{ row }">{{ formatBytes(row.used_bytes) }}</template>
            </el-table-column>
            <el-table-column label="堆上限" width="110">
              <template #default="{ row }">{{ formatBytes(row.max_bytes) }}</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="analysis-section" v-if="middlewareRows.length">
          <div class="section-header">
            <el-icon><Box /></el-icon>
            <span>中间件（按 Prometheus 指标名扫描）</span>
          </div>
          <p v-if="discoveredMetricCount" class="section-hint">
            本次扫到 {{ discoveredMetricCount }} 个指标名。中间件内存/磁盘只用来自该 exporter 的 used/max（或水位）；没有就不填，数据目录仍看 PVC / 节点盘。
          </p>
          <el-table :data="middlewareRows" size="small" style="width: 100%">
            <el-table-column prop="name" label="组件" min-width="160" />
            <el-table-column prop="source" label="数据源" width="160" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="checkTagType(row.level)" size="small" effect="plain">{{ checkLevelLabel(row.level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="result" label="结果" min-width="220" />
            <el-table-column label="内存" width="140">
              <template #default="{ row }">{{ row.mem_text || (row.mem_pct != null ? row.mem_pct + '%' : '-') }}</template>
            </el-table-column>
            <el-table-column label="存储" width="160">
              <template #default="{ row }">{{ row.disk_text || (row.disk_pct != null ? row.disk_pct + '%' : '-') }}</template>
            </el-table-column>
            <el-table-column label="实例" min-width="200">
              <template #default="{ row }">{{ (row.instances && row.instances.length) ? row.instances.join(', ') : '-' }}</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.pvc_usage && currentReport.pvc_usage.length">
          <div class="section-header">
            <el-icon><Coin /></el-icon>
            <span>PVC 用量（全部 {{ currentReport.pvc_usage.length }} 块）</span>
          </div>
          <el-table :data="currentReport.pvc_usage" size="small" style="width: 100%" max-height="420">
            <el-table-column prop="namespace" label="Namespace" min-width="130" />
            <el-table-column prop="pvc" label="PVC" min-width="200" />
            <el-table-column prop="service" label="别名" min-width="110" />
            <el-table-column label="使用率" width="90">
              <template #default="{ row }">{{ row.pct < 0 ? '-' : row.pct + '%' }}</template>
            </el-table-column>
            <el-table-column label="Δ24h" width="90">
              <template #default="{ row }">
                <span :class="deltaClass(row.delta_24h)">{{ fmtDelta(row.delta_24h) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="已用" width="100">
              <template #default="{ row }">{{ formatBytes(row.used_bytes) }}</template>
            </el-table-column>
            <el-table-column label="容量" width="100">
              <template #default="{ row }">{{ formatBytes(row.capacity_bytes) }}</template>
            </el-table-column>
            <el-table-column prop="baseline" label="备注" min-width="160" />
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.known_normals && currentReport.known_normals.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.normals = !auxOpen.normals">
            <el-icon><InfoFilled /></el-icon>
            <span>已知常态（{{ currentReport.known_normals.length }}）</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.normals" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <ul class="known-normals" v-show="auxOpen.normals">
            <li v-for="(item, idx) in currentReport.known_normals" :key="idx">{{ item }}</li>
          </ul>
        </div>

        <div class="analysis-section" v-if="decommissionedRows.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.decommissioned = !auxOpen.decommissioned">
            <el-icon><InfoFilled /></el-icon>
            <span>已下线残留（{{ decommissionedRows.length }}）</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.decommissioned" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <template v-if="auxOpen.decommissioned">
            <p class="section-hint">Prometheus 还能扫到这些目标，但不在当前集群节点上，多半是关机后没摘抓取。不进发现问题、不扣健康分。连续出现的会进「已知常态」。断开时间取上次巡检已记录为 down 的时间。</p>
            <el-table :data="decommissionedRows" size="small" style="width: 100%">
              <el-table-column label="类型" width="90">
                <template #default="{ row }">{{ row.kind === 'target' ? '抓取' : '告警' }}</template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="140">
                <template #default="{ row }">{{ row.name || row.job || '-' }}</template>
              </el-table-column>
              <el-table-column prop="instance" label="实例" min-width="200">
                <template #default="{ row }">{{ row.instance || '-' }}</template>
              </el-table-column>
              <el-table-column label="断开时间" width="150">
                <template #default="{ row }">{{ row.when || '-' }}</template>
              </el-table-column>
              <el-table-column label="连续" width="80">
                <template #default="{ row }">{{ row.persistent ? '是' : '-' }}</template>
              </el-table-column>
              <el-table-column v-if="canManage" label="" width="72">
                <template #default="{ row }">
                  <el-button
                    v-if="row.key"
                    link
                    type="primary"
                    size="small"
                    @click="ignoreItem(row.key, row.label || row.instance, 'decommissioned')"
                  >忽略</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </div>

        <div class="analysis-section" v-if="ignoreList.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.ignored = !auxOpen.ignored">
            <el-icon><InfoFilled /></el-icon>
            <span>已手动忽略（{{ ignoreList.length }}）</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.ignored" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <template v-if="auxOpen.ignored">
            <p class="section-hint">点过忽略的条目。下次巡检不再报，可随时取消。</p>
            <el-table :data="ignoreList" size="small" style="width: 100%">
              <el-table-column prop="label" label="条目" min-width="240">
                <template #default="{ row }">{{ row.label || row.key }}</template>
              </el-table-column>
              <el-table-column prop="check_id" label="检查项" width="140" />
              <el-table-column prop="created_by" label="操作人" width="120">
                <template #default="{ row }">{{ row.created_by || '-' }}</template>
              </el-table-column>
              <el-table-column v-if="canManage" label="" width="88">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="unignoreItem(row.key)">取消忽略</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </div>

        <div class="analysis-section" v-if="uncoveredLines.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.uncovered = !auxOpen.uncovered">
            <el-icon><InfoFilled /></el-icon>
            <span>未覆盖（{{ uncoveredLines.length }}）</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.uncovered" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <template v-if="auxOpen.uncovered">
            <p class="section-hint">Prometheus 里没有对应指标，未检查，不等于健康。</p>
            <ul class="known-normals">
              <li v-for="(item, idx) in uncoveredLines" :key="idx">{{ item }}</li>
            </ul>
          </template>
        </div>

        <div class="analysis-section">
          <div class="section-header">
            <el-icon><MagicStick /></el-icon>
            <span>巡检报告摘要</span>
          </div>
          <div class="analysis-card">
            <div class="markdown-body">
              {{ currentReport.ai_analysis || 'No detailed analysis available for this report.' }}
            </div>
          </div>
        </div>

        <div class="analysis-section" v-if="currentReport.fleet_summary?.top_cpu?.length">
          <button type="button" class="section-header section-header-toggle" @click="auxOpen.charts = !auxOpen.charts">
            <el-icon><Histogram /></el-icon>
            <span>资源 Top 10</span>
            <el-icon class="toggle-caret">
              <ArrowDown v-if="auxOpen.charts" />
              <ArrowRight v-else />
            </el-icon>
          </button>
          <template v-if="auxOpen.charts">
          <el-row :gutter="20" class="metrics-row">
            <el-col :span="12" v-if="getServerTopOption('cpu_pct', 'CPU 使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">CPU 使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('cpu_pct', 'CPU 使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
            <el-col :span="12" v-if="getServerTopOption('mem_pct', '内存使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">内存使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('mem_pct', '内存使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
          </el-row>
          <el-row :gutter="20" class="metrics-row" style="margin-top: 20px;">
            <el-col :span="12" v-if="getServerTopOption('disk_pct', '磁盘(/)使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">磁盘(/)使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('disk_pct', '磁盘(/)使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
          </el-row>
          </template>
        </div>

        <div class="analysis-section" v-if="currentReport.alerts_summary">
          <div class="section-header">
            <el-icon><Warning /></el-icon>
            <span>告警分析</span>
          </div>
          <el-row :gutter="20" class="metrics-row">
            <el-col :span="12">
              <div class="chart-card">
                <div class="chart-title">Firing 告警严重度分布</div>
                <v-chart class="report-chart" :option="getAlertsPieOption()" autoresize />
              </div>
            </el-col>
            <el-col :span="12">
              <div class="chart-card">
                <div class="chart-title">Top 告警</div>
                <el-table :data="currentReport.alerts_summary.top_alerts || []" style="width: 100%">
                  <el-table-column prop="name" label="Alert" min-width="220" />
                  <el-table-column prop="count" label="Count" width="90" />
                </el-table>
              </div>
            </el-col>
          </el-row>
        </div>

        <div class="analysis-section" v-if="currentReport.trend_7d && currentReport.trend_7d.length">
          <div class="section-header">
            <el-icon><DataLine /></el-icon>
            <span>7 日趋势</span>
          </div>
          <p class="section-hint">日巡检快照拼起来的均线，用来看这周水位；单机任意时间窗仍去 Grafana。</p>
          <div class="chart-card">
            <div class="chart-title">健康评分 / 告警数量</div>
            <v-chart class="report-chart" :option="getTrendOption()" autoresize />
          </div>
          <div class="chart-card" style="margin-top: 16px" v-if="hasFleetTrend">
            <div class="chart-title">均 CPU / 内存 / 磁盘</div>
            <v-chart class="report-chart" :option="getFleetTrendOption()" autoresize />
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="openTicketDialog">提交系统工单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ticketDialogVisible" title="提交系统运维工单" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="ticketTitle" />
        </el-form-item>
        <el-form-item label="严重度">
          <el-select v-model="ticketSeverity" style="width: 100%">
            <el-option label="低" value="low" />
            <el-option label="中" value="medium" />
            <el-option label="高" value="high" />
            <el-option label="紧急" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明（可编辑）">
          <el-input v-model="ticketDescription" type="textarea" :rows="12" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ticketDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ticketSubmitting" @click="submitOpsTicket">提交</el-button>
      </template>
    </el-dialog>

    <!-- Config Dialog -->
    <el-dialog v-model="configVisible" title="Inspection Configuration" width="540px" class="custom-dialog">
      <el-form :model="configForm" label-width="140px" label-position="top" class="config-form">
        <div class="form-section">
          <h3 class="section-title">Monitoring Data</h3>
          <el-form-item label="Prometheus Endpoint">
            <el-input v-model="configForm.prometheus_url" placeholder="http://prometheus:9090" />
            <div class="form-tip">巡检会拉 Prometheus：node-exporter、告警、pvc_stats_*（pvc-stats-exporter）、以及若存在的 kube-state-metrics / blackbox</div>
          </el-form-item>
        </div>

        <div class="form-section">
          <h3 class="section-title">AI Analysis Engine (Ark/Doubao)</h3>
          <el-form-item label="Ark Base URL">
            <el-input v-model="configForm.ark_base_url" placeholder="https://ark.cn-beijing.volces.com/api/v3" />
          </el-form-item>
          <el-form-item label="Ark API Key">
            <el-input
              v-model="configForm.ark_api_key"
              type="password"
              show-password
              :placeholder="configForm.ark_api_key_set ? '已保存密钥：留空表示不修改' : '可选'"
            />
          </el-form-item>
          <el-form-item label="Ark Model Endpoint ID">
            <el-input v-model="configForm.ark_model_id" placeholder="ep-202xxxxxxxx-xxxxx" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="configVisible = false">Cancel</el-button>
          <el-button type="primary" @click="saveConfig" class="shadow-btn">Save Configuration</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Logs Dialog -->
    <el-dialog v-model="logDialogVisible" title="System Inspection Logs" width="900px" top="5vh">
      <div class="log-viewer-container">
        <div class="log-header">
           <span class="log-filename">inspection.log</span>
           <div class="log-controls">
             <el-pagination 
               small
               layout="prev, pager, next"
               :total="logTotal"
               :page-size="logPageSize"
               v-model:current-page="logPage"
               @current-change="fetchLogs"
             />
             <el-button size="small" :icon="Refresh" circle @click="fetchLogs(logPage)" />
           </div>
        </div>
        <div class="log-content" v-loading="logLoading">
          <pre>{{ logContent || 'No logs available.' }}</pre>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch, provide, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '@/stores/system'
import type { InspectionReport } from '@/types/system'
import { 
  Setting, Search, Calendar, 
  MagicStick, Warning, CircleCheck,
  DataLine, Histogram, Document, Refresh, Download,
  List, Box, Coin, InfoFilled, Monitor, ArrowRight, ArrowDown
} from '@element-plus/icons-vue'
import { taskApi } from '@/api/task'
import { opsTicketsApi } from '@/api/ops_tickets'
import { systemApi } from '@/api/system'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
} from 'echarts/components'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
])

const systemStore = useSystemStore()
const router = useRouter()
const canViewInspection = computed(() => systemStore.isAdmin || systemStore.hasPermission('view_inspection'))
const canManage = computed(() => systemStore.isAdmin || systemStore.hasPermission('run_inspection'))
// ... existing refs and computed ...

const getServerTopOption = (key: string, title: string) => {
  const rep: any = currentReport.value
  const top = rep?.fleet_summary?.top_cpu || rep?.servers || []
  const list = Array.isArray(top) ? top : []
  const sorted = [...list].sort((a: any, b: any) => Number(b?.[key] || 0) - Number(a?.[key] || 0)).slice(0, 10)
  if (!sorted.length) return {}
  return {
    title: { text: '', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: sorted.map((s: any) => s.instance || '-'), axisLabel: { interval: 0, rotate: 25 } },
    yAxis: { type: 'value', name: '%' },
    series: [{ name: title, type: 'bar', data: sorted.map((s: any) => s[key]), itemStyle: { color: '#3b82f6' } }],
  }
}

const getAlertsPieOption = () => {
  const a: any = currentReport.value?.alerts_summary || {}
  const crit = Number(a.critical_total || 0)
  const warn = Number(a.warning_total || 0)
  const other = Math.max(0, Number(a.firing_total || 0) - crit - warn)
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: '70%',
        data: [
          { name: 'Critical/High', value: crit },
          { name: 'Warning', value: warn },
          { name: 'Other', value: other },
        ].filter((x) => x.value > 0),
      },
    ],
  }
}

const getTrendOption = () => {
  const t: any[] = (currentReport.value?.trend_7d || []) as any[]
  const dates = t.map((x) => x.date)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Score', 'Firing', 'Critical'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: 'Score', min: 0, max: 100 },
      { type: 'value', name: 'Alerts', min: 0 },
    ],
    series: [
      { name: 'Score', type: 'line', yAxisIndex: 0, data: t.map((x) => x.score ?? null), smooth: true },
      { name: 'Firing', type: 'bar', yAxisIndex: 1, data: t.map((x) => x.firing ?? 0), itemStyle: { color: '#f59e0b' } },
      { name: 'Critical', type: 'bar', yAxisIndex: 1, data: t.map((x) => x.critical ?? 0), itemStyle: { color: '#ef4444' } },
    ],
  }
}

const hasFleetTrend = computed(() =>
  (currentReport.value?.trend_7d || []).some(
    (x: any) => x.avg_cpu != null || x.avg_mem != null || x.avg_disk != null
  )
)

const getFleetTrendOption = () => {
  const t: any[] = (currentReport.value?.trend_7d || []) as any[]
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['均 CPU', '均内存', '均磁盘'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: t.map((x) => x.date) },
    yAxis: { type: 'value', name: '%', min: 0, max: 100 },
    series: [
      { name: '均 CPU', type: 'line', data: t.map((x) => x.avg_cpu ?? null), smooth: true, itemStyle: { color: '#3b82f6' } },
      { name: '均内存', type: 'line', data: t.map((x) => x.avg_mem ?? null), smooth: true, itemStyle: { color: '#8b5cf6' } },
      { name: '均磁盘', type: 'line', data: t.map((x) => x.avg_disk ?? null), smooth: true, itemStyle: { color: '#10b981' } },
    ],
  }
}
const reports = computed(() => systemStore.reports)
const loading = computed(() => systemStore.loading)
const inspectionConfig = computed(() => systemStore.inspectionConfig)

const tableData = computed(() => {
  return reports.value || []
})

const formatReportTime = (row: any) => {
  const ts = row?.timestamp
  if (ts) {
    const d = new Date(ts)
    if (!isNaN(d.getTime())) return d.toLocaleString()
  }
  const id = row?.report_id || ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(id)) return id
  if (!id) return '-'
  try {
    const d = new Date(String(id).replace(/-/g, '/'))
    return isNaN(d.getTime()) ? id : d.toLocaleString()
  } catch (e) {
    return id
  }
}

const hasScore = (score: unknown) => score !== null && score !== undefined && Number.isFinite(Number(score))

const serverLabel = (row: any) => {
  const svc = (row?.service || '').trim()
  const inst = (row?.instance || '').trim()
  if (!svc || svc === inst) return '-'
  return svc
}

const dialogVisible = ref(false)
const configVisible = ref(false)
const currentReport = ref<InspectionReport | null>(null)
const auxOpen = reactive({ normals: false, uncovered: false, decommissioned: false, ignored: false, charts: false, nodes: true })
const nodeQuery = ref('')
const nodeKindFilter = ref('all')
const ignoreList = ref<any[]>([])
const ignoreKeySet = computed(() => new Set(ignoreList.value.map((i: any) => i.key).filter(Boolean)))

const configForm = ref({
  prometheus_url: '',
  ark_base_url: '',
  ark_api_key: '',
  ark_api_key_set: false,
  ark_model_id: ''
})

watch(inspectionConfig, (newVal) => {
  if (newVal) {
    configForm.value = { ...newVal }
  }
}, { immediate: true })

onMounted(() => {
  systemStore.fetchReports()
  systemStore.fetchInspectionConfig()
  loadIgnores()
})

const handleRun = () => {
  systemStore.runInspection()
}

const saveConfig = async () => {
  await systemStore.saveInspectionConfig(configForm.value)
  configVisible.value = false
}

const getScoreType = (score: number) => {
  if (!hasScore(score)) return 'info'
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'danger'
}

const getProgressStatus = (score: number) => {
  if (!hasScore(score)) return ''
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'exception'
}

const scoreReasons = computed(() => {
  const reasons = currentReport.value?.health_summary?.reasons || []
  return reasons.filter((r: string) => r && r !== 'System Healthy')
})
const esClusters = computed(() => currentReport.value?.elasticsearch?.clusters || [])
const esHeapNodes = computed(() => currentReport.value?.elasticsearch?.heap_nodes || [])
const middlewareRows = computed(() => currentReport.value?.middleware?.items || [])
const checklistCovered = computed(() =>
  (currentReport.value?.checklist || [])
    .filter((c: any) => c.level !== 'skip' && c.id !== 'decommissioned')
    .map((c: any, i: number) => {
      const ignored = ignoreKeySet.value.has(`check:${c.id}`)
      if (ignored && (c.level === 'warning' || c.level === 'critical')) {
        return { ...c, level: 'ok', result: '已忽略', _key: `${c.id || 'check'}-${i}` }
      }
      return { ...c, _key: `${c.id || 'check'}-${i}` }
    })
)
const decommissionedRows = computed(() => {
  const listed = currentReport.value?.decommissioned || []
  if (listed.length) return listed.filter((row: any) => !row.key || !ignoreKeySet.value.has(row.key))
  const folded = (currentReport.value?.checklist || []).find((c: any) => c.id === 'decommissioned')
  return (folded?.detail || []).map((label: string) => ({ label, instance: label, name: 'HostDown', kind: 'alert' }))
})
const uncoveredLines = computed(() => {
  const rows = currentReport.value?.checklist || []
  const folded = rows.find((c: any) => c.id === 'uncovered')
  if (folded?.detail?.length) return folded.detail
  return rows.filter((c: any) => c.level === 'skip').map((c: any) => `${c.name}：${c.result}`)
})
const discoveredMetricCount = computed(() => {
  const n = currentReport.value?.middleware?.discovered_names
  if (n) return n
  return currentReport.value?.discovery?.metric_name_count || 0
})
const workloadRows = computed(() => {
  const rows = currentReport.value?.workloads || []
  if (!rows.length) return []
  const first = rows[0] as { pod?: string; kind?: string; pods?: unknown[] }
  if (first.pod && !first.kind && !Array.isArray(first.pods)) {
    return rows.map((p: any) => ({
      key: p.key || `${p.namespace || ''}/${p.pod}`,
      kind: 'Pod',
      namespace: p.namespace,
      name: p.pod,
      service: p.service,
      ready: p.phase === 'running' && !p.waiting ? 1 : 0,
      desired: 1,
      level: p.level,
      pods: [p],
    }))
  }
  return rows
})

const workloadNsGroups = computed(() => {
  const map = new Map<string, any[]>()
  for (const row of workloadRows.value) {
    const ns = row.namespace || '-'
    if (!map.has(ns)) map.set(ns, [])
    map.get(ns)!.push(row)
  }
  const rank = (level: string) => (level === 'critical' ? 0 : level === 'warning' ? 1 : 2)
  const worst = (items: any[]) => {
    if (items.some((i) => i.level === 'critical')) return 'critical'
    if (items.some((i) => i.level === 'warning')) return 'warning'
    return 'ok'
  }
  return [...map.entries()].map(([namespace, workloads]) => ({
    key: namespace,
    namespace,
    count: workloads.length,
    ready: workloads.reduce((s, w) => s + Number(w.ready || 0), 0),
    desired: workloads.reduce((s, w) => s + Number(w.desired || 0), 0),
    level: worst(workloads),
    workloads: workloads.map((w, i) => ({
      ...w,
      key: w.key || `${namespace}/${w.kind || 'wl'}/${w.name || i}`,
    })),
  })).sort((a, b) => rank(a.level) - rank(b.level) || a.namespace.localeCompare(b.namespace))
})

const esStatusType = (status?: string) => {
  if (status === 'green') return 'success'
  if (status === 'yellow') return 'warning'
  if (status === 'red') return 'danger'
  return 'info'
}

const checkTagType = (level?: string) => {
  if (level === 'ok') return 'success'
  if (level === 'warning') return 'warning'
  if (level === 'critical') return 'danger'
  if (level === 'info') return 'info'
  return 'info'
}

const checkLevelLabel = (level?: string) => {
  if (level === 'ok') return '正常'
  if (level === 'warning') return '关注'
  if (level === 'critical') return '严重'
  if (level === 'skip') return '未覆盖'
  if (level === 'info') return '记录'
  return level || '-'
}

const checkItems = (row: any) => {
  const raw = Array.isArray(row?.items) && row.items.length
    ? row.items
    : (row?.detail || []).map((label: string) => ({ key: `${row.id}:${label}`, label }))
  return raw.filter((it: any) => it && (it.label || it.key) && !ignoreKeySet.value.has(it.key))
}

const loadIgnores = async () => {
  try {
    ignoreList.value = await systemApi.listInspectionIgnores()
  } catch (e) {
    console.error(e)
  }
}

const ignoreItem = async (key: string, label?: string, checkId?: string) => {
  if (!key) return
  try {
    await systemApi.addInspectionIgnore({ key, label: label || key, check_id: checkId || '' })
    await loadIgnores()
    ElMessage.success('已忽略，下次巡检不再报')
  } catch (e) {
    console.error(e)
  }
}

const unignoreItem = async (key: string) => {
  if (!key) return
  try {
    await systemApi.removeInspectionIgnore(key)
    await loadIgnores()
    ElMessage.success('已取消忽略')
  } catch (e) {
    console.error(e)
  }
}

const verdictAlertType = computed(() => {
  const v = currentReport.value?.verdict || ''
  if (v.includes('需关注')) return 'warning'
  if (v.includes('无法判定')) return 'warning'
  if (v.includes('未见明显异常')) return 'success'
  return 'info'
})

const formatBytes = (n?: number) => {
  const val = Number(n || 0)
  const units = ['B', 'Ki', 'Mi', 'Gi', 'Ti']
  let size = val
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i += 1
  }
  return `${size.toFixed(1)}${units[i]}`
}

const fmtPct = (n?: number) => {
  if (n == null || Number.isNaN(Number(n))) return '-'
  return Number(n).toFixed(1)
}

const fmtDelta = (n?: number) => {
  if (n == null || Number.isNaN(Number(n))) return '-'
  const v = Number(n)
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}pt`
}

const deltaClass = (n?: number) => {
  const v = Number(n)
  if (!Number.isFinite(v)) return ''
  if (v >= 10) return 'delta-hot'
  if (v > 0) return 'delta-up'
  if (v < 0) return 'delta-down'
  return ''
}

const clipPct = (n?: number) => {
  const v = Number(n || 0)
  if (Number.isNaN(v)) return 0
  return Math.max(0, Math.min(100, Math.round(v)))
}

const pctColor = (n: number | undefined, warn: number, crit: number) => {
  const v = Number(n || 0)
  if (v >= crit) return '#ef4444'
  if (v >= warn) return '#f59e0b'
  return '#22c55e'
}

const formatUptime = (hours?: number) => {
  const n = Number(hours || 0)
  if (!n) return '-'
  if (n >= 48) return `${(n / 24).toFixed(1)}d`
  return `${n.toFixed(1)}h`
}

const nodeKindLabel = (row: any) => {
  if (row?.kind === 'k8s' && row?.cloud === 'aws') return 'EKS'
  if (row?.kind === 'k8s') return 'K8s'
  return '独立'
}

const isIpv4 = (s?: string) => {
  const parts = String(s || '').split('.')
  if (parts.length !== 4) return false
  return parts.every((p) => /^\d+$/.test(p) && Number(p) >= 0 && Number(p) <= 255)
}

const hostFromInstance = (inst?: string) => {
  let t = String(inst || '').trim()
  if (t.includes('://')) t = t.split('://')[1] || t
  t = t.split('/')[0]
  if (t.startsWith('[') && t.includes(']')) return t.slice(1, t.indexOf(']'))
  if ((t.match(/:/g) || []).length === 1) return t.split(':')[0]
  return t
}

const displayIp = (row: any) => {
  if (row?.ip) return row.ip
  const host = hostFromInstance(row?.instance)
  return isIpv4(host) ? host : '-'
}

const machineName = (row: any) => {
  for (const cand of [row?.node_name, row?.hostname, row?.nodename, hostFromInstance(row?.instance)]) {
    const v = String(cand || '').trim()
    if (v && !isIpv4(v)) return v
  }
  return '-'
}

const nodeHotCount = computed(() =>
  (currentReport.value?.servers || []).filter((s: any) => s.level === 'warning' || s.level === 'critical').length
)

const filteredServers = computed(() => {
  const rows = currentReport.value?.servers || []
  const kind = nodeKindFilter.value
  const q = nodeQuery.value.trim().toLowerCase()
  return rows.filter((s: any) => {
    if (kind === 'k8s' && s.kind !== 'k8s') return false
    if (kind === 'host' && s.kind === 'k8s') return false
    if (kind === 'hot' && s.level !== 'warning' && s.level !== 'critical') return false
    if (!q) return true
    const blob = [s.ip, s.node_name, s.hostname, s.service, s.role, s.instance, s.nodegroup, s.instance_id, s.zone, s.instance_type, s.compute_type]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return blob.includes(q)
  })
})

const bytesResourceText = (used?: number, total?: number, pct?: number) => {
  if (total) return `${formatBytes(used)} / ${formatBytes(total)}（${fmtPct(pct)}%）`
  if (pct != null && pct !== undefined) return `${fmtPct(pct)}%`
  return '-'
}

const cpuResourceText = (row: any) => {
  const cores = Number(row?.cpu_cores || 0)
  const pct = Number(row?.cpu_pct)
  if (cores && Number.isFinite(pct)) {
    const used = (pct / 100) * cores
    return `${used.toFixed(1)} / ${cores} 核（${fmtPct(pct)}%）`
  }
  if (Number.isFinite(pct)) return `${fmtPct(pct)}%`
  return '-'
}

const viewReport = async (row: any) => {
  await systemStore.fetchReportDetail(row.report_id)
  const rep: any = systemStore.currentReport || {}
  const score =
    rep?.health_summary?.level === 'unknown'
      ? null
      : (rep?.health_summary?.score ??
        rep?.risk_summary?.score ??
        rep?.score ??
        row?.score ??
        null)
  currentReport.value = { ...rep, score }
  auxOpen.normals = false
  auxOpen.uncovered = false
  auxOpen.decommissioned = false
  auxOpen.ignored = false
  auxOpen.charts = false
  auxOpen.nodes = true
  dialogVisible.value = true
}

const ticketDialogVisible = ref(false)
const ticketTitle = ref('')
const ticketDescription = ref('')
const ticketSeverity = ref('medium')
const ticketSubmitting = ref(false)

const openTicketDialog = () => {
  const rep: any = currentReport.value
  if (!rep?.report_id) {
    ElMessage.warning('报告数据不完整')
    return
  }
  const hs = rep.health_summary || rep.risk_summary || {}
  const reasons = (hs.reasons || []).filter(Boolean)
  const alerts = rep.alerts_summary?.top_alerts || []
  const rid = rep.report_id as string
  ticketTitle.value = `巡检处置 · ${rid}`
  let desc = `关联巡检报告: ${rid}\n健康分: ${rep.score ?? '-'}\n`
  if (reasons.length) desc += '\n健康原因:\n' + reasons.map((r: string) => `- ${r}`).join('\n')
  if (alerts.length)
    desc += '\nTOP 告警:\n' + alerts.slice(0, 8).map((a: any) => `- ${a.name} (${a.count})`).join('\n')
  if (rep.ai_analysis) desc += '\n\n摘要:\n' + String(rep.ai_analysis).slice(0, 1200)
  ticketDescription.value = desc
  ticketSeverity.value =
    rep.score != null && Number(rep.score) < 60 ? 'critical' : Number(rep.score) < 80 ? 'high' : 'medium'
  ticketDialogVisible.value = true
}

const submitOpsTicket = async () => {
  const rep: any = currentReport.value
  if (!rep?.report_id) return
  ticketSubmitting.value = true
  try {
    const hs = rep.health_summary || rep.risk_summary || {}
    await opsTicketsApi.create({
      title: ticketTitle.value,
      description: ticketDescription.value,
      inspection_report_id: rep.report_id as string,
      severity: ticketSeverity.value,
      inspection_snapshot: {
        score: rep.score,
        health_reasons: hs.reasons || [],
        top_alerts: (rep.alerts_summary?.top_alerts || []).slice(0, 15),
      },
    })
    ElMessage.success('工单已提交')
    ticketDialogVisible.value = false
    dialogVisible.value = false
    router.push('/system/tickets')
  } finally {
    ticketSubmitting.value = false
  }
}

// Log Viewer Logic
const logDialogVisible = ref(false)
const logLoading = ref(false)
const logContent = ref('')
const logPage = ref(1)
const logPageSize = ref(1000)
const logTotal = ref(0)

const showLogs = () => {
  logDialogVisible.value = true
  fetchLogs(1)
}

const fetchLogs = async (page = 1) => {
  logPage.value = page
  logLoading.value = true
  try {
    // Assuming inspection.log exists in logs/inspection.log or just inspection
    // taskApi.getTaskLogs takes a task_id and appends .log
    // So 'inspection' -> 'logs/inspection.log'
    const res = await taskApi.getTaskLogs('inspection', { 
      page, 
      page_size: logPageSize.value,
      reverse: true 
    })
    logContent.value = res.lines.join('')
    logTotal.value = res.total
  } catch (e) {
    logContent.value = `Error loading logs: ${e}`
  } finally {
    logLoading.value = false
  }
}
</script>

<style scoped>
/* Log Viewer Styles */
.log-viewer-container {
  display: flex;
  flex-direction: column;
  height: 600px;
  background: #0f172a;
  border-radius: 4px;
  overflow: hidden;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  color: #e2e8f0;
}

.log-filename {
  font-weight: 600;
  font-size: 14px;
}

.log-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  color: #cbd5e1;
  font-family: 'Menlo', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.log-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Existing Styles */
.inspection-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px 0;
}

.page-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

.table-card {
  border: 1px solid #f1f5f9 !important;
  border-radius: 12px !important;
}

.report-id-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  color: #334155;
}

.report-icon {
  color: #3b82f6;
}

.score-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.score-tag {
  font-weight: 700;
  font-size: 12px;
  min-width: 36px;
  text-align: center;
}

.status-icon-placeholder {
  font-size: 24px;
  color: #94a3b8;
}

.summary-text {
  font-size: 13px;
  color: #64748b;
}

.report-content {
  padding: 8px;
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 32px 48px;
  margin-bottom: 24px;
}

.findings-list ol {
  margin: 0 0 12px 18px;
  padding: 0;
  color: #334155;
  font-size: 13px;
  line-height: 1.7;
}

.known-normals {
  margin: 0;
  padding-left: 18px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.8;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-item .label {
  font-size: 11px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.5px;
}

.meta-item .value {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.score-display {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.score-value {
  font-size: 32px;
  font-weight: 800;
}

.score-value.success { color: #10b981; }
.score-value.warning { color: #f59e0b; }
.score-value.danger { color: #ef4444; }

.score-total {
  font-size: 14px;
  color: #94a3b8;
  font-weight: 600;
}

.analysis-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: #1e293b;
  font-size: 16px;
}

.section-hint {
  font-size: 12px;
  color: #64748b;
  margin: -8px 0 0;
}

.section-header-toggle {
  cursor: pointer;
  border: none;
  background: none;
  padding: 0;
  width: 100%;
  font: inherit;
}

.section-header-toggle .toggle-caret {
  margin-left: auto;
  color: #94a3b8;
}

.check-detail-list {
  margin: 0;
  padding: 4px 8px 8px 28px;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.pct-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pct-cell .el-progress {
  flex: 1;
}

.pct-cell span {
  width: 42px;
  text-align: right;
  font-size: 12px;
  color: #334155;
}

.bytes-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #94a3b8;
}

.node-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 8px 0 10px;
}

.resource-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.resource-cell span {
  font-size: 12px;
  color: #334155;
  line-height: 1.3;
}

.delta-up {
  color: #d97706;
}

.delta-hot {
  color: #dc2626;
  font-weight: 600;
}

.delta-down {
  color: #059669;
}

.check-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}


.score-reasons {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
  max-width: 280px;
  line-height: 1.4;
}

.analysis-card {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 24px;
}

.markdown-body {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 14px;
  color: #334155;
}

.metrics-row {
  margin-top: 10px;
}

.chart-card {
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 16px;
}

.chart-title {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 12px;
  text-transform: uppercase;
}

.report-chart {
  height: 200px;
}

.forecast-card {
  display: flex;
  justify-content: space-around;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 20px;
}

.forecast-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.forecast-item .label {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
}

.forecast-item .value {
  font-size: 24px;
  font-weight: 700;
  color: #3b82f6;
}

.form-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
  border-left: 3px solid #3b82f6;
  padding-left: 8px;
}

.form-tip {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
}

.shadow-btn {
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

:deep(.el-form-item__label) {
  font-weight: 600;
  color: #475569;
  font-size: 13px;
}
</style>
