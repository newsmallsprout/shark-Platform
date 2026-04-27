<template>
  <div class="traffic-page">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">Traffic Dashboard</h2>
        <p class="page-subtitle">Monitor and analyze traffic trends, latency, error rate and geo distribution</p>
      </div>
      <div class="header-actions">
        <el-radio-group v-model="range" size="small" class="range-group" @change="onRangePresetChange">
          <el-radio-button label="10m">10m</el-radio-button>
          <el-radio-button label="1h">1H</el-radio-button>
          <el-radio-button label="6h">6H</el-radio-button>
          <el-radio-button label="24h">24H</el-radio-button>
          <el-radio-button label="7d">7D</el-radio-button>
          <el-radio-button label="30d">30D</el-radio-button>
          <el-radio-button label="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-if="range === 'custom'"
          v-model="customTimeRange"
          type="datetimerange"
          range-separator="—"
          start-placeholder="开始"
          end-placeholder="结束"
          size="small"
          class="custom-range-picker"
          :shortcuts="customRangeShortcuts"
          @change="onCustomRangePicked"
        />
        <el-select
          v-model="trafficSource"
          size="small"
          class="source-select"
          style="width: 168px"
          placeholder="日志源"
          :disabled="sourceOptions.length <= 1"
          @change="() => loadAll(false)"
        >
          <el-option v-for="s in sourceOptions" :key="s.id" :label="s.label" :value="s.id" />
        </el-select>
        <el-select v-model="pollSec" size="small" class="poll-select" style="width: 110px">
          <el-option :value="0" label="手动刷新" />
          <el-option :value="5" label="5s" />
          <el-option :value="15" label="15s" />
          <el-option :value="30" label="30s" />
        </el-select>
        <div class="refresh-status" :class="{ syncing: softRefreshing }">
          <span class="refresh-dot" :class="{ active: pollSec > 0 || softRefreshing }" />
          <span>{{ refreshLabel }}</span>
        </div>
        <el-tooltip content="开启后从 Redis/文件全量拉取原始日志，含慢接口与 Top IP，数据量大时易超时" placement="top">
          <div class="raw-detail-switch">
            <span class="raw-detail-label">原始明细</span>
            <el-switch v-model="rawLogDetail" size="small" @change="() => loadAll(false)" />
          </div>
        </el-tooltip>
        <el-button :icon="Setting" size="small" class="toolbar-btn" @click="onOpenTrafficConfig">设置</el-button>
        <el-button
          :icon="Refresh"
          size="small"
          type="primary"
          class="toolbar-btn shadow-btn"
          :loading="loading"
          @click="() => loadAll(false)"
        >
          刷新
        </el-button>
      </div>
    </div>

    <el-tabs v-model="mainTab" class="main-tabs">
      <el-tab-pane label="流量趋势" name="trend">
        <div v-if="!overview.log_configured" class="warn-banner page-panel">
          <el-icon><WarningFilled /></el-icon>
          <span>未配置 Nginx access 日志路径。请在设置中填写或通过环境变量 <code>TRAFFIC_NGINX_ACCESS_LOG</code> 指定。</span>
        </div>
        <div class="kpi-row">
          <div v-for="card in kpiCards" :key="card.key" class="page-panel kpi-card">
            <div class="kpi-head">
              <div>
                <div class="kpi-label">{{ card.label }}</div>
                <div class="kpi-value">{{ card.value }}</div>
                <div class="kpi-src">{{ card.source }}</div>
              </div>
              <div :ref="(el) => setKpiRef(card.key, el)" class="kpi-spark" />
            </div>
          </div>
        </div>

        <el-row :gutter="16" class="chart-row">
          <el-col :xs="24" :xl="16" :lg="15">
            <div class="page-panel chart-wrap">
              <div class="chart-title">QPS / 请求量</div>
              <div ref="chartQps" class="echart" />
            </div>
            <div class="page-panel chart-wrap">
              <div class="chart-title">P50 / P95 / P99 响应时间 (ms)</div>
              <div ref="chartLat" class="echart" />
            </div>
            <div class="page-panel chart-wrap">
              <div class="chart-title">状态码吞吐 (req/s)</div>
              <div ref="chartErr" class="echart" />
            </div>
          </el-col>
          <el-col :xs="24" :xl="8" :lg="9">
            <div class="page-panel chart-wrap">
              <div class="chart-title">国家 / 地区热力</div>
              <div ref="chartMap" class="echart map-h" />
            </div>
            <div class="page-panel chart-wrap">
              <div class="chart-title">Top 国家请求量</div>
              <div ref="chartCountry" class="echart country-h" />
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="16" class="bottom-row">
          <el-col :xs="24" :md="8">
            <div class="page-panel chart-wrap">
              <div class="chart-title">状态码分布</div>
              <div ref="chartPie" class="echart pie-h" />
            </div>
          </el-col>
          <el-col :xs="24" :md="16">
            <div class="page-panel chart-wrap table-wrap">
              <div class="chart-title">Top 请求路径</div>
              <el-table
                :data="pathsRows"
                :row-key="rowKeyPath"
                :row-class-name="pathsTableRowClass"
                size="small"
                class="dark-table traffic-data-table"
                max-height="280"
              >
                <el-table-column prop="path" label="Path" min-width="160" show-overflow-tooltip />
                <el-table-column prop="requests" label="Req" width="80" />
                <el-table-column prop="p95_ms" label="P95 ms" width="90" />
                <el-table-column prop="errors_5xx" label="5xx" width="60" />
                <el-table-column prop="share_pct" label="%" width="60" />
              </el-table>
            </div>
          </el-col>
        </el-row>

        <el-row v-if="errDetail" :gutter="16" class="err-detail-row">
          <el-col :span="24">
            <div class="page-panel chart-wrap err-detail-panel">
              <div class="chart-title">错误详情</div>
              <div v-if="errDetail.n_err === 0" class="err-detail-empty">本窗口无 4xx / 5xx</div>
              <template v-else>
                <el-alert
                  v-if="errDetail.rollup_no_status_breakdown"
                  type="info"
                  :closable="false"
                  class="err-detail-alert"
                  show-icon
                >
                  分钟聚合只存 2xx/4xx/5xx 汇总，无法按「路径 + 具体状态码」展示。请开启「原始明细」后刷新。
                </el-alert>
                <el-table
                  v-else
                  :data="errDetail.path_code_breakdown || []"
                  size="small"
                  row-key="path"
                  class="dark-table traffic-data-table err-detail-table"
                  max-height="420"
                  empty-text="无路径级数据"
                >
                  <el-table-column prop="path" label="Path" min-width="200" show-overflow-tooltip>
                    <template #default="{ row }">
                      <code class="err-path-code">{{ row.path }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column label="状态码（4xx / 5xx）" min-width="280">
                    <template #default="{ row }">
                      <span class="err-code-tag-wrap">
                        <el-tag
                          v-for="(c, i) in row.codes || []"
                          :key="`${row.path}-${c.code}-${i}`"
                          :type="c.code >= 500 ? 'danger' : 'warning'"
                          size="small"
                          effect="plain"
                          class="err-code-tag"
                        >
                          {{ c.code }} ×{{ c.count }}
                        </el-tag>
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="total_errors" label="合计" width="90" align="right" />
                </el-table>
              </template>
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="24">
            <div class="page-panel chart-wrap table-wrap">
              <div class="chart-title">慢接口 Top · Top IP</div>
              <el-row :gutter="12">
                <el-col :xs="24" :md="12">
                  <el-table
                    :data="slowRows"
                    :row-key="rowKeyPath"
                    :row-class-name="slowTableRowClass"
                    size="small"
                    class="dark-table traffic-data-table"
                    max-height="220"
                  >
                    <el-table-column prop="path" label="Path" min-width="140" show-overflow-tooltip />
                    <el-table-column prop="p95_ms" label="P95" width="80" />
                    <el-table-column prop="p99_ms" label="P99" width="80" />
                  </el-table>
                </el-col>
                <el-col :xs="24" :md="12">
                  <el-table
                    :data="ipRows"
                    :row-key="rowKeyIp"
                    :row-class-name="ipTableRowClass"
                    size="small"
                    class="dark-table traffic-data-table"
                    max-height="220"
                  >
                    <el-table-column prop="ip" label="IP" width="140" />
                    <el-table-column prop="country" label="Region" width="100" />
                    <el-table-column prop="requests" label="Req" width="80" />
                  </el-table>
                </el-col>
              </el-row>
            </div>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="请求流转" name="flow" lazy>
        <el-alert
          v-if="jaegerError"
          type="warning"
          :closable="false"
          show-icon
          class="jaeger-alert"
          :title="jaegerError"
        />
        <el-alert
          v-else-if="!jaegerConfigured"
          type="info"
          :closable="false"
          show-icon
          class="jaeger-alert"
          title="未配置 Jaeger Query"
        >
          请在中心环境设置 <code>JAEGER_QUERY_BASE_URL</code>（如 <code>http://jaeger:16686</code>，视集群 Service
          名为准），并可选 <code>JAEGER_DEFAULT_SERVICE</code>、<code>JAEGER_QUERY_TOKEN</code> 等。保存后切回本 Tab
          即可拉取 Traces 与依赖边。
        </el-alert>
        <div v-if="jaegerUiBase" class="flow-jaeger-link mb-8">
          <a :href="jaegerUiBase" target="_blank" rel="noopener">打开 Jaeger UI</a>
        </div>
        <el-row :gutter="16" class="flow-row" align="middle">
          <el-col :xs="24" :md="8">
            <el-select
              v-model="jaegerService"
              filterable
              clearable
              allow-create
              default-first-option
              placeholder="选择或手输服务名（与左侧时间范围一致）"
              size="small"
              style="width: 100%"
              @change="onJaegerServiceChange"
            >
              <el-option v-for="s in jaegerServices" :key="s" :label="s" :value="s" />
            </el-select>
          </el-col>
        </el-row>
        <el-row :gutter="16" class="flow-row mt-8">
          <el-col :xs="24" :lg="16" :md="14">
            <div class="page-panel flow-deps-panel">
              <div class="flow-graph-head">
                <div class="chart-title">
                  {{ selectedTraceId ? 'Trace 链路与时延' : '服务级依赖（时间窗内）' }}
                </div>
                <el-button
                  v-if="selectedTraceId"
                  type="primary"
                  link
                  size="small"
                  @click="clearTraceSelection"
                  >清除选中</el-button
                >
              </div>
              <p v-if="flowGraphError" class="ph-desc flow-graph-err">{{ flowGraphError }}</p>
              <div
                v-show="selectedTraceId && !flowGraphError"
                v-loading="flowGraphLoading"
                ref="flowGraphEl"
                class="flow-graph-echart"
              />
              <p
                v-if="!selectedTraceId && !jaegerDepItems.length"
                class="ph-desc"
                style="margin-top: 0"
              >
                点选 trace 后显示 <strong>向下展开的调用树</strong>；默认只展开
                2 层，点节点再展开，悬停看完整 op。可<strong>拖动画布/滚轮缩放</strong>。图上仅一行标签，减少叠字。
              </p>
              <p v-else-if="!selectedTraceId && jaegerDepItems.length" class="ph-desc">本时间窗服务间依赖：</p>
              <ul v-if="!selectedTraceId && jaegerDepItems.length" class="dep-list">
                <li v-for="(d, i) in jaegerDepItems" :key="i" class="dep-row">
                  <span class="dep-node">{{ d.parent }}</span>
                  <span class="dep-arrow">→</span>
                  <span class="dep-node">{{ d.child }}</span>
                  <el-tag v-if="d.call_count" size="small" class="ml-6">{{ d.call_count }}</el-tag>
                </li>
              </ul>
            </div>
          </el-col>
          <el-col :xs="24" :lg="8" :md="10">
            <div class="page-panel chart-wrap table-wrap">
              <div class="chart-title">最近 Trace</div>
              <el-input
                v-model="traceIdFilter"
                class="mb-8"
                clearable
                size="small"
                placeholder="按 Trace ID 搜索（子串）"
              />
              <el-table
                :data="traceRowsPaged"
                :row-key="rowKeyTrace"
                :row-class-name="traceTableRowClassWithSelected"
                size="small"
                class="dark-table traffic-data-table traffic-trace-table"
                max-height="360"
                @row-click="onTraceTableRowClick"
              >
                <el-table-column label="Trace ID" min-width="200" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span :title="row.trace_id" class="trace-id-cell">{{ row.trace_id }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="root_service" label="Service" width="120" show-overflow-tooltip />
                <el-table-column prop="started_at" label="开始(UTC)" width="156" show-overflow-tooltip />
                <el-table-column prop="duration_ms" label="ms" width="72" />
                <el-table-column prop="span_count" label="Span" width="64" />
                <el-table-column prop="status" label="Status" width="64" />
              </el-table>
              <el-pagination
                v-model:current-page="tracePage"
                v-model:page-size="tracePageSize"
                class="trace-pager"
                size="small"
                layout="total, prev, pager, next, sizes"
                :page-sizes="[10, 20, 50, 100]"
                :total="traceRowsFiltered.length"
                background
              />
            </div>
          </el-col>
        </el-row>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="configOpen" title="Traffic 数据源配置" width="640px" class="traffic-dialog">
      <el-form :model="cfgForm" label-width="150px">
        <el-form-item label="启用采集">
          <el-switch v-model="cfgForm.enabled" />
        </el-form-item>
        <el-form-item label="采集模式">
          <el-select v-model="cfgForm.access_log_mode" style="width: 100%">
            <el-option label="本地文件（Pod/共享卷）" value="file" />
            <el-option label="远程推送 → Redis（go-log-collector / 兼容 ingest）" value="redis" />
          </el-select>
          <div v-if="cfgForm.access_log_mode === 'redis'" class="form-hint">
            需 <code>TRAFFIC_REDIS_URL</code>。推荐
            <strong>go-log-collector</strong>：<code>POST {{ cfgForm.edge_ingest_path || '/api/edge/logs' }}</code>，请求头
            <code>X-Shark-Edge-Token: &lt;{{ cfgForm.edge_token_env || 'SHARK_EDGE_TOKEN' }}&gt;</code>（与中心环境变量一致；未设
            <code>SHARK_EDGE_TOKEN</code> 时可与 <code>TRAFFIC_INGEST_TOKEN</code> 相同）。Body 中
            <code>stream_key</code> 会出现在大盘数据源中（自动发现，无需在下方逐行配齐）；<code>log_format</code> 与下表每行「行解析」或全局格式一致。兼容旧方式：
            <code>POST /api/traffic/ingest</code> + Bearer
            <code>TRAFFIC_INGEST_TOKEN</code>。 Redis：
            <el-tag :type="cfgForm.redis_env_configured ? 'success' : 'danger'" size="small" class="ml-6">
              {{ cfgForm.redis_env_configured ? '已配置' : '未配置 URL' }}
            </el-tag>
          </div>
        </el-form-item>
        <el-form-item v-if="cfgForm.access_log_mode === 'file'" label="Access log 路径">
          <el-input v-model="cfgForm.access_log_path" placeholder="/var/log/nginx/access.json.log" />
        </el-form-item>
        <template v-if="cfgForm.access_log_mode === 'redis'">
          <el-form-item v-if="cfgForm.time_based_rollup_enforced" label="大盘数据源">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="已接 ClickHouse：大盘按时间窗从分钟聚合取数"
            >
              ingest 经 Redis；分钟维度由 traffic_rollup_flush 落库。无数据时检查 TRAFFIC_ROLLUP_ENABLED 与定时任务。调试可设
              TRAFFIC_DASHBOARD_REDIS_FALLBACK=1。
            </el-alert>
          </el-form-item>
          <el-form-item label="Redis List Key">
            <el-input v-model="cfgForm.redis_log_key" placeholder="traffic:access:lines" />
          </el-form-item>
          <div class="form-hint">
            Redis 列表行数默认<strong>不限制</strong>（后台为 0：ingest 不做 LTRIM，读盘时读全表）。生产环境请自行保证 Redis
            内存；若需上限可在 Django Admin 中把 <code>redis_max_lines</code> /
            <code>dashboard_fetch_max_lines</code> 设为正数。
          </div>
        </template>
        <el-form-item label="日志格式（全局）">
          <el-select v-model="cfgForm.log_format">
            <el-option label="JSON 行" value="json" />
            <el-option label="Combined" value="combined" />
          </el-select>
          <div class="form-hint">多站点某行可填「行解析」覆盖；go-log-collector 的 <code>nginx_json</code> 等同 JSON 行。</div>
        </el-form-item>
        <el-form-item v-if="cfgForm.access_log_mode === 'file'" label="尾部读取字节">
          <el-input-number v-model="cfgForm.max_tail_bytes" :min="65536" :max="52428800" />
        </el-form-item>
        <el-form-item label="多站点 / 域名（可选）">
          <div class="form-hint">
            一般<strong>留空</strong>即可：ingest 与分钟聚合会登记 <code>stream_key</code>，大盘下拉与 Redis List 键
            <code>&lt;redis_log_key&gt;:&lt;id&gt;</code>（<code>TRAFFIC_REDIS_STREAM_LAYOUT=single</code> 时共用一个键）自动对齐。需要<strong>覆写</strong>某流的显示名、行解析、自定义
            <code>file_path</code> / <code>redis_key</code> 时再在此添加行。旧版
            <code>POST /api/traffic/ingest?source=&lt;id&gt;</code> 与
            <code>X-Traffic-Source: &lt;id&gt;</code> 仍有效。
          </div>
          <el-table :data="cfgForm.log_sources" border size="small" class="log-src-table">
            <el-table-column label="ID" width="120">
              <template #default="{ row }">
                <el-input v-model="row.id" size="small" placeholder="api" />
              </template>
            </el-table-column>
            <el-table-column label="显示名" min-width="120">
              <template #default="{ row }">
                <el-input v-model="row.label" size="small" placeholder="API" />
              </template>
            </el-table-column>
            <el-table-column label="行解析" width="150">
              <template #default="{ row }">
                <el-select v-model="row.log_format" size="small" clearable placeholder="继承全局" style="width: 100%">
                  <el-option label="继承全局" value="" />
                  <el-option label="json" value="json" />
                  <el-option label="nginx_json" value="nginx_json" />
                  <el-option label="combined" value="combined" />
                  <el-option label="auto" value="auto" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column v-if="cfgForm.access_log_mode === 'file'" label="文件路径" min-width="220">
              <template #default="{ row }">
                <el-input
                  v-model="row.file_path"
                  size="small"
                  placeholder="/var/log/nginx/access_api.json.log"
                />
              </template>
            </el-table-column>
            <el-table-column v-if="cfgForm.access_log_mode === 'redis'" label="Redis List Key" min-width="220">
              <template #default="{ row }">
                <el-input v-model="row.redis_key" size="small" placeholder="traffic:access:lines:api" />
              </template>
            </el-table-column>
            <el-table-column label="" width="72" fixed="right">
              <template #default="{ $index }">
                <el-button type="danger" link size="small" @click="removeLogSource($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button class="mt-8" size="small" @click="addLogSource">添加一行</el-button>
        </el-form-item>
        <el-form-item label="MaxMind mmdb">
          <el-input
            v-model="cfgForm.geoip_db_path"
            placeholder="/usr/share/GeoIP/GeoLite2-City.mmdb 或 GeoIP2-City.mmdb"
          />
          <div class="form-hint">MaxMind GeoIP2 / GeoLite2 城市库；可与环境变量 TRAFFIC_GEOIP_DB 二选一（后台优先）。</div>
        </el-form-item>
        <el-form-item label="使用巡检 Prometheus">
          <el-switch v-model="cfgForm.use_inspection_prometheus" />
        </el-form-item>
        <el-form-item label="Prometheus 覆盖">
          <el-input v-model="cfgForm.prometheus_url_override" placeholder="留空则走巡检配置" />
        </el-form-item>
        <el-form-item label="Blackbox PromQL">
          <el-input v-model="cfgForm.blackbox_promql" placeholder="默认 probe_success" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configOpen = false">取消</el-button>
        <el-button type="primary" @click="saveCfg">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
import * as echarts from 'echarts'
import { Refresh, Setting, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { trafficApi, type TrafficLogSourceRow } from '@/api/traffic'

echarts.registerTheme('shark-traffic', {
  backgroundColor: 'transparent',
  color: ['#3b82f6', '#60a5fa', '#93c5fd', '#38bdf8', '#2563eb', '#0284c7'],
  textStyle: {
    color: '#475569',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#cbd5e1' } },
    axisTick: { show: false },
    axisLabel: { color: '#64748b' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#64748b' },
    splitLine: { lineStyle: { color: 'rgba(203,213,225,0.55)' } },
  },
  timeAxis: {
    axisLine: { lineStyle: { color: '#cbd5e1' } },
    axisTick: { show: false },
    axisLabel: { color: '#64748b' },
  },
})

/** 默认 1 小时：短窗(10m)在仅走分钟聚合时易因 flush/冷启动显示全空；可手动选 10m。 */
const range = ref('1h')
const customTimeRange = ref<[Date, Date] | null>(null)
const customRangeShortcuts = [
  {
    text: '最近 24 小时',
    value: () => {
      const e = new Date()
      return [new Date(e.getTime() - 86400000), e] as [Date, Date]
    },
  },
  {
    text: '最近 7 天',
    value: () => {
      const e = new Date()
      return [new Date(e.getTime() - 7 * 86400000), e] as [Date, Date]
    },
  },
]
/** 关闭=分钟聚合（默认，快）；开启=全量原始日志（慢接口/IP，易超时） */
const rawLogDetail = ref(false)
const pollSec = ref(5)
const loading = ref(false)
const softRefreshing = ref(false)
const mainTab = ref('trend')
const configOpen = ref(false)
const trafficSource = ref('all')
const sourceOptions = ref<{ id: string; label: string }[]>([])

const overview = ref<any>({ series: { qps: [], error_rate: [] }, log_configured: true })
const errDetail = computed(() => overview.value?.error_detail ?? null)
const timeseries = ref<any>({})
const geoItems = ref<any[]>([])
const pathsRows = ref<any[]>([])
const slowRows = ref<any[]>([])
const ipRows = ref<any[]>([])
const statusPie = ref<any[]>([])
const allTraceRows = ref<any[]>([])
const traceIdFilter = ref('')
const tracePage = ref(1)
const tracePageSize = ref(10)
const selectedTraceId = ref('')
const flowGraphEl = ref<HTMLElement | null>(null)
const flowGraphLoading = ref(false)
const flowGraphError = ref('')
let flowGraphChart: echarts.ECharts | null = null
const jaegerConfigured = ref(false)
const jaegerError = ref('')
const jaegerUiBase = ref('')
const jaegerServices = ref<string[]>([])
const jaegerService = ref('')
const jaegerDepItems = ref<{ parent: string; child: string; call_count: number }[]>([])

const traceRowsFiltered = computed(() => {
  const q = (traceIdFilter.value || '').trim().toLowerCase()
  const all = allTraceRows.value
  if (!q) return all
  return all.filter((r: { trace_id?: string }) => String(r.trace_id || '').toLowerCase().includes(q))
})

const traceRowsPaged = computed(() => {
  const list = traceRowsFiltered.value
  const start = (tracePage.value - 1) * tracePageSize.value
  return list.slice(start, start + tracePageSize.value)
})

const pathsRowFlash = ref<Record<string, boolean>>({})
const slowRowFlash = ref<Record<string, boolean>>({})
const ipRowFlash = ref<Record<string, boolean>>({})
const traceRowFlash = ref<Record<string, boolean>>({})

const prevTableSigs = {
  paths: {} as Record<string, string>,
  slow: {} as Record<string, string>,
  ip: {} as Record<string, string>,
  trace: {} as Record<string, string>,
}
let tableFlashClearTimer: number | null = null

const cfgForm = reactive({
  enabled: true,
  access_log_mode: 'file' as 'file' | 'redis',
  access_log_path: '',
  error_log_path: '',
  log_format: 'json',
  max_tail_bytes: 5242880,
  redis_log_key: 'traffic:access:lines',
  redis_max_lines: 0,
  dashboard_fetch_max_lines: 0,
  redis_env_configured: false,
  clickhouse_configured: false,
  time_based_rollup_enforced: false,
  jaeger_query_configured: false,
  edge_ingest_path: '/api/edge/logs',
  edge_token_env: 'SHARK_EDGE_TOKEN',
  log_sources: [] as TrafficLogSourceRow[],
  geoip_db_path: '',
  use_inspection_prometheus: true,
  prometheus_url_override: '',
  blackbox_promql: '',
})

const kpiRefs: Record<string, HTMLElement | null> = {}
function setKpiRef(key: string, el: unknown) {
  kpiRefs[key] = (el as HTMLElement) || null
}

const chartQps = ref<HTMLElement | null>(null)
const chartLat = ref<HTMLElement | null>(null)
const chartErr = ref<HTMLElement | null>(null)
const chartMap = ref<HTMLElement | null>(null)
const chartCountry = ref<HTMLElement | null>(null)
const chartPie = ref<HTMLElement | null>(null)

const kpiCharts: Record<string, echarts.ECharts | null> = {}
const charts: Record<string, echarts.ECharts | null> = {}
let pollId: number | null = null
let worldGeoJsonCache: unknown | null = null

type MainChartKey = 'qps' | 'lat' | 'err' | 'map' | 'country' | 'pie'

function chartDisposed(c: echarts.ECharts | null | undefined): boolean {
  return !c || !!(c as { isDisposed?: () => boolean }).isDisposed?.()
}

function disposeMainChartsOnly() {
  Object.keys(charts).forEach((k) => {
    disposeChart(charts[k])
    charts[k] = null
  })
}

function getOrInitMain(el: HTMLElement | null, key: MainChartKey): echarts.ECharts | null {
  if (!el) return null
  let c = charts[key]
  if (!chartDisposed(c)) return c as echarts.ECharts
  c = echarts.init(el, 'shark-traffic')
  charts[key] = c
  return c
}

async function ensureWorldGeoJson(): Promise<unknown> {
  if (worldGeoJsonCache == null) {
    worldGeoJsonCache = await loadWorldGeoJson()
  }
  return worldGeoJsonCache
}

const refreshLabel = computed(() => (pollSec.value > 0 ? `${pollSec.value}s 自动刷新` : '手动刷新'))

const kpiCards = ref([
  { key: 'total', label: '窗口内请求', value: '—', source: '' },
  {
    key: 'qps',
    label: 'QPS (请求时间·近60s)',
    value: '—',
    source: '按日志内请求时刻，非推送时刻',
  },
  { key: 'lat', label: '平均响应', value: '—', source: '' },
  { key: 'err', label: '错误率', value: '—', source: '' },
  { key: 'up', label: '可用性', value: '—', source: '' },
])

function disposeChart(c?: echarts.ECharts | null) {
  if (c) {
    c.dispose()
  }
}

function disposeAllMain() {
  Object.keys(charts).forEach((k) => {
    disposeChart(charts[k])
    charts[k] = null
  })
  Object.keys(kpiCharts).forEach((k) => {
    disposeChart(kpiCharts[k])
    kpiCharts[k] = null
  })
}

function sparkOption(series: number[][], color: string, animMs = 280) {
  const xs = series.map((_, i) => i)
  const ys = series.map((x) => x[1])
  const areaColorMap: Record<string, string> = {
    'rgb(0,191,255)': 'rgba(0,191,255,0.12)',
    'rgb(61,165,255)': 'rgba(61,165,255,0.12)',
    'rgb(94,200,255)': 'rgba(94,200,255,0.12)',
    'rgb(47,127,209)': 'rgba(47,127,209,0.12)',
    'rgb(76,201,240)': 'rgba(76,201,240,0.12)',
  }
  return {
    backgroundColor: 'transparent',
    animationDuration: animMs,
    grid: { left: 2, right: 2, top: 2, bottom: 2 },
    xAxis: { type: 'category', show: false, data: xs },
    yAxis: { type: 'value', show: false, min: 'dataMin' },
    series: [
      {
        type: 'line',
        data: ys,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: areaColorMap[color] || 'rgba(0,191,255,0.12)' },
            { offset: 1, color: 'rgba(0,191,255,0)' },
          ]),
        },
      },
    ],
  }
}

const axisTooltip = {
  trigger: 'axis',
  backgroundColor: 'rgba(15, 23, 42, 0.94)',
  borderColor: '#cbd5e1',
  borderWidth: 1,
  textStyle: { color: '#f8fafc', fontSize: 12 },
  extraCssText: 'box-shadow:none;border-radius:10px;padding:10px 12px;',
}

const itemTooltip = {
  trigger: 'item',
  backgroundColor: 'rgba(15, 23, 42, 0.94)',
  borderColor: '#cbd5e1',
  borderWidth: 1,
  textStyle: { color: '#f8fafc', fontSize: 12 },
  extraCssText: 'box-shadow:none;border-radius:10px;padding:10px 12px;',
}

/** 地图 / 地球贴图走同源 public，避免内网无法访问 jsDelivr、echarts.apache.org */
function trafficMapAsset(relPath: string): string {
  const base = import.meta.env.BASE_URL || '/'
  const p = relPath.replace(/^\//, '')
  return base.endsWith('/') ? `${base}${p}` : `${base}/${p}`
}

async function loadWorldGeoJson(): Promise<unknown> {
  const localUrl = trafficMapAsset('traffic-maps/world.json')
  const tryFetch = async (url: string) => {
    const res = await fetch(url, { credentials: 'same-origin' })
    if (!res.ok) throw new Error(String(res.status))
    return res.json()
  }
  try {
    return await tryFetch(localUrl)
  } catch {
    /* 构建遗漏或旧部署：再试公网镜像（部分环境仍不可达） */
    const mirror =
      'https://raw.githubusercontent.com/apache/echarts/master/test/data/map/json/world.json'
    return tryFetch(mirror)
  }
}

function lineSeries(
  name: string,
  data: number[][],
  color: string,
  extra: Record<string, any> = {},
  animMs = 320,
) {
  return {
    name,
    type: 'line',
    smooth: true,
    showSymbol: false,
    symbol: 'none',
    data,
    lineStyle: { color, width: 2 },
    emphasis: { focus: 'series' },
    animationDuration: animMs,
    ...extra,
  }
}

function updateKpiCharts(soft = false) {
  const q = overview.value?.series?.qps || []
  const e = overview.value?.series?.error_rate || []
  const rq = timeseries.value?.requests || []
  const keys = ['total', 'qps', 'lat', 'err', 'up']
  const dataMap: Record<string, number[][]> = {
    total: rq.length ? rq : q,
    qps: q,
    lat: q,
    err: e.length ? e : q,
    up: q,
  }
  const colors = ['rgb(59,130,246)', 'rgb(96,165,250)', 'rgb(147,197,253)', 'rgb(56,189,248)', 'rgb(37,99,235)']
  const anim = soft ? 100 : 280
  keys.forEach((key, i) => {
    const el = kpiRefs[key]
    if (!el) return
    let c = kpiCharts[key]
    if (!c) {
      c = echarts.init(el, 'shark-traffic')
      kpiCharts[key] = c
    }
    c.setOption(sparkOption(dataMap[key] || [], colors[i % colors.length], anim), true)
  })
}

async function ensureMapChart(soft: boolean, anim: number) {
  if (!chartMap.value) return
  const c = getOrInitMain(chartMap.value, 'map')
  if (!c) return
  const heatData = geoItems.value
    .filter((g) => g.lat && g.lng && g.requests > 0)
    .map((g) => [g.lng, g.lat, g.requests])
  const reqVals = geoItems.value.map((g) => Number(g.requests) || 0)
  const vmax = reqVals.length ? Math.max(1, ...reqVals) : 1
  const mapOption = {
    animationDuration: anim,
    tooltip: {
      ...itemTooltip,
      formatter: (p: any) => {
        const v = p.value as number[]
        if (Array.isArray(v) && v.length >= 3) {
          return `经度 ${v[0]?.toFixed?.(2) ?? v[0]} 纬度 ${v[1]?.toFixed?.(2) ?? v[1]}<br/>请求量: ${v[2]}`
        }
        return `${p.name || ''}<br/>${p.value ?? ''}`
      },
    },
    geo: {
      map: 'world',
      roam: true,
      itemStyle: { areaColor: '#e2e8f0', borderColor: '#cbd5e1', borderWidth: 0.8 },
      emphasis: { itemStyle: { areaColor: '#bfdbfe' }, label: { color: '#1e293b' } },
    },
    visualMap: {
      min: 0,
      max: vmax,
      calculable: true,
      inRange: { color: ['#0c4a6e', '#0369a1', '#0ea5e9', '#38bdf8', '#fbbf24', '#f97316'] },
      textStyle: { color: '#64748b' },
      left: 8,
      bottom: 20,
    },
    series: [
      {
        name: '请求热度',
        type: 'heatmap',
        coordinateSystem: 'geo',
        data: heatData,
        pointSize: 12,
        blurSize: 18,
        emphasis: { itemStyle: { shadowBlur: 12 } },
      } as any,
    ],
  }
  try {
    const worldJson = await ensureWorldGeoJson()
    try {
      echarts.registerMap('world', worldJson as any)
    } catch {
      /* already registered */
    }
    c.setOption(mapOption, true)
  } catch {
    c.setOption(
      {
        title: {
          text: '地图数据加载失败（请确认已部署 frontend/public/traffic-maps/world.json）',
          left: 'center',
          top: 'center',
          textStyle: { color: '#64748b', fontSize: 11 },
        },
      },
      true,
    )
  }
}

/** 热力地图依赖 GeoJSON，放到 idle 再画，避免阻塞首屏与其它图表。 */
function scheduleMapRender(soft: boolean, anim: number) {
  const run = () => {
    void ensureMapChart(soft, anim)
  }
  const ric = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number })
    .requestIdleCallback
  if (typeof ric === 'function') {
    ric(run, { timeout: 500 })
  } else {
    window.setTimeout(run, 80)
  }
}

async function renderMainCharts(opts?: { soft?: boolean }) {
  const soft = opts?.soft === true
  const anim = soft ? 100 : 220
  if (!soft) {
    disposeMainChartsOnly()
  }

  const ts = timeseries.value
  const qpsC = getOrInitMain(chartQps.value, 'qps')
  if (qpsC) {
    qpsC.setOption(
      {
        animationDuration: anim,
        tooltip: axisTooltip,
        legend: { top: 8, left: 'center', textStyle: { color: '#64748b' }, data: ['QPS', 'Requests/min'] },
        grid: { left: 48, right: 20, top: 48, bottom: 28 },
        xAxis: { type: 'time' },
        yAxis: [{ type: 'value', name: 'QPS' }, { type: 'value', name: 'Req', splitLine: { show: false } }],
        series: [
          lineSeries(
            'QPS',
            ts.qps || [],
            '#3b82f6',
            {
              areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: 'rgba(59,130,246,0.12)' },
                  { offset: 1, color: 'rgba(59,130,246,0.02)' },
                ]),
              },
            },
            anim,
          ),
          {
            name: 'Requests/min',
            type: 'bar',
            yAxisIndex: 1,
            barWidth: 10,
            data: (ts.requests || []).map((x: number[]) => [x[0], x[1] / Math.max((ts.bucket_sec || 60) / 60, 1)]),
            itemStyle: { color: 'rgba(96,165,250,0.45)', borderRadius: [3, 3, 0, 0] },
            animationDuration: anim,
          },
        ],
      },
      true,
    )
  }

  const lat = ts.latency || {}
  const latC = getOrInitMain(chartLat.value, 'lat')
  if (latC) {
    latC.setOption(
      {
        animationDuration: anim,
        tooltip: {
          ...axisTooltip,
          valueFormatter: (v: number) => `${v} ms`,
        },
        legend: { top: 8, left: 'center', textStyle: { color: '#64748b' } },
        grid: { left: 48, right: 20, top: 48, bottom: 28 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: 'ms' },
        series: [
          lineSeries('P50', lat.p50 || [], '#93c5fd', {}, anim),
          lineSeries('P95', lat.p95 || [], '#60a5fa', {}, anim),
          lineSeries('P99', lat.p99 || [], '#3b82f6', {}, anim),
        ],
      },
      true,
    )
  }

  const st = ts.status_stack || {}
  const errC = getOrInitMain(chartErr.value, 'err')
  if (errC) {
    errC.setOption(
      {
        animationDuration: anim,
        tooltip: axisTooltip,
        legend: { top: 8, left: 'center', textStyle: { color: '#64748b' } },
        grid: { left: 48, right: 20, top: 48, bottom: 28 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value' },
        series: [
          {
            name: '2xx',
            type: 'line',
            stack: 's',
            smooth: true,
            showSymbol: false,
            animationDuration: anim,
            areaStyle: { color: 'rgba(147,197,253,0.18)' },
            lineStyle: { width: 0, color: '#93c5fd' },
            data: st['2xx'] || [],
          },
          {
            name: '4xx',
            type: 'line',
            stack: 's',
            smooth: true,
            showSymbol: false,
            animationDuration: anim,
            areaStyle: { color: 'rgba(96,165,250,0.18)' },
            lineStyle: { width: 0, color: '#60a5fa' },
            data: st['4xx'] || [],
          },
          {
            name: '5xx',
            type: 'line',
            stack: 's',
            smooth: true,
            showSymbol: false,
            animationDuration: anim,
            areaStyle: { color: 'rgba(59,130,246,0.22)' },
            lineStyle: { width: 0, color: '#3b82f6' },
            data: st['5xx'] || [],
          },
        ],
      },
      true,
    )
  }

  const items = [...geoItems.value].sort((a, b) => b.requests - a.requests).slice(0, 10)
  const countryC = getOrInitMain(chartCountry.value, 'country')
  if (countryC) {
    countryC.setOption(
      {
        animationDuration: anim,
        tooltip: itemTooltip,
        grid: { left: 92, right: 16, top: 12, bottom: 12 },
        xAxis: { type: 'value' },
        yAxis: { type: 'category', data: items.map((i) => i.name || i.code).reverse(), axisLabel: { color: '#475569' } },
        series: [
          {
            type: 'bar',
            data: items.map((i) => i.requests).reverse(),
            barWidth: 12,
            animationDuration: anim,
            itemStyle: {
              borderRadius: [0, 6, 6, 0],
              color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: 'rgba(96,165,250,0.24)' },
                { offset: 1, color: '#3b82f6' },
              ]),
            },
          },
        ],
      },
      true,
    )
  }

  const pieC = getOrInitMain(chartPie.value, 'pie')
  if (pieC) {
    pieC.setOption(
      {
        animationDuration: anim,
        tooltip: itemTooltip,
        legend: { bottom: 8, left: 'center', textStyle: { color: '#64748b', fontSize: 12 } },
        series: [
          {
            type: 'pie',
            radius: ['52%', '74%'],
            center: ['50%', '44%'],
            itemStyle: { borderRadius: 4, borderColor: '#ffffff', borderWidth: 2 },
            label: { color: '#475569', fontSize: 12 },
            labelLine: { lineStyle: { color: '#94a3b8' } },
            animationDuration: anim,
            data: statusPie.value.length ? statusPie.value : [{ name: '无数据', value: 1 }],
          },
        ],
      },
      true,
    )
  }

  scheduleMapRender(soft, anim)
}

function updateKpiText() {
  const o = overview.value || {}
  kpiCards.value = [
    { key: 'total', label: '窗口内请求', value: fmtNum(o.total_requests), source: '' },
    {
      key: 'qps',
      label: 'QPS (请求时间·近60s)',
      value: fmtNum(o.qps),
      source: '按日志内请求时刻，非推送时刻',
    },
    { key: 'lat', label: '平均响应', value: `${o.latency_avg_ms ?? 0} ms`, source: '' },
    { key: 'err', label: '错误率', value: `${o.error_rate_pct ?? 0}%`, source: '' },
    {
      key: 'up',
      label: '可用性',
      value: o.availability_pct != null ? `${o.availability_pct}%` : '—',
      source: '',
    },
  ]
}

function fmtNum(n: unknown) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function currentSourceParam(): string | undefined {
  const s = trafficSource.value
  if (!s || s === 'all') return 'all'
  return s
}

async function refreshSourceOptions() {
  try {
    const data = await trafficApi.sources()
    const items = data.items || []
    sourceOptions.value = items
    const ids = new Set(items.map((i) => i.id))
    if (!trafficSource.value || !ids.has(trafficSource.value)) {
      trafficSource.value = items[0]?.id || 'all'
    }
  } catch {
    sourceOptions.value = []
  }
}

function addLogSource() {
  cfgForm.log_sources.push({ id: '', label: '', file_path: '', redis_key: '', log_format: '' })
}

function removeLogSource(index: number) {
  cfgForm.log_sources.splice(index, 1)
}

function rowKeyPath(row: any) {
  return String(row?.path ?? '')
}

function rowKeyIp(row: any) {
  return String(row?.ip ?? '')
}

function rowKeyTrace(row: any) {
  const id = row?.trace_id
  if (id != null && String(id)) return String(id)
  return `trace-${row?.root_service ?? 'x'}-${row?.duration_ms ?? 0}-${row?.status ?? ''}`
}

function sigPathRow(row: any) {
  return `${row.requests}|${row.p95_ms}|${row.errors_5xx}|${row.share_pct}`
}

function sigSlowRow(row: any) {
  return `${row.p95_ms}|${row.p99_ms}|${row.requests ?? ''}`
}

function sigIpRow(row: any) {
  return `${row.requests}|${row.country ?? ''}`
}

function sigTraceRow(row: any) {
  return `${row.duration_ms}|${row.status}|${row.root_service ?? ''}|${row.started_at ?? ''}|${row.span_count ?? ''}`
}

function diffRowFlash(
  rows: any[],
  prev: Record<string, string>,
  sigFn: (row: any) => string,
  keyFn: (row: any) => string,
): Record<string, boolean> {
  const out: Record<string, boolean> = {}
  for (const row of rows) {
    const k = keyFn(row)
    if (!k) continue
    const s = sigFn(row)
    if (prev[k] !== undefined && prev[k] !== s) {
      out[k] = true
    }
  }
  return out
}

function syncTablePrevSigs() {
  const p: Record<string, string> = {}
  for (const row of pathsRows.value) {
    const k = rowKeyPath(row)
    if (k) p[k] = sigPathRow(row)
  }
  prevTableSigs.paths = p

  const s: Record<string, string> = {}
  for (const row of slowRows.value) {
    const k = rowKeyPath(row)
    if (k) s[k] = sigSlowRow(row)
  }
  prevTableSigs.slow = s

  const i: Record<string, string> = {}
  for (const row of ipRows.value) {
    const k = rowKeyIp(row)
    if (k) i[k] = sigIpRow(row)
  }
  prevTableSigs.ip = i

  const t: Record<string, string> = {}
  for (const row of allTraceRows.value) {
    const k = rowKeyTrace(row)
    if (k) t[k] = sigTraceRow(row)
  }
  prevTableSigs.trace = t
}

function clearTableRowFlash() {
  pathsRowFlash.value = {}
  slowRowFlash.value = {}
  ipRowFlash.value = {}
  traceRowFlash.value = {}
}

function applyRowFlashAfterLoad(silent: boolean) {
  if (tableFlashClearTimer != null) {
    clearTimeout(tableFlashClearTimer)
    tableFlashClearTimer = null
  }

  if (!silent) {
    clearTableRowFlash()
    syncTablePrevSigs()
    return
  }

  pathsRowFlash.value = diffRowFlash(pathsRows.value, prevTableSigs.paths, sigPathRow, rowKeyPath)
  slowRowFlash.value = diffRowFlash(slowRows.value, prevTableSigs.slow, sigSlowRow, rowKeyPath)
  ipRowFlash.value = diffRowFlash(ipRows.value, prevTableSigs.ip, sigIpRow, rowKeyIp)
  traceRowFlash.value = diffRowFlash(allTraceRows.value, prevTableSigs.trace, sigTraceRow, rowKeyTrace)

  syncTablePrevSigs()

  tableFlashClearTimer = window.setTimeout(() => {
    clearTableRowFlash()
    tableFlashClearTimer = null
  }, 1400)
}

function pathsTableRowClass({ row }: { row: any }) {
  const k = rowKeyPath(row)
  if (k && pathsRowFlash.value[k]) return 'traffic-trow traffic-trow--updated'
  return 'traffic-trow'
}

function slowTableRowClass({ row }: { row: any }) {
  const k = rowKeyPath(row)
  if (k && slowRowFlash.value[k]) return 'traffic-trow traffic-trow--updated'
  return 'traffic-trow'
}

function ipTableRowClass({ row }: { row: any }) {
  const k = rowKeyIp(row)
  if (k && ipRowFlash.value[k]) return 'traffic-trow traffic-trow--updated'
  return 'traffic-trow'
}

function traceTableRowClass({ row }: { row: any }) {
  const k = rowKeyTrace(row)
  if (k && traceRowFlash.value[k]) return 'traffic-trow traffic-trow--updated'
  return 'traffic-trow'
}

function traceTableRowClassWithSelected(d: { row: any }) {
  const base = traceTableRowClass(d)
  const id = d.row?.trace_id
  if (id != null && String(id) && String(id) === String(selectedTraceId.value)) {
    return `${base} traffic-trow--trace-active`.replace(/\s+/g, ' ').trim()
  }
  return base
}

function onRangePresetChange() {
  if (range.value === 'custom' && !customTimeRange.value) {
    const e = new Date()
    customTimeRange.value = [new Date(e.getTime() - 86400000), e]
  }
  void loadAll(false)
}

function onCustomRangePicked() {
  if (range.value === 'custom') void loadAll(false)
}

function disposeFlowGraph() {
  if (flowGraphChart) {
    flowGraphChart.dispose()
    flowGraphChart = null
  }
}

const TRACE_TREE_COLORS = ['#2563eb', '#059669', '#c2410c', '#0891b2', '#7c3aed', '#64748b']

type TraceTreeNode = {
  name: string
  value?: number
  category?: number
  op_detail?: string
  children?: TraceTreeNode[]
}

function itemStyleForTraceTree(n: TraceTreeNode): Record<string, unknown> {
  const c = n.category != null ? TRACE_TREE_COLORS[Math.min(5, Math.max(0, n.category))] : TRACE_TREE_COLORS[5]
  const { children, ...rest } = n
  const out: Record<string, unknown> = {
    ...rest,
    itemStyle: { color: c, borderColor: c, borderWidth: 1 },
  }
  if (children && children.length) {
    out.children = children.map((ch) => itemStyleForTraceTree(ch))
  }
  return out
}

type TraceGraphPayload = {
  tree?: { data: TraceTreeNode[] }
  nodes: { id: string; name: string; category: number; duration_ms: number; span_count?: number }[]
  links: { source: string; target: string; value?: number; label?: string }[]
  categories: { name: string }[]
  truncated?: boolean
}

function renderTraceTree(graph: TraceGraphPayload) {
  const el = flowGraphEl.value
  if (!el) {
    flowGraphError.value = '图表容器未就绪'
    return
  }
  const raw = graph.tree?.data
  if (!raw || !raw.length) {
    flowGraphError.value = '该 trace 无 span 数据'
    return
  }
  const data = raw.map((n) => itemStyleForTraceTree(n)) as unknown[]
  el.style.minHeight = 'min(80vh, 640px)'
  el.style.maxHeight = '80vh'
  el.style.minWidth = '100%'
  el.style.overflow = 'auto'
  const c = echarts.init(el, 'shark-traffic')
  const cats = graph.categories || [
    { name: 'http' },
    { name: 'db' },
    { name: 'redis' },
    { name: 'mongo' },
    { name: 'mq' },
    { name: 'other' },
  ]
  c.setOption(
    {
      animationDuration: 180,
      tooltip: {
        trigger: 'item',
        confine: true,
        extraCssText: 'max-width:min(90vw,480px);white-space:pre-wrap;',
        formatter: (p: { data?: { op_detail?: string; name?: string; value?: number } }) => {
          const d = p.data as { op_detail?: string; name?: string; value?: number } | undefined
          const t = d?.op_detail
          const head = String(d?.name || '')
          if (t) {
            const body = String(t)
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/\n/g, '<br/>')
            return (
              '<div style="font-weight:600;margin-bottom:6px">' +
              head.replace(/</g, '&lt;') +
              '</div><div style="opacity:0.92;font-size:12px;line-height:1.45">' +
              body +
              '</div>'
            )
          }
          return head.replace(/</g, '&lt;')
        },
      },
      legend: { data: cats.map((x) => x.name), bottom: 2, type: 'scroll' },
      series: [
        {
          type: 'tree',
          data,
          top: 28,
          left: 24,
          right: 24,
          bottom: 32,
          layout: 'orthogonal',
          // TB: 子调用在下方、兄弟向左右排开，比 LR+竖向长串叠字可读得多
          orient: 'TB',
          symbol: 'emptyCircle',
          symbolSize: 6,
          initialTreeDepth: 2,
          expandAndCollapse: true,
          roam: true,
          nodeScaleRatio: 0.35,
          edgeShape: 'polyline',
          lineStyle: { color: '#94a3b8', width: 1.05 },
          label: {
            position: 'top',
            distance: 6,
            fontSize: 10,
            lineHeight: 13,
            color: '#1e293b',
            width: 320,
            overflow: 'truncate',
            rotate: 0,
          },
          leaves: {
            label: { position: 'right', align: 'left', fontSize: 10 },
          },
          emphasis: { focus: 'descendant' },
        },
      ],
    },
    { notMerge: true }
  )
  flowGraphChart = c
  c.resize()
  setTimeout(() => c.resize(), 100)
  window.addEventListener('resize', onFlowGraphResize)
}

function renderTraceForceGraph(graph: TraceGraphPayload) {
  const el = flowGraphEl.value
  if (!el) {
    flowGraphError.value = '图表容器未就绪'
    return
  }
  if (!graph?.nodes?.length) {
    flowGraphError.value = '该 trace 无 span 数据'
    return
  }
  el.style.minHeight = '420px'
  el.style.maxHeight = '72vh'
  const c = echarts.init(el, 'shark-traffic')
  const cats = graph.categories || [
    { name: 'http' },
    { name: 'db' },
    { name: 'redis' },
    { name: 'mongo' },
    { name: 'mq' },
    { name: 'other' },
  ]
  c.setOption({
    animationDuration: 200,
    tooltip: { trigger: 'item' },
    legend: { data: cats.map((x) => x.name), bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'graph',
        layout: 'force',
        categories: cats,
        data: graph.nodes.map((n) => ({
          id: n.id,
          name: n.name,
          category: n.category,
          value: n.duration_ms,
          symbolSize: 16 + Math.min(28, Math.log1p(Number(n.duration_ms) || 0) * 4),
        })),
        links: (graph.links || []).map((l) => ({
          source: l.source,
          target: l.target,
          value: l.value,
          lineStyle: {
            width: 1.2 + Math.min(4, Math.log1p(Number(l.value) || 0) / 2),
            curveness: 0.12,
          },
          label: {
            show: (graph.nodes?.length || 0) < 35,
            fontSize: 9,
            color: '#64748b',
            formatter: l.label || '',
          },
        })),
        label: { show: true, fontSize: 10, lineHeight: 13, color: '#334155' },
        lineStyle: { color: 'source', curveness: 0.12, opacity: 0.75 },
        emphasis: { focus: 'adjacency', scale: true },
        force: {
          repulsion: 320,
          edgeLength: [64, 220],
          gravity: 0.12,
          friction: 0.62,
          layoutAnimation: false,
        },
        roam: true,
        draggable: true,
      },
    ],
  })
  flowGraphChart = c
  c.resize()
  setTimeout(() => c.resize(), 100)
  window.addEventListener('resize', onFlowGraphResize)
}

function renderFlowGraph(graph: TraceGraphPayload) {
  const el = flowGraphEl.value
  if (!el) {
    flowGraphError.value = '图表容器未就绪'
    return
  }
  const hasTree = graph.tree && Array.isArray(graph.tree.data) && graph.tree.data.length > 0
  if (!hasTree && !graph?.nodes?.length) {
    flowGraphError.value = '该 trace 无 span 数据'
    return
  }
  disposeFlowGraph()
  if (hasTree) {
    renderTraceTree(graph)
  } else {
    renderTraceForceGraph(graph)
  }
}

function onFlowGraphResize() {
  flowGraphChart?.resize()
}

async function onJaegerServiceChange() {
  await refreshJaegerTraces()
}

function clearTraceSelection() {
  selectedTraceId.value = ''
  flowGraphError.value = ''
  window.removeEventListener('resize', onFlowGraphResize)
  disposeFlowGraph()
}

async function loadTraceForSelection(tid: string) {
  if (!tid) return
  selectedTraceId.value = tid
  flowGraphError.value = ''
  flowGraphLoading.value = true
  window.removeEventListener('resize', onFlowGraphResize)
  disposeFlowGraph()
  try {
    const res = (await trafficApi.jaegerTraceDetail(tid)) as {
      ok?: boolean
      error?: string
      graph?: { tree?: { data: unknown[] }; nodes: any[]; links: any[]; categories: any[]; truncated?: boolean }
    }
    if (res == null || res.ok === false) {
      flowGraphError.value = res?.error || '加载失败'
      return
    }
    const g = res.graph
    const hasTree = g?.tree && Array.isArray(g.tree.data) && g.tree.data.length > 0
    if (!g || (!hasTree && !g?.nodes?.length)) {
      flowGraphError.value = '该 trace 无 span 数据'
      return
    }
    await nextTick()
    renderFlowGraph(res.graph)
  } catch (e: unknown) {
    const ax = e as { response?: { data?: { error?: string } }; message?: string }
    flowGraphError.value = ax?.response?.data?.error || ax?.message || '请求失败'
  } finally {
    flowGraphLoading.value = false
  }
}

function onTraceTableRowClick(row: any) {
  if (row?.trace_id) void loadTraceForSelection(String(row.trace_id))
}

async function refreshJaegerTraces() {
  try {
    const r = range.value
    const p: { range?: string; start?: string; end?: string; service?: string; limit?: string } = {
      limit: '40',
    }
    if (jaegerService.value) p.service = jaegerService.value
    if (r === 'custom' && customTimeRange.value && customTimeRange.value.length === 2) {
      p.start = customTimeRange.value[0].toISOString()
      p.end = customTimeRange.value[1].toISOString()
    } else {
      p.range = r === 'custom' ? '1h' : r
    }
    const tr = (await trafficApi.jaegerTraces(p)) as {
      configured?: boolean
      error?: string | null
      traces?: any[]
      dependencies?: { items?: { parent: string; child: string; call_count: number }[] }
      services?: string[]
      service_used?: string
      jaeger_ui_base?: string
    }
    jaegerConfigured.value = !!tr.configured
    jaegerError.value = tr.configured && tr.error ? tr.error : ''
    jaegerUiBase.value = (tr.jaeger_ui_base || '').replace(/\/$/, '')
    const prevSel = selectedTraceId.value
    allTraceRows.value = tr.traces || []
    const stillHas =
      prevSel && allTraceRows.value.some((x: { trace_id?: string }) => String(x.trace_id) === String(prevSel))
    if (stillHas) {
      void loadTraceForSelection(String(prevSel))
    } else {
      clearTraceSelection()
    }
    tracePage.value = 1
    jaegerDepItems.value = (tr.dependencies && tr.dependencies.items) || []
    jaegerServices.value = tr.services || []
    if (tr.service_used && !String(jaegerService.value || '').trim()) {
      jaegerService.value = tr.service_used
    }
  } catch {
    jaegerError.value = '请求失败'
    allTraceRows.value = []
    jaegerDepItems.value = []
    clearTraceSelection()
  }
}

async function loadAll(silent = false) {
  if (!silent) loading.value = true
  else softRefreshing.value = true
  try {
    const r = range.value
    const src = currentSourceParam()
    let snapOpts: { start?: string; end?: string; fullData?: boolean } | undefined
    if (r === 'custom' && customTimeRange.value && customTimeRange.value.length === 2) {
      snapOpts = {
        start: customTimeRange.value[0].toISOString(),
        end: customTimeRange.value[1].toISOString(),
      }
      if (rawLogDetail.value) snapOpts.fullData = true
    } else if (rawLogDetail.value) {
      snapOpts = { fullData: true }
    }
    const snap = (await trafficApi.snapshot(
      r === 'custom' ? '24h' : r,
      src,
      snapOpts,
    )) as any
    if (mainTab.value === 'flow') await refreshJaegerTraces()
    const ov = snap.overview || {}
    overview.value = ov
    timeseries.value = snap.timeseries || {}
    geoItems.value = (snap.geo && snap.geo.items) || []
    pathsRows.value = (snap.top_paths && snap.top_paths.items) || []
    slowRows.value = (snap.top_slow && snap.top_slow.items) || []
    statusPie.value = (snap.top_status && snap.top_status.items) || []
    ipRows.value = (snap.top_ip && snap.top_ip.items) || []
    applyRowFlashAfterLoad(silent)
    updateKpiText()
    await nextTick()
    updateKpiCharts(silent)
    if (typeof requestAnimationFrame === 'function') {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            void renderMainCharts({ soft: silent }).then(() => resolve())
          })
        })
      })
    } else {
      await renderMainCharts({ soft: silent })
    }
  } catch {
    /* request interceptor */
  } finally {
    if (!silent) loading.value = false
    else softRefreshing.value = false
  }
}

async function onOpenTrafficConfig() {
  try {
    const c = (await trafficApi.getConfig()) as any
    const ls = Array.isArray(c.log_sources) ? c.log_sources : []
    cfgForm.log_sources.splice(
      0,
      cfgForm.log_sources.length,
      ...ls.map((row: Record<string, string>) => ({
        id: String(row.id || ''),
        label: String(row.label || ''),
        file_path: String(row.file_path || ''),
        redis_key: String(row.redis_key || ''),
        log_format: String(row.log_format || ''),
      }))
    )
    Object.assign(cfgForm, { ...c, log_sources: cfgForm.log_sources })
    configOpen.value = true
  } catch {
    ElMessage.error('读取配置失败')
  }
}

async function saveCfg() {
  try {
    const rows = cfgForm.log_sources.filter((x) => String(x.id || '').trim())
    const ids = rows.map((x) => String(x.id).trim())
    if (new Set(ids).size !== ids.length) {
      ElMessage.error('日志源 ID 不能重复')
      return
    }
    const {
      clickhouse_configured: _c,
      time_based_rollup_enforced: _t,
      jaeger_query_configured: _j,
      ...rest
    } = cfgForm
    await trafficApi.saveConfig({ ...rest, log_sources: rows })
    ElMessage.success('已保存')
    configOpen.value = false
    await refreshSourceOptions()
    loadAll()
  } catch {
    /* */
  }
}

function setupPoll() {
  if (pollId) clearInterval(pollId)
  if (pollSec.value > 0) {
    pollId = setInterval(() => {
      if (mainTab.value === 'trend') loadAll(true)
    }, pollSec.value * 1000)
  }
}

watch(pollSec, setupPoll)

watch(traceIdFilter, () => {
  tracePage.value = 1
})

watch(mainTab, (t) => {
  if (t === 'flow') void refreshJaegerTraces()
  if (t === 'trend') {
    void nextTick(() => onResize())
  }
})

onMounted(async () => {
  await refreshSourceOptions()
  loadAll()
  setupPoll()
  window.addEventListener('resize', onResize)
})

function onResize() {
  Object.values(charts).forEach((c) => c?.resize())
  Object.values(kpiCharts).forEach((c) => c?.resize())
}

onUnmounted(() => {
  window.removeEventListener('resize', onFlowGraphResize)
  disposeFlowGraph()
  if (pollId) clearInterval(pollId)
  if (tableFlashClearTimer != null) {
    clearTimeout(tableFlashClearTimer)
    tableFlashClearTimer = null
  }
  disposeAllMain()
  window.removeEventListener('resize', onResize)
})
</script>

<style scoped>
.traffic-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header,
.main-tabs,
.kpi-row,
.chart-row,
.bottom-row,
.flow-row {
  position: relative;
  z-index: 1;
}

.page-panel {
  background: #ffffff;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  box-shadow: none;
}
.page-panel:hover {
  border-color: #e2e8f0;
}


.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
}
.page-subtitle {
  margin: 4px 0 0;
  font-size: 14px;
  color: #64748b;
}
.custom-range-picker {
  width: 320px;
  margin-left: 4px;
}
.custom-range-picker :deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: none;
  border: 1px solid #dbe2ea;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.refresh-status {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}
.refresh-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #94a3b8;
}
.refresh-dot.active {
  background: #3b82f6;
  animation: dashboardPulse 1.6s ease-in-out infinite;
}
.refresh-status.syncing {
  border-color: #bfdbfe;
  background: #eff6ff;
}
.toolbar-btn {
  border-radius: 8px;
}
.raw-detail-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 4px;
}
.raw-detail-label {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}
.shadow-btn {
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}
.source-select :deep(.el-input__wrapper) {
  background: #ffffff;
  box-shadow: none;
  border: 1px solid #dbe2ea;
  color: #334155;
}
.log-src-table {
  width: 100%;
  margin-top: 8px;
}
.mt-8 {
  margin-top: 8px;
}
.poll-select :deep(.el-input__wrapper) {
  background: #ffffff;
  box-shadow: none;
  border: 1px solid #dbe2ea;
  color: #334155;
}
.range-group :deep(.el-radio-button__inner) {
  background: #ffffff;
  border-color: #dbe2ea;
  color: #64748b;
  box-shadow: none;
}
.range-group :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #fff;
}

.main-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.main-tabs :deep(.el-tabs__nav-wrap::after) {
  background: #e2e8f0;
}
.main-tabs :deep(.el-tabs__item) {
  color: #64748b;
  font-weight: 600;
}
.main-tabs :deep(.el-tabs__item.is-active) {
  color: #3b82f6;
}
.main-tabs :deep(.el-tabs__active-bar) {
  background: #3b82f6;
  height: 2px;
}

.warn-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
  font-size: 13px;
  color: #b45309;
  border-color: #fcd34d;
  background: #fffbeb;
}
.warn-banner code {
  font-size: 11px;
  color: #92400e;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1439px) {
  .kpi-row {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 1023px) {
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 767px) {
  .kpi-row {
    grid-template-columns: 1fr;
  }
}
.kpi-card {
  padding: 14px 16px;
  min-height: 132px;
}
.kpi-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.kpi-label {
  font-size: 12px;
  line-height: 16px;
  color: #64748b;
}
.kpi-value {
  margin: 10px 0 8px;
  color: #3b82f6;
  font-size: 30px;
  line-height: 1;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.kpi-src {
  font-size: 12px;
  line-height: 16px;
  color: #94a3b8;
}
.kpi-spark {
  width: 88px;
  height: 40px;
  flex-shrink: 0;
}

.err-detail-row {
  margin-bottom: 0;
}
.err-detail-panel {
  margin-bottom: 16px;
}
.err-detail-empty {
  font-size: 13px;
  color: #94a3b8;
  padding: 4px 0 2px;
}
.err-code-tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  line-height: 1.5;
}
.err-code-tag {
  margin: 0 !important;
}
.err-detail-alert {
  margin-bottom: 12px;
}
.err-detail-alert :deep(.el-alert__content) {
  font-size: 12px;
  color: #475569;
}
.err-detail-table {
  margin-top: 0;
}
.err-path-code {
  font-size: 12px;
  color: #334155;
  word-break: break-all;
}

.chart-wrap {
  padding: 12px 14px 10px;
  margin-bottom: 16px;
}
.chart-title {
  margin-bottom: 10px;
  color: #475569;
  font-size: 14px;
  font-weight: 600;
}
.echart {
  width: 100%;
  height: 260px;
}
.map-h {
  height: 260px;
}
.country-h {
  height: 240px;
}
.pie-h {
  height: 280px;
}

.jaeger-alert {
  margin-bottom: 16px;
}
.jaeger-alert :deep(.el-alert__content) {
  color: #475569;
}
.jaeger-alert :deep(.el-alert) {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}
.flow-placeholder {
  padding: 24px;
  min-height: 360px;
}
.ph-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}
.ph-desc {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 24px;
}
.ph-grid {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}
.ph-node {
  padding: 16px 24px;
  border-radius: 10px;
  border: 1px solid #dbe2ea;
  background: #f8fafc;
  color: #334155;
  font-weight: 600;
}
.ph-node.dim {
  opacity: 0.72;
}
.ph-edge {
  width: 40px;
  height: 2px;
  background: linear-gradient(90deg, transparent, #60a5fa, transparent);
}

.flow-deps-panel {
  min-height: 200px;
  padding: 12px 14px 16px;
  margin-bottom: 16px;
}
.dep-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.dep-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-size: 13px;
  color: #334155;
}
.dep-node {
  font-weight: 600;
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dep-arrow {
  margin: 0 8px;
  color: #94a3b8;
  flex-shrink: 0;
}
.link-trace {
  color: #2563eb;
  text-decoration: none;
  word-break: break-all;
}
.link-trace:hover {
  text-decoration: underline;
}
.flow-jaeger-link {
  font-size: 13px;
  margin-bottom: 8px;
}
.flow-jaeger-link a {
  color: #2563eb;
}
.flow-graph-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.flow-graph-echart {
  width: 100%;
  min-height: 420px;
  max-height: 80vh;
  overflow: auto;
}
.flow-graph-err {
  color: #b45309;
}
.trace-pager {
  margin-top: 10px;
  justify-content: flex-end;
}
.traffic-trace-table :deep(tbody tr) {
  cursor: pointer;
}
.traffic-trace-table :deep(tr.traffic-trow--trace-active td.el-table__cell) {
  background: rgba(59, 130, 246, 0.1) !important;
  box-shadow: inset 3px 0 0 0 #3b82f6;
}
.trace-id-cell {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #1e40af;
}
.mb-8 {
  margin-bottom: 8px;
}
.mt-8 {
  margin-top: 8px;
}

.dark-table {
  --el-table-bg-color: #ffffff;
  --el-table-tr-bg-color: #ffffff;
  --el-table-row-hover-bg-color: #f8fafc;
  --el-table-header-bg-color: #f8fafc;
  --el-table-text-color: #334155;
  --el-table-header-text-color: #64748b;
  --el-table-border-color: #f1f5f9;
}
.dark-table :deep(.el-table__inner-wrapper::before) {
  background-color: #f1f5f9;
}
.dark-table :deep(th.el-table__cell),
.dark-table :deep(td.el-table__cell) {
  background: transparent;
}

.traffic-data-table :deep(tr.traffic-trow td.el-table__cell) {
  transition:
    background-color 0.42s ease,
    box-shadow 0.42s ease;
}
.traffic-data-table :deep(tr.traffic-trow--updated td.el-table__cell) {
  background-color: rgba(59, 130, 246, 0.08) !important;
  box-shadow: inset 3px 0 0 0 #3b82f6;
}

@keyframes dashboardPulse {
  0%, 100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}
</style>

<style>
.traffic-dialog .el-dialog {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: none;
}
.traffic-dialog .el-dialog__title {
  color: #1e293b;
}
.traffic-dialog .el-form-item__label,
.traffic-dialog .el-input__inner,
.traffic-dialog .el-select__placeholder,
.traffic-dialog .el-dialog__body {
  color: #475569;
}
.traffic-dialog .el-input__wrapper,
.traffic-dialog .el-select__wrapper,
.traffic-dialog .el-textarea__inner {
  background: #ffffff;
  box-shadow: none;
}
.traffic-dialog .el-textarea__inner,
.traffic-dialog .el-input__wrapper,
.traffic-dialog .el-select__wrapper {
  border: 1px solid #dbe2ea;
}
.traffic-dialog .form-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
.traffic-dialog .form-hint code {
  font-size: 11px;
  padding: 1px 4px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 4px;
}
.traffic-dialog .ml-6 {
  margin-left: 6px;
  vertical-align: middle;
}
</style>
