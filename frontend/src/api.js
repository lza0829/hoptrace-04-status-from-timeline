async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  if (!res.ok) {
    let payload
    try {
      payload = await res.json()
    } catch {
      payload = null
    }
    const detail = payload?.detail
    const msg =
      typeof detail === 'string'
        ? detail
        : detail?.reason || detail?.error || JSON.stringify(detail) || res.statusText
    const err = new Error(msg)
    err.status = res.status
    err.payload = payload
    throw err
  }
  return res.json()
}

export const api = {
  health: () => req('/api/health'),
  overview: () => req('/api/overview'),
  waybills: () => req('/api/waybills'),
  timeline: (id) => req(`/api/waybills/${encodeURIComponent(id)}/timeline`),
  statusProof: (id) => req(`/api/waybills/${encodeURIComponent(id)}/status-proof`),
  statusCheck: () => req('/api/status-check'),
  loadHop: (id, hop) =>
    req(`/api/waybills/${encodeURIComponent(id)}/hops`, {
      method: 'POST',
      body: JSON.stringify(hop),
    }),
  writeStatusDirect: (id, status) =>
    req(`/api/waybills/${encodeURIComponent(id)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status_proj: status }),
    }),
  quarantine: () => req('/api/quarantine'),
  sidecar: () => req('/api/sidecar'),
  ingest: () => req('/api/ingest/run', { method: 'POST' }),
  proofs: (waybillId) =>
    req(waybillId ? `/api/status-proofs?waybill_id=${encodeURIComponent(waybillId)}` : '/api/status-proofs'),
}
