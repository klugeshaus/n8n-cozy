# n8n

A single self-contained n8n Marketplace app chart for Cozystack 1.7.1. It deploys one n8n instance (SQLite storage, one replica) and provides two optional toggles: the **Code Sandbox** (the [n8n sandbox service](https://github.com/n8n-io/n8n-sandbox-service) — sandbox API + Sysbox runners, **Setup 1**) and **Search** (an in-cluster SearXNG instance with its JSON API enabled). The chart does not depend on `cozy-lib` and renders standalone with `helm lint`/`helm template`; injected Cozystack values (`_namespace`, `_cluster`) are optional.

The deployment guide lives in the top-level repository README; this document is the chart reference.

## Toggles

| Value | Default | Description |
|---|---|---|
| `sandbox.enabled` | `false` | Code Sandbox — deploys the n8n sandbox API (`n8nio/n8n-sandbox-service-api`) plus Sysbox runners and wires n8n to it with `N8N_INSTANCE_AI_SANDBOX_*` / `N8N_SANDBOX_SERVICE_*`. |
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
| `image.tag` | `2.48.5` | n8n image tag. **n8n >= 2.16.0** is required for the Code Sandbox (sandbox service) integration; `instance-ai` is a default module, so no `N8N_ENABLED_MODULES` is needed. |
| `communityPackages` | `""` | JSON array of npm community packages reconciled by n8n on startup, e.g. `[{"name":"n8n-nodes-searxng","version":"0.2.6"}]`. Requires egress to the npm registry. Leave empty to install nodes from the n8n UI instead. |

### Code Sandbox (`sandbox.*`)

| Value | Default | Description |
|---|---|---|
| `sandbox.enabled` | `false` | Deploy the sandbox API, its TLS/auth/config resources and the runner StatefulSet, and wire n8n to the API. |
| `sandbox.apiKey` | `""` | API key shared by n8n (`N8N_SANDBOX_SERVICE_API_KEY`) and the API (`SANDBOX_API_KEYS`). Empty → generated once and preserved via `lookup`. |
| `sandbox.runnerRegistrationToken` | `""` | `SANDBOX_API_RUNNER_REGISTRATION_TOKEN`. Empty → generated once and preserved via `lookup`. |
| `sandbox.external.enabled` | `false` | Use an external sandbox API instead of rendering any in-cluster sandbox resources. |
| `sandbox.external.url` | `""` | Base URL of the external API, reachable from n8n over plain HTTP (e.g. `http://<vm-address>:8080`). |
| `sandbox.external.apiKey` | `""` | API key for the external API; must match a value in its `SANDBOX_API_KEYS`. |
| `sandbox.api.image.repository` | `n8nio/n8n-sandbox-service-api` | Sandbox API image. |
| `sandbox.api.image.tag` | `1.16.0` | Sandbox API image tag. |
| `sandbox.api.replicas` | `1` | API replicas (SQLite backend; keep 1). |
| `sandbox.api.resourcesPreset` | `t1.small` | Sizing preset for the API container. |
| `sandbox.api.resources.cpu` / `.memory` | `""` | Explicit overrides for the API container. |
| `sandbox.runner.enabled` | `true` | Render the runner StatefulSet. |
| `sandbox.runner.isolation` | `sysbox` | `sysbox` (needs the Sysbox node pool) or `privileged` (works on Talos / immutable-rootfs clusters). |
| `sandbox.runner.acknowledgePrivileged` | `false` | Must be `true` when `isolation: privileged`; the chart fails otherwise. |
| `sandbox.runner.image.repository` | `n8nio/n8n-sandbox-service-runner-dind` | Runner image. |
| `sandbox.runner.image.tag` | `1.16.0` | Runner image tag. |
| `sandbox.runner.sandboxImage.repository` | `n8nio/n8n-sandbox-service-sandbox` | Sandbox workload image. |
| `sandbox.runner.sandboxImage.tag` | `1.16.0` | Sandbox workload image tag. |
| `sandbox.runner.replicas` | `1` | Number of runner replicas. |
| `sandbox.runner.capacityTotal` | `100` | Runner capacity (mandatory; size it for your node pool). |
| `sandbox.runner.dataRootSizeLimit` | `64Gi` | emptyDir size limit for the Docker data root. |
| `sandbox.runner.nodeSelector` | `{sysbox-install: "yes"}` | Node selector for the runner pods. |
| `sandbox.runner.tolerations` | `[{key: sysbox-runtime, operator: Equal, value: not-running, effect: NoSchedule}]` | Tolerations matching the Sysbox installer taint. |
| `sandbox.runner.resourcesPreset` | `t1.medium` | Sizing preset for the runner container. |
| `sandbox.runner.resources.cpu` / `.memory` | `""` | Explicit overrides for the runner container. |

#### External sandbox VM (real Sysbox on Cozystack)

On clusters whose nodes cannot run Sysbox (e.g. **Talos**, which has a read-only
root filesystem), a dedicated Ubuntu VM is the only way to get real Sysbox
isolation. Set `sandbox.enabled=true` + `sandbox.external.enabled=true` plus
`sandbox.external.url` / `sandbox.external.apiKey`; the chart then renders **no**
in-cluster sandbox objects and only sets the four `N8N_*SANDBOX*` env vars as
plain values.

[`deploy/sandbox-vm/README.md`](../../deploy/sandbox-vm/README.md) contains
Cozystack `VMDisk` + `VMInstance` manifests that auto-provision that Ubuntu VM
(KubeVirt + CDI + cloud-init) running **both** the sandbox API and a privileged
DinD runner with local mTLS — n8n docs "Setup 3: Bundled sandbox". Apply the VM
first, verify `curl http://<vm-address>:8080/healthz` returns `{"status":"ok"}`,
then set the values above.

### Search (`search.*`)

| Value | Default | Description |
|---|---|---|
| `search.enabled` | `false` | Deploy SearXNG and expose it to n8n at `http://<release>-search:8080`. |
| `search.image.repository` | `searxng/searxng` | SearXNG image repository. |
| `search.image.tag` | `2026.11.15-2d500cb6b` | SearXNG image tag. |
| `search.resourcesPreset` | `t1.nano` | Sizing preset for the SearXNG container. |
| `search.resources.cpu` | `""` | Explicit CPU override for the SearXNG container. |
| `search.resources.memory` | `""` | Explicit memory override for the SearXNG container. |

## Environment

### SearXNG container (instance `n8n-ai`)

| Variable | Value | Optional |
|---|---|---|
| `SEARXNG_BASE_URL` | `http://n8n-ai-search:8080/` | `false` |
| `SEARXNG_SECRET` | set to the key `SEARXNG_SECRET` in secret `n8n-ai-search-config` | `false` |

`SEARXNG_SECRET` is generated once and preserved via `lookup`, and is also written into `server.secret_key` in the same Secret's `settings.yml`. n8n itself receives `SEARXNG_URL` (without the trailing slash) for convenience.

### n8n container (when `sandbox.enabled`)

| Variable | Value |
|---|---|
| `N8N_INSTANCE_AI_SANDBOX_ENABLED` | `true` |
| `N8N_INSTANCE_AI_SANDBOX_PROVIDER` | `n8n-sandbox` |
| `N8N_SANDBOX_SERVICE_URL` | `http://<release>-sandbox:8080` |
| `N8N_SANDBOX_SERVICE_API_KEY` | from `<release>-credentials` / `SANDBOX_API_KEY` — must match `SANDBOX_API_KEYS` |

## Images

| Component | Image |
|---|---|
| n8n | `docker.n8n.io/n8nio/n8n:2.48.5` |
| Sandbox API (Code Sandbox) | `n8nio/n8n-sandbox-service-api:1.16.0` |
| Sandbox runner (Code Sandbox) | `n8nio/n8n-sandbox-service-runner-dind:1.16.0` |
| Sandbox workload (Code Sandbox) | `n8nio/n8n-sandbox-service-sandbox:1.16.0` |
| SearXNG (Search) | `searxng/searxng:2026.11.15-2d500cb6b` |

## Notes

- **n8n >= 2.16.0** is required for the sandbox service integration (pinned `2.48.5`); the `instance-ai` module is enabled by default.
- `N8N_ENCRYPTION_KEY` is stable across upgrades: it is generated once and then preserved via `lookup` from the live `<release>-credentials` Secret, so existing credentials remain decryptable. The same Secret carries `SANDBOX_API_KEY`, shared with the sandbox service so the two sides can never drift.
- n8n talks to the sandbox API over plain HTTP on the ClusterIP. mTLS between the API and its runners is mandatory; the chart generates a self-signed CA and four leaf certificates in-chart and preserves them via `lookup` — **no cert-manager dependency**.
- **Sysbox is a cluster-level prerequisite**: a dedicated Ubuntu node pool with Sysbox installed (Kubernetes 1.32+, >= 4 CPU / 4 GB per node, `br_netfilter`, `RuntimeClass sysbox-runc`). On immutable-rootfs distributions such as **Talos**, Sysbox cannot install — use `runner.isolation: privileged` with `runner.acknowledgePrivileged: true` and label the namespace `pod-security.kubernetes.io/enforce=privileged`. See the top-level README for the full setup.
- The sandbox service images come from `n8n-io/n8n-sandbox-service` under n8n's **Sustainable Use License** (not MIT); this chart only references them.
- n8n runs in SQLite/standalone mode, which means exactly 1 replica (no queue mode); the Deployment uses a `Recreate` strategy because the data volume is RWO.
- `resourcesPreset` reproduces Cozystack's `cozy-lib` preset matrix faithfully (size `nano`…`4xlarge` × series `t1/c1/s1/u1/m1` plus the legacy flat aliases): limits are `cpu`/`memory`/`ephemeral-storage`, and requests are derived as `cpu = ceil(limit/10)`, `memory = limit`, `ephemeral-storage = int(limit/40)`. Explicit `resources.cpu` / `resources.memory` override the preset limits.
- The SearXNG JSON API is usable with the built-in **HTTP Request** node at `http://<release>-search:8080/search?q=<query>&format=json`; the `SEARXNG_URL` env var hints at the in-cluster base URL when Search is enabled.
- The optional `n8n-nodes-searxng@0.2.6` community node is archived/MIT and is not built into this chart; install it via `communityPackages`, which requires egress to the npm registry.
- No `cozy-lib` dependency — the chart is self-contained. The injected `_namespace`/`_cluster` values are optional, so `helm lint` and `helm template` work standalone.

## License

[MIT](../../LICENSE) — Copyright (c) 2026 Klugeshaus. Free to use, modify and redistribute; see the repository root `LICENSE` for the full terms.
