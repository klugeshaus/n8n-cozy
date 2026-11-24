# n8n

A single self-contained n8n Marketplace app chart for Cozystack 1.7.1. It deploys one n8n instance (SQLite storage, one replica) and provides two optional toggles: the **Code Sandbox** (external task runners) and **Search** (an in-cluster SearXNG instance with its JSON API enabled). The chart does not depend on `cozy-lib` and renders standalone with `helm lint`/`helm template`; injected Cozystack values (`_namespace`, `_cluster`) are optional.

The deployment guide lives in the top-level repository README; this document is the chart reference.

## Toggles

| Value | Default | Description |
|---|---|---|
| `sandbox.enabled` | `false` | Code Sandbox — deploys `n8nio/runners` external task runners and wires the n8n task broker on port 5679. |
| `search.enabled` | `false` | Search — deploys a private in-cluster SearXNG with its JSON API enabled at `http://<release>-search:8080`. |

## Values

### Common parameters

| Value | Default | Description |
|---|---|---|
| `host` | `""` | Fully-qualified hostname for n8n. Leave empty to use the tenant apex domain (`<release>.<tenant-host>`). |
| `size` | `10Gi` | Size of the persistent volume that stores n8n workflows, credentials and execution data. |
| `storageClass` | `""` | StorageClass used for the n8n data volume. Empty uses the cluster default. Immutable. |
| `resources.cpu` | `""` | Explicit CPU override for the n8n container. |
| `resources.memory` | `""` | Explicit memory override for the n8n container. |
| `resourcesPreset` | `t1.small` | Default sizing preset for the n8n container (Cozystack preset matrix). |
| `timezone` | `UTC` | Timezone used by n8n for scheduled workflows (IANA name). |
| `image.repository` | `docker.n8n.io/n8nio/n8n` | n8n main container image repository. |
| `image.tag` | `2.48.5` | n8n image tag; also used for the Code Sandbox runner image so versions cannot diverge. n8n >= 2.13.0 is required when the Code Sandbox is enabled. |
| `communityPackages` | `""` | JSON array of npm community packages reconciled by n8n on startup, e.g. `[{"name":"n8n-nodes-searxng","version":"0.2.6"}]`. Requires egress to the npm registry. Leave empty to install nodes from the n8n UI instead. |

### Code Sandbox (`sandbox.*`)

| Value | Default | Description |
|---|---|---|
| `sandbox.enabled` | `false` | Deploy the task-runner Deployment and wire the n8n task broker. |
| `sandbox.replicas` | `1` | Number of task-runner replicas. |
| `sandbox.imageRepository` | `n8nio/runners` | Runner image repository; the tag always follows `image.tag`, so the n8n and runner versions cannot diverge. |
| `sandbox.resourcesPreset` | `t1.nano` | Sizing preset for each runner replica. |
| `sandbox.resources.cpu` | `""` | Explicit CPU override for each runner replica. |
| `sandbox.resources.memory` | `""` | Explicit memory override for each runner replica. |

### Search (`search.*`)

| Value | Default | Description |
|---|---|---|
| `search.enabled` | `false` | Deploy SearXNG and expose it to n8n at `http://<release>-search:8080`. |
| `search.image.repository` | `searxng/searxng` | SearXNG image repository. |
| `search.image.tag` | `2026.11.15-2d500cb6b` | SearXNG image tag. |
| `search.resourcesPreset` | `t1.nano` | Sizing preset for the SearXNG container. |
| `search.resources.cpu` | `""` | Explicit CPU override for the SearXNG container. |
| `search.resources.memory` | `""` | Explicit memory override for the SearXNG container. |

## Images

| Component | Image |
|---|---|
| n8n | `docker.n8n.io/n8nio/n8n:2.48.5` |
| Task runners (Code Sandbox) | `n8nio/runners:2.48.5` (tag follows `image.tag`) |
| SearXNG (Search) | `searxng/searxng:2026.11.15-2d500cb6b` |

## Notes

- n8n >= 2.13.0 is required for the task runners used by the Code Sandbox; the runner image tag must equal the n8n `image.tag` (enforced by construction — the chart always derives it from `image.tag`).
- `N8N_ENCRYPTION_KEY` is stable across upgrades: it is generated once and then preserved via `lookup` from the live `<release>-credentials` Secret, so existing credentials remain decryptable. The same Secret carries `N8N_RUNNERS_AUTH_TOKEN` for the optional runners.
- n8n runs in SQLite/standalone mode, which means exactly 1 replica (no queue mode); the Deployment uses a `Recreate` strategy because the data volume is RWO.
- `resourcesPreset` reproduces Cozystack's `cozy-lib` preset matrix faithfully (size `nano`…`4xlarge` × series `t1/c1/s1/u1/m1` plus the legacy flat aliases): limits are `cpu`/`memory`/`ephemeral-storage`, and requests are derived as `cpu = ceil(limit/10)`, `memory = limit`, `ephemeral-storage = int(limit/40)`. Explicit `resources.cpu` / `resources.memory` override the preset limits.
- The SearXNG JSON API is usable with the built-in **HTTP Request** node at `http://<release>-search:8080/search?q=<query>&format=json`; the `SEARXNG_URL` env var hints at the in-cluster base URL when Search is enabled.
- The optional `n8n-nodes-searxng@0.2.6` community node is archived/MIT and is not built into this chart; install it via `communityPackages`, which requires egress to the npm registry.
- No `cozy-lib` dependency — the chart is self-contained. The injected `_namespace`/`_cluster` values are optional, so `helm lint` and `helm template` work standalone.

## License

[MIT](../../LICENSE) — Copyright (c) 2026 Klugeshaus. Free to use, modify and redistribute; see the repository root `LICENSE` for the full terms.
