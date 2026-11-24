# n8n for Cozystack 1.7 Marketplace

A standalone, **tappable External-Apps repository** that adds a single **n8n**
card to the Cozystack 1.7 Marketplace. The card's **Deploy** form has two
optional checkboxes:

| Toggle | What it deploys |
|---|---|
| **Code Sandbox** | n8n external task runners (`n8nio/runners`) wired to the n8n task broker, so the JavaScript/Python **Code** node runs in an isolated sandbox. |
| **Search (SearXNG)** | A private in-cluster SearXNG metasearch engine with its **JSON API** enabled, reachable from n8n at `http://<release>-search:8080`. |

Both are disabled by default. Enabling them deploys the extra components as
part of the *same* n8n instance — no separate Marketplace cards and no second
install step.

Target: **Cozystack 1.7.1** (tag `v1.7.1`, the latest stable 1.7.x release;
all 22 upstream files we depend on are byte-identical to branch `release-1.7`,
while `main` has drifted). The repo is validated with `cozypkg`, pushed as an OCI
artifact, tapped into an existing cluster, and installed — **no Cozystack
rebuild is required**. The `packages/` tree is also laid out so it can be
dropped into the `cozystack/cozystack` source tree as a normal in-tree app.

---

## Repository layout

```
README.md                          this deployment guide
LICENSE                            MIT — free for anyone to use, modify and redistribute
Makefile                           convenience targets
.gitignore
deploy/package.yaml                non-interactive `Package` manifest
hack/gen-appdef.py                 regenerates the ApplicationDefinition
hack/verify.py / verify.sh         local `cozypkg validate` equivalent
hack/package.mk                    no-op shim for the in-tree Makefiles
packages/
  core/platform/sources/n8n.yaml  PackageSource  cozy-apps.n8n
  apps/n8n/                       the tenant-facing Helm chart (raw manifests)
    Chart.yaml
    values.yaml                  chart values (also the Deploy form fields)
    values.schema.json           JSON Schema -> AD spec.application.openAPISchema
    logos/n8n.svg                Marketplace icon source
    templates/                   Deployment, Service, PVC, Secret, Ingress/HTTPRoute,
                                 sandbox.yaml, search.yaml, dashboard-resourcemap.yaml
    tests/                       helm-unittest specs
  system/n8n-rd/                 cluster-scoped ApplicationDefinition chart
    cozyrds/n8n.yaml             the ApplicationDefinition (AD)
    templates/cozyrd.yaml        emits cozyrds/* verbatim
```

### Why this shape

- `packages/core/platform/sources/n8n.yaml` declares the **`PackageSource`**
  (`cozy-apps.n8n`). `cozypkg tap` materialises it; `cozypkg add` creates the
  `Package` CR. The component named `n8n-rd` carries an `install:` block, so
  installing the Package renders the **ApplicationDefinition into
  `cozy-system`** — that is what puts the card in the Marketplace.
- The component named `n8n` has **no** `install:` block. It is consumed only
  as an `ExternalArtifact` referenced by
  `spec.release.chartRef.name: cozy-apps-n8n-default-n8n`
  (`naming.ArtifactName("cozy-apps.n8n", "default", "n8n")`).
- The Dashboard renders the Deploy form directly from
  `spec.application.openAPISchema`. That string is generated from
  `values.schema.json` by `hack/gen-appdef.py`, so the form and the chart
  contract can never drift. Flipping a checkbox writes `sandbox.enabled` /
  `search.enabled` into the CR spec, which becomes `HelmRelease.spec.values`.
- The app chart renders **self-contained raw Kubernetes manifests** instead of
  the two-level "Flux HelmRelease → vendored upstream chart" pattern used by
  built-in apps. It has **no `cozy-lib` dependency**, so `cozypkg validate
  --helm-lint` works without staging libraries and `helm lint` / `helm
  template` work standalone. Injected Cozystack values (`_namespace`,
  `_cluster`) are always read via `default dict`, so they are optional.
- Both `Chart.yaml` files carry a **real chart version (`1.0.0`)** rather than
  the in-tree `0.0.0 # Placeholder` comment. `cozypkg push` is a plain
  `flux push artifact` and publishes the chart verbatim — only the in-tree
  Cozystack build pipeline rewrites versions. Bump both chart versions on
  every release/tag (and keep the OCI tag in sync).

---

## Prerequisites

- A running **Cozystack 1.7** cluster with `cozystack.networking` and
  `cozystack.cozystack-engine` installed (the two `dependsOn` entries).
- `kubectl` (admin context), `helm` v3, `git`, and **`cozypkg`** (the
  `cozypkg` CLI shipped with Cozystack 1.7) on your workstation.
- An OCI registry you can push to (e.g. `ghcr.io/<org>/n8n`).
- For community nodes / SearXNG upstream engines: outbound internet from the
  tenant namespace (npm registry, search engines).

> **RBAC:** no ClusterRole edit is needed. In `v1.7.1`,
> `cozystack-basics`'s `cozy:tenant:base` role already grants
> `apiGroups: ["apps.cozystack.io"], resources: ['*'], verbs: ['*']`, and
> `cozy:tenant:view:base` grants `get/list/watch` on `*`. Tenants can create
> and list the dynamically generated `N8N` resource out of the box. The
> `cozystack-api` aggregated API server builds the CRD from the
> ApplicationDefinition and restarts itself on AD changes — there is no
> hand-written CRD to install.

---

## Quickstart: validate → push → connect (tap) → add

All commands run from the repository root. Replace `<org>`, `<git-url>` and
the tag as needed.

### 0. Validate locally

```sh
./hack/verify.sh                 # self-contained: no cozypkg/flux/jq needed
cozypkg validate . --helm-lint  # the real gate, on a machine with cozypkg
```

`hack/verify.sh` re-implements the important `cozypkg validate` rules
(PackageSource presence/reserved prefix, component chart dirs, artifact-name
match, strict YAML decode, `openAPISchema` ↔ `values.schema.json` sync,
`values.yaml` ↔ schema consistency) and renders the chart in five value
combinations. `cozypkg validate . --helm-lint` is the authoritative check used
by the community index gate.

### 1. Make it a git repository

`cozypkg push` records a git source URL and revision in the OCI artifact. If
your repo has no `origin`, pass `--source` and `--revision` explicitly.

The canonical repository is **https://github.com/klugeshaus/n8n-cozy**.
Starting from the published repo, clone it instead of the `init` + `remote add`
pair below:

```sh
git clone https://github.com/klugeshaus/n8n-cozy.git
cd n8n-cozy
```

For a fresh directory that will be pushed as this repository:

```sh
git init
git remote add origin https://github.com/klugeshaus/n8n-cozy.git
git add -A
git commit -m "Add n8n Marketplace app for Cozystack 1.7"
git tag v1.0.0
```

### 2. Push the OCI artifact

```sh
cozypkg push oci://ghcr.io/<org>/n8n:v1.0.0 \
  --path . \
  --source https://github.com/klugeshaus/n8n-cozy.git \
  --revision v1.0.0 \
  --helm-lint --reproducible
```

`push` runs `flux push artifact <ref> --path=./packages …` behind the scenes
and validates first unless `--skip-validate` is given. `--path .` is the repo
root; the artifact root is `<root>/packages`.

### 3. Connect the repository (Dashboard → Repositories)

In the Cozystack dashboard this step is the **Repositories** page:

> **Repositories**
>
> External-Apps repositories connected to this cluster and the packages they
> expose. Connecting a repository makes its apps available but installs nothing.
> Install an app with `cozypkg add`. Connect only sources you trust. The index
> verifies signatures at publication time; connecting does not verify them.

The form has two fields:

- **Repository (oci:// reference)** — the published artifact, e.g.
  `oci://ghcr.io/<org>/n8n:v1.0.0`.
- **Pull secret (optional, for private repositories)** — the name of a
  pull-credential Secret pre-created in `cozy-system`; leave it empty for a
  public repository.

Connecting creates a Flux `OCIRepository` named `tap-<org>-n8n` in `cozy-system`
(labelled `cozystack.io/tap: "true"`), rewrites the PackageSource's `sourceRef`
to it, and materialises the `cozy-apps.n8n` PackageSource. **Connecting installs
nothing** — no `Package`, `HelmRelease` or `ApplicationDefinition` is created
until step 4. The Repositories page then lists the connected reference together
with the packages it exposes.

The same operation from the CLI:

```sh
cozypkg tap oci://ghcr.io/<org>/n8n:v1.0.0
# private repository (Secret must already exist in cozy-system):
cozypkg tap oci://ghcr.io/<org>/n8n:v1.0.0 --secret <pull-secret>
```

**Trust and signatures.** Connecting only validates the artifact's structure;
it does not verify signatures. Publication-time verification is the community
index's job (`cozypkg validate --require-signature`). Installing an app from a
connected repository runs its charts in your management cluster, so connect only
sources you trust. To additionally verify the cosign signature on **every pull**,
use the CLI-only flags `--certificate-identity` and `--certificate-oidc-issuer`
(both required together — the Repositories form has no equivalent):

```sh
cozypkg tap oci://ghcr.io/<org>/n8n:v1.0.0 \
  --certificate-identity '<subject-regex>' \
  --certificate-oidc-issuer '<issuer-regex>'
```

> **New in 1.7.1:** `tap` pins the artifact by digest. A tag-only reference is
> pinned to the digest it first resolves to, so moving the tag upstream no
> longer changes what the cluster runs — connect again to move the pin. You can
> also connect an immutable digest directly:
> `cozypkg tap oci://ghcr.io/<org>/n8n@sha256:<64 hex>`.

After connecting, the source is available for installation:

```sh
cozypkg list                     # shows cozy-apps.n8n as an available source
```

### 4. Install

**Interactive:**

```sh
cozypkg add cozy-apps.n8n
```

`add` asks which variant to install (there is one: `default`) and confirms
privileged components (there are none). It creates the cluster-scoped
`Package` CR named `cozy-apps.n8n`; the reconciler then installs the `n8n-rd`
component, which registers the cluster-scoped `ApplicationDefinition`.

**Non-interactive (recommended for GitOps):**

```sh
cozypkg add -f deploy/package.yaml
# ...or equivalently:
kubectl apply -f deploy/package.yaml
```

`deploy/package.yaml` is:

```yaml
apiVersion: cozystack.io/v1alpha1
kind: Package
metadata:
  name: cozy-apps.n8n
spec:
  variant: default
```

`cozypkg add -f` creates the `Package` directly from the file, skipping the
variant prompt. `PackageSpec` additionally supports `ignoreDependencies: []`
and `components: {<name>: {enabled: bool, values: {…}}}`.

### 5. Deploy an instance from the Marketplace

```sh
kubectl get applicationdefinitions              # cluster-scoped; n8n should be present
kubectl get packagesources                       # cluster-scoped; cozy-apps.n8n
```

In the Cozystack Dashboard: **Marketplace → PaaS → N8N → Deploy**. The form
shows `host`, `size`, `storageClass`, `resourcesPreset`, `timezone`, `image`,
`communityPackages`, and the two **checkboxes**: `sandbox.enabled` and
`search.enabled`. Give the instance a name and press **Deploy**. The Dashboard
POSTs a `N8N` CR (`apps.cozystack.io/v1alpha1`, plural `n8ns`) into your tenant
namespace; the reconciler creates the `HelmRelease`
`n8n-<instance-name>` pointing at the `ExternalArtifact`.

```sh
kubectl get n8ns -n <tenant>
kubectl get helmreleases -n <tenant> | grep n8n-
kubectl get pods -n <tenant> -l app.kubernetes.io/instance=n8n-<name>
```

To remove an instance, delete its `N8N` CR. To remove the app entirely:

```sh
cozypkg del cozy-apps.n8n
cozypkg untap cozy-apps.n8n
```

---

## Using the two options

### Search (SearXNG)

Enabling `search.enabled` deploys a private SearXNG with `limiter: false` and
`search.formats: [html, json]`. **The `json` format is required** — without it
the API returns HTML. Use the built-in **HTTP Request** node (no extra package
needed):

```
GET http://n8n-<name>-search:8080/search?q=<query>&format=json
```

When Search is enabled the n8n container also gets a `SEARXNG_URL` env var
with the base URL. SearXNG is **in-cluster only** (no Ingress/HTTPRoute), and
it needs outbound internet to reach the upstream search engines.

Optionally install the community node instead. It is **not built in** and is
not bundled by this chart:

```
n8n-nodes-searxng@0.2.6   (sammcj/n8n-nodes-searxng, archived, MIT)
```

Set `communityPackages` to a JSON array, e.g.
`[{"name":"n8n-nodes-searxng","version":"0.2.6"}]`. n8n then sets
`N8N_COMMUNITY_PACKAGES_MANAGED_BY_ENV=true` and reconciles the package on
boot; this **requires egress to the npm registry** and locks the
community-packages UI. Leave it empty to install nodes from the n8n UI.

### Code Sandbox (external task runners)

Enabling `sandbox.enabled`:

- adds `N8N_RUNNERS_MODE=external`,
  `N8N_RUNNERS_BROKER_LISTEN_ADDRESS=0.0.0.0`, `N8N_RUNNERS_AUTH_TOKEN` and
  `N8N_NATIVE_PYTHON_RUNNER=true` to the n8n main container (broker port
  **5679**);
- creates Service `n8n-<name>-broker` (in-cluster only);
- creates Deployment `n8n-<name>-runner` from `n8nio/runners:<image.tag>`,
  with `N8N_RUNNERS_TASK_BROKER_URI=http://n8n-<name>-broker:5679`, the same
  auth token, and launcher health checks on port **5680**.

Notes:

- **Version parity is enforced by construction**: the runner tag is always
  derived from `image.tag`, so the n8n and runner versions cannot diverge.
- **n8n >= 2.13.0 is required** for external task runners. The pinned default
  is `2.48.5`; do not override `image.tag` with an older release while the
  sandbox is enabled.
- The runners use n8n's **stock launcher policy** (`/etc/n8n-task-runners.json`).
  Advanced `NODE_FUNCTION_ALLOW_EXTERNAL` / `N8N_RUNNERS_STDLIB_ALLOW`
  allow-lists are `env-overrides` in that launcher config, not container env
  vars; to change them, mount a custom launcher config and set
  `N8N_RUNNERS_CONFIG_PATH`.
- The deprecated `N8N_RUNNERS_ENABLED` variable is intentionally **not** set.

### General n8n notes

- **Stable encryption key.** `N8N_ENCRYPTION_KEY` is generated once and then
  preserved via `lookup` from the live `<release>-credentials` Secret. Changing
  it makes stored credentials undecryptable. The same Secret holds the runner
  auth token.
- **Standalone / SQLite.** One replica, `Recreate` strategy, data on a RWO PVC
  at `/home/node/.n8n`. There is no queue mode (which would require Postgres +
  Redis). Scale-out is intentionally not offered.
- **Hostname / TLS.** With `_namespace.gateway` set, the chart renders a
  Gateway API `HTTPRoute` attached to Gateway `cozystack`; otherwise it renders
  a `networking.k8s.io/v1` Ingress with cert-manager annotations. Set `host`
  explicitly to override the default `<release>.<tenant-apex>`.

---

## Merging into the Cozystack source tree

The `packages/` tree is drop-in compatible. For a PR against
`cozystack/cozystack` `release-1.7`:

1. Copy `packages/apps/n8n/` → `packages/apps/n8n/` and
   `packages/system/n8n-rd/` → `packages/system/n8n-rd/`.
2. Copy `packages/core/platform/sources/n8n.yaml` →
   `packages/core/platform/sources/n8n-application.yaml` and rename the
   PackageSource to **`cozystack.n8n-application`** (the reserved `cozystack.`
   prefix is correct in-tree; it is forbidden only for external/tapped repos).
3. **Regenerate the AD** so `chartRef.name` matches the new artifact name:
   ```sh
   python3 hack/gen-appdef.py --ps-name cozystack.n8n-application
   ```
   This produces `cozystack-n8n-application-default-n8n`. (Verify with
   `python3 hack/gen-appdef.py --check`.)
4. Add the bundle entry to
   `packages/core/platform/templates/bundles/paas.yaml`:
   ```
   {{include "cozystack.platform.package.full.default" (list "cozystack.n8n-application" $) }}
   ```
5. Optional / nice-to-have:
   - `api/apps/v1alpha1/n8n/types.go` + `zz_generated.deepcopy.go` (generated
     Go CRD types via `cozyvalues-gen` / `hack/update-crd.sh`). **Not required**
     for an external/tapped app: `cozystack-api` builds the resource
     dynamically from `openAPISchema`.
   - `n8ns` in `packages/system/cozystack-basics/templates/clusterroles.yaml` —
     **optional at v1.7.1** because `cozy:tenant:base` already grants the
     `apps.cozystack.io` wildcard.
   - `sidebar-icons.tsx` — optional; the dashboard has a generic fallback.
   - e2e tests.

The `Makefile`s inside `packages/apps/n8n/` and `packages/system/n8n-rd/`
`include ../../../hack/package.mk`. In the Cozystack source tree that file is
the real shared makefile. In this standalone repo `hack/package.mk` is a small
no-op shim so `make` does not fail; `cozypkg validate` never invokes `make`.

---

## Local verification reference

`cozypkg`, `flux` and the `helm-unittest` plugin are not required to work on
this repo. Everything below uses `helm`, `python3` (PyYAML + `jsonschema`) and
`git`:

```sh
./hack/verify.sh                                   # full local gate
python3 hack/gen-appdef.py --check                # AD is in sync with the schema
helm lint packages/apps/n8n
helm lint packages/system/n8n-rd
helm template n8n-test packages/apps/n8n --namespace tenant-test
helm template n8n-test packages/apps/n8n --namespace tenant-test \
  --set sandbox.enabled=true --set search.enabled=true
helm template n8n-test packages/apps/n8n --namespace tenant-test \
  --set sandbox.enabled=true --set search.enabled=true \
  --set _namespace.gateway=cozy-system --set _namespace.host=example.org
helm template test packages/system/n8n-rd        # renders the ApplicationDefinition
```

`hack/verify.py` also asserts that `spec.application.openAPISchema` equals
`values.schema.json`, that the two toggles are booleans defaulting to `false`,
that the schema does **not** set `additionalProperties: false` (injected
`_namespace`/`_cluster` must pass), and that the AD `chartRef` matches
`naming.ArtifactName`.

The `packages/apps/n8n/tests/*_test.yaml` files are `helm-unittest` suites;
run them with `helm unittest packages/apps/n8n` if you have the plugin
installed. They are kept as YAML-parseable specs and are checked for syntax by
`hack/verify.py`.

---

## Reference: exact deployment objects

| Object | Name |
|---|---|
| PackageSource / Package | `cozy-apps.n8n` |
| ApplicationDefinition | `n8n` (kind `N8N`, plural `n8ns`) |
| HelmRelease per instance | `n8n-<instance>` (prefix `n8n-`) |
| n8n Deployment + Service + PVC | `n8n-<instance>`, `n8n-<instance>-data` |
| Credentials Secret | `n8n-<instance>-credentials` |
| Code Sandbox | `n8n-<instance>-runner`, `n8n-<instance>-broker` |
| Search | `n8n-<instance>-search`, `n8n-<instance>-search-config` |
| Ingress / HTTPRoute | `n8n-<instance>-ingress` / `n8n-<instance>` |

The ApplicationDefinition's `secrets.include` and `services.include` selectors
use the same `n8n-{{ .name }}` style, so the Dashboard's Secrets/Services tabs
show exactly these objects.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Klugeshaus.

Everyone is free to **use**, **copy**, **modify**, **merge**, **publish**,
**distribute**, **sub-license** and **sell** copies of this repository and its
contents, with or without restriction, as long as the above copyright notice
and permission notice are kept intact. There is no copyleft obligation and no
attribution required beyond keeping the notice.

This project ships original Helm templates, YAML manifests, JSON Schema and
scripts; the third-party components it deploys (n8n, `n8nio/runners`, SearXNG)
are **not** part of this repository and remain under their own upstream
licenses (n8n's Sustainable Use License, SearXNG AGPL-3.0, and so on).
