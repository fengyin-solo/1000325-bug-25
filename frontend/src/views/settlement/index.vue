<template>
  <section class="page" data-module="settlement">
    <header class="page-head">
      <div>
        <h2>电量结算管理</h2>
        <p class="page-desc">维护结算单，围绕结算单号、结算对象、结算周期、上网电量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记结算单</button>
        <button class="btn" type="button" @click="exportRows">导出电量结算清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号</span>
        <input v-model="filters.keyword" placeholder="按结算单号检索" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in pageRows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button
              v-if="column === '结算单号'"
              class="link"
              type="button"
              @click="openDetail(row)"
            >
              {{ formatCell(column, row[column]) }}
            </button>
            <template v-else>{{ formatCell(column, row[column]) }}</template>
          </td>
          <td class="row-actions">
            <template v-if="allowedActions(row).length">
              <button
                v-for="action in allowedActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">已锁定</span>
          </td>
        </tr>
        <tr v-if="!pageRows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无电量结算数据，可先登记结算单</td>
        </tr>
        <tr v-if="pageRows.length">
          <td :colspan="amountColumnIndex">本页合计</td>
          <td>{{ formatMoney(pageTotals.payable) }}</td>
          <td>{{ formatMoney(pageTotals.paid) }}</td>
          <td :colspan="2"></td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电量结算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>结算单明细 · {{ detail['结算单号'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in detailColumns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ formatCell(column, detail[column]) }}</dd>
          </template>
          <dt>状态锁定</dt>
          <dd>{{ isLocked(detail) ? '已付清，周期与金额锁定不可改' : '流转中' }}</dd>
        </dl>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null>
type Cell = Row[keyof Row]

const ENDPOINT = '/api/settlement'
const columns = ['结算单号', '结算对象', '结算周期', '上网电量', '电价标准', '应结金额', '已付金额', '结算状态']
const detailColumns = ['结算单号', '结算对象', '结算周期', '上网电量', '电价标准', '应结金额', '已付金额', '结算状态']
const statuses = ['待核对', '核对中', '已确认', '已付清', '有争议']
const amountColumnIndex = columns.indexOf('应结金额')

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const detail = ref<Row | null>(null)
const filters = ref<{ keyword: string; status: string }>({ keyword: '', status: '' })

const pageRows = computed(() => rows.value)

const pageTotals = computed(() =>
  pageRows.value.reduce(
    (acc: { payable: number; paid: number }, row) => {
      acc.payable += toNumber(row['应结金额'])
      acc.paid += toNumber(row['已付金额'])
      return acc
    },
    { payable: 0, paid: 0 },
  ),
)

const stats = computed(() => {
  const pendingCount = rows.value.filter((row) => row['结算状态'] === '待核对').length
  const monthlyAmount = rows.value
    .filter((row) => row['结算状态'] === '已付清')
    .reduce((sum, row) => sum + toNumber(row['已付金额']), 0)
  const disputeCount = rows.value.filter((row) => row['结算状态'] === '有争议').length
  return [
    { label: '待核对结算单', value: pendingCount },
    { label: '已付清金额合计', value: formatMoney(monthlyAmount) },
    { label: '争议单数', value: disputeCount },
  ]
})

function toNumber(value: Cell): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function formatMoney(value: number): string {
  return `¥${value.toFixed(2)}`
}

function formatCell(column: string, value: Cell): string {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '应结金额' || column === '已付金额') return formatMoney(toNumber(value))
  if (column === '电价标准') return String(toNumber(value).toFixed(2))
  return String(value)
}

function allowedActions(row: Row): string[] {
  const actions = row['可执行动作']
  return Array.isArray(actions) ? (actions as string[]) : []
}

function isLocked(row: Row): boolean {
  return row['结算状态'] === '已付清'
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '结算单登记入口尚未接入审批流'
}

async function openDetail(row: Row | null) {
  if (!row) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('结算单明细读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结算单明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.detail || payload?.message || '电量结算动作未生效，请稍后重试')
    }
    await reload()
    if (detail.value && String(detail.value.id) === String(row.id)) {
      void openDetail(payload.entry ?? row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('结算单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.muted-text {
  color: var(--text-muted, #9aa3af);
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal-card {
  width: min(560px, 92vw);
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.25);
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 16px;
  margin: 0;
}

.detail-grid dt {
  color: var(--text-muted, #9aa3af);
}

.detail-grid dd {
  margin: 0;
}
</style>
