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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted">已付清，不可改动</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无电量结算数据，可先登记结算单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电量结算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/settlement'
const columns = ["结算单号", "结算对象", "结算周期", "上网电量", "电价标准", "应结金额", "已付金额", "结算状态"]
// 每个状态允许执行的动作；已付清是终态，不再给任何操作入口
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待核对: ["发起核对", "标记争议"],
  核对中: ["确认结算", "标记争议"],
  已确认: ["确认结算", "标记争议"],
  有争议: ["恢复核对"],
  已付清: [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 统计卡片跟着当前列表数据走，保证合计与明细对得上
const stats = computed(() => [
  { label: '待核对结算单', value: countByStatus('待核对') },
  { label: '本月结算额', value: sumField('应结金额') },
  { label: '争议单数', value: countByStatus('有争议') },
])

function countByStatus(status: string): number {
  return rows.value.filter((row) => row['结算状态'] === status).length
}

function sumField(field: string): number {
  const sum = rows.value.reduce((acc, row) => acc + (Number(row[field]) || 0), 0)
  return Number(sum.toFixed(2))
}

function availableActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['结算状态'] ?? '')] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '结算单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '电量结算动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
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
