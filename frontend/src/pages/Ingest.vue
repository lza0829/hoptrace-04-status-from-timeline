<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const result = ref(null)
const busy = ref(false)
const err = ref('')

async function run() {
  busy.value = true
  err.value = ''
  try {
    result.value = await api.ingest()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page-card">
    <h1>装载</h1>
    <p class="lead">
      从本地夹具跑一批轨迹点装载。每条写入正式时间线的 hop 都在同一事务内触发状态投影重算，
      并追加一条状态证明；批次失败则整批回滚。
    </p>
    <button class="btn" :disabled="busy" @click="run">{{ busy ? '装载中…' : '跑装载批次' }}</button>
    <p v-if="err" class="muted" style="margin-top:12px">{{ err }}</p>
    <template v-if="result">
      <div class="stat-row" style="margin-top:16px" v-if="result.ok">
        <div class="stat"><b>{{ result.report.written }}</b><span>新写入 hop</span></div>
        <div class="stat"><b>{{ result.report.input }}</b><span>输入 hop</span></div>
        <div class="stat ok">
          <b>{{ (result.report.projection_redrawn || []).length }}</b><span>投影重算运单</span>
        </div>
      </div>
      <p v-if="result.ok && result.report.projection_redrawn?.length" class="hint">
        重算运单：{{ result.report.projection_redrawn.join('、') }}
      </p>
      <pre style="margin-top:16px;font-family:var(--mono);font-size:12px;white-space:pre-wrap">{{ result }}</pre>
    </template>
  </div>
</template>
