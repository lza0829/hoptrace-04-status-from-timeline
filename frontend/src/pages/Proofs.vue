<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await api.proofs()
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div class="page-card">
    <h1>证明</h1>
    <p class="lead">
      状态投影证明列表：每条记录绑定运单、正式时间线末 hop、映射码、投影值与证明时刻。
      证明由投影服务在时间线变更的同一事务内追加，不单独写入。
      <router-link to="/status" class="inline-link">查看同源检查 →</router-link>
    </p>
    <p v-if="err" class="muted">{{ err }}</p>
    <table class="table">
      <thead>
        <tr>
          <th>id</th><th>运单</th><th>末 hop</th><th>映射码</th>
          <th>投影</th><th>时间线摘要</th><th>证明时刻</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.id }}</td>
          <td><router-link :to="`/status?wb=${r.waybill_id}`">{{ r.waybill_id }}</router-link></td>
          <td>{{ r.last_hop_id || '—' }}</td>
          <td>{{ r.mapped_code || '—' }}</td>
          <td>{{ r.proj_value }}</td>
          <td :title="r.timeline_digest">{{ (r.timeline_digest || '').slice(0, 12) }}…</td>
          <td>{{ r.created_at }}</td>
        </tr>
        <tr v-if="!rows.length"><td colspan="7" class="muted">暂无证明</td></tr>
      </tbody>
    </table>
  </div>
</template>
