<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const waybills = ref([])
const selected = ref(null)
const detail = ref(null)
const overview = ref(null)
const err = ref('')

const hopCode = ref('DELIVERED')
const actionMsg = ref('')
const actionErr = ref('')
const busy = ref(false)

const CODES = ['PICKED', 'IN_TRANSIT', 'ARRIVED_HUB', 'OUT_FOR_DELIVERY', 'DELIVERED', 'EXCEPTION']

async function loadList() {
  overview.value = await api.overview()
  waybills.value = await api.waybills()
  if (!selected.value && waybills.value.length) {
    selected.value = waybills.value[0].id
  }
}

async function loadDetail(id) {
  if (!id) return
  detail.value = await api.timeline(id)
}

onMounted(async () => {
  try {
    await loadList()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

watch(selected, (id) => {
  actionMsg.value = ''
  actionErr.value = ''
  loadDetail(id).catch((e) => { err.value = String(e.message || e) })
})

const hops = computed(() => detail.value?.hops || [])
const proof = computed(() => detail.value?.proof)
const check = computed(() => detail.value?.check)

function nextTs() {
  const last = hops.value[hops.value.length - 1]
  const d = last ? new Date(last.event_ts) : new Date()
  return new Date(d.getTime() + 60 * 60 * 1000).toISOString().replace('.000Z', 'Z')
}

async function loadHop() {
  busy.value = true
  actionMsg.value = ''
  actionErr.value = ''
  try {
    const res = await api.loadHop(selected.value, {
      id: `H-UI-${Date.now()}`,
      event_ts: nextTs(),
      location_code: 'UI-POINT',
      event_code: hopCode.value,
      seq: hops.value.length + 1,
    })
    actionMsg.value = `已装载正式 hop，投影重算为「${res.status}」`
    await loadDetail(selected.value)
    await loadList()
  } catch (e) {
    actionErr.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function tryDirectWrite() {
  busy.value = true
  actionMsg.value = ''
  actionErr.value = ''
  try {
    await api.writeStatusDirect(selected.value, hopCode.value === 'DELIVERED' ? '已签收' : '运输中')
    actionErr.value = '意外：直接改写未被拒绝'
  } catch (e) {
    actionErr.value = `已拒绝并回滚：${e.message}`
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <p v-if="err" class="muted">{{ err }}</p>
    <div class="stat-row" v-if="overview">
      <div class="stat"><b>{{ overview.waybills }}</b><span>运单</span></div>
      <div class="stat"><b>{{ overview.hops_primary }}</b><span>正式 hop</span></div>
      <div class="stat"><b>{{ overview.hops_sidecar }}</b><span>旁路</span></div>
      <div class="stat"><b>{{ overview.quarantine }}</b><span>隔离</span></div>
      <div class="stat" :class="{ ok: !overview.projection_diverged, bad: overview.projection_diverged }">
        <b>{{ overview.projection_aligned }}</b><span>投影同源</span>
      </div>
      <div class="stat" :class="{ bad: overview.projection_diverged }">
        <b>{{ overview.projection_diverged }}</b><span>投影分叉</span>
      </div>
    </div>

    <div class="tri">
      <aside class="pane waybill-pane">
        <h2>运单索引</h2>
        <button
          v-for="w in waybills"
          :key="w.id"
          class="wb-item"
          :class="{ active: selected === w.id }"
          @click="selected = w.id"
        >
          <span class="id">{{ w.id }}</span>
          <span class="title">{{ w.title }}</span>
          <span class="st">{{ w.status_proj }}</span>
        </button>
      </aside>

      <section class="pane axis-pane">
        <div class="axis-head">
          <h1>{{ detail?.waybill?.title || '时间线' }}</h1>
          <span>{{ selected }}</span>
        </div>
        <div class="v-axis" v-if="hops.length">
          <div class="hop-node" v-for="h in hops" :key="h.id">
            <div class="ts">{{ h.event_ts }}</div>
            <div class="code">{{ h.event_code }}</div>
            <div class="loc">{{ h.location_code }} · {{ h.id }}</div>
          </div>
        </div>
        <p v-else class="muted">无正式轨迹点</p>
      </section>

      <aside class="pane inspect-pane">
        <h2>检查器</h2>
        <dl class="kv" v-if="detail?.waybill">
          <dt>运单</dt><dd>{{ detail.waybill.id }}</dd>
          <dt>投影状态</dt><dd>{{ detail.waybill.status_proj }}</dd>
          <dt>同源</dt>
          <dd>
            <span v-if="check" class="tag" :class="check['同源'] ? 'ok' : 'bad'">
              {{ check['同源'] ? '是' : '否' }}
            </span>
          </dd>
          <dt>创建</dt><dd>{{ detail.waybill.created_at }}</dd>
        </dl>

        <h2>状态证明</h2>
        <dl class="kv" v-if="proof">
          <dt>末 hop</dt><dd>{{ proof.last_hop_id || '—' }}</dd>
          <dt>映射码</dt><dd>{{ proof.mapped_code || '—' }}</dd>
          <dt>投影值</dt><dd>{{ proof.proj_value }}</dd>
          <dt>摘要</dt><dd class="digest">{{ (proof.timeline_digest || '').slice(0, 16) }}…</dd>
          <dt>证明时刻</dt><dd>{{ proof.created_at }}</dd>
        </dl>
        <p v-else class="muted">暂无证明</p>

        <h2>装载 hop</h2>
        <div class="control">
          <select v-model="hopCode">
            <option v-for="c in CODES" :key="c" :value="c">{{ c }}</option>
          </select>
          <button class="btn small" :disabled="busy" @click="loadHop">装载并重算</button>
        </div>
        <p class="hint">投影随正式线末有效 hop 同事务更新；乱序旧 hop 不改变投影。</p>

        <h2>直接改投影</h2>
        <div class="control">
          <button class="btn small danger" :disabled="busy" @click="tryDirectWrite">
            尝试直接改写（应失败）
          </button>
        </div>
        <p class="hint">该入口整笔失败并回滚，不留下半成功。</p>

        <p v-if="actionMsg" class="flash ok">{{ actionMsg }}</p>
        <p v-if="actionErr" class="flash bad">{{ actionErr }}</p>

        <p class="hint" v-if="check && !check['同源']">
          分叉原因：{{ check.divergences.join('；') }}
        </p>
      </aside>

      <footer class="pane dot-rail">
        <span class="label">HOP</span>
        <template v-for="(h, i) in hops" :key="h.id">
          <span class="dot on"></span>
          <span v-if="i < hops.length - 1" class="dot-line"></span>
        </template>
        <template v-if="!hops.length">
          <span class="dot"></span>
          <span class="dot-line"></span>
          <span class="dot"></span>
        </template>
      </footer>
    </div>
  </div>
</template>
