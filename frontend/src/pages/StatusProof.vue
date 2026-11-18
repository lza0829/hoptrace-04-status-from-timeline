<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const check = ref(null)
const detail = ref(null)
const err = ref('')

const focus = computed(() => route.query.wb || '')

async function load() {
  err.value = ''
  try {
    check.value = await api.statusCheck()
    detail.value = focus.value ? await api.statusProof(focus.value) : null
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(load)
watch(focus, load)
</script>

<template>
  <div class="page-card">
    <div class="page-head">
      <h1>状态证明</h1>
      <button class="btn ghost" @click="load">重跑检查</button>
    </div>
    <p class="lead">
      对外状态只能由正式时间线末有效 hop 的 event_code 映射得出。此处逐运单核对
      运单投影值、末 hop、映射码与证明时刻；任何不一致都会列为分叉。
    </p>
    <p v-if="err" class="muted">{{ err }}</p>

    <section v-if="detail" class="proof-sheet">
      <h2>{{ detail.waybill_id }} 状态证明</h2>
      <dl class="kv">
        <dt>运单</dt><dd>{{ detail.waybill_id }}</dd>
        <dt>投影值</dt><dd>{{ detail.status_proj }}</dd>
        <dt>末 hop</dt><dd>{{ detail.last_hop?.id || '—' }}</dd>
        <dt>末 hop 码</dt><dd>{{ detail.mapped_code || '—' }}</dd>
        <dt>映射值</dt><dd>{{ detail.proj_value }}</dd>
        <dt>证明时刻</dt><dd>{{ detail.proof_at || '—' }}</dd>
        <dt>时间线摘要</dt><dd class="digest">{{ (detail.timeline_digest || '').slice(0, 24) }}…</dd>
        <dt>同源</dt>
        <dd><span class="tag" :class="detail['同源'] ? 'ok' : 'bad'">{{ detail['同源'] ? '是' : '否' }}</span></dd>
        <dt>来源</dt><dd>{{ detail.source }}</dd>
      </dl>
    </section>

    <div class="stat-row" v-if="check">
      <div class="stat"><b>{{ check.checked }}</b><span>核对运单</span></div>
      <div class="stat ok"><b>{{ check.aligned }}</b><span>同源</span></div>
      <div class="stat" :class="{ bad: check.diverged }">
        <b>{{ check.diverged }}</b><span>分叉</span>
      </div>
    </div>

    <table class="table" v-if="check">
      <thead>
        <tr>
          <th>运单</th><th>投影值</th><th>末 hop</th><th>映射码</th>
          <th>期望值</th><th>证明时刻</th><th>判定</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="r in check.items"
          :key="r.waybill_id"
          :class="{ rowbad: !r['同源'], focused: focus === r.waybill_id }"
        >
          <td><router-link :to="`/status?wb=${r.waybill_id}`">{{ r.waybill_id }}</router-link></td>
          <td>{{ r.status_proj }}</td>
          <td>{{ r.last_hop_id || '—' }}</td>
          <td>{{ r.mapped_code || '—' }}</td>
          <td>{{ r.expected_status }}</td>
          <td>{{ r.proof_created_at || '—' }}</td>
          <td>
            <span v-if="r['同源']" class="tag ok">同源</span>
            <span v-else class="tag bad" :title="r.divergences.join('；')">分叉</span>
          </td>
        </tr>
        <tr v-if="!check.items.length"><td colspan="7" class="muted">暂无运单</td></tr>
      </tbody>
    </table>
  </div>
</template>
