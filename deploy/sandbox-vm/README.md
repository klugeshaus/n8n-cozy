# n8n Sandbox VM (opt-in, KubeVirt-backed)

This directory provisions a **dedicated Ubuntu VM** that hosts the whole
[n8n sandbox service](https://github.com/n8n-io/n8n-sandbox-service) — the
HTTP **API** plus a **privileged Docker-in-Docker (DinD) runner** — using
Cozystack's KubeVirt-backed Marketplace apps (`VMDisk` + `VMInstance`).
n8n, running as a normal pod in the cluster, points at the VM's API over
plain HTTP. This mirrors n8n docs **"Setup 3: Bundled sandbox"**.

```
n8n pod (in-cluster)  --plain HTTP :8080-->  sandbox-api  (Ubuntu VM)
                                              │  mTLS gRPC :9090 / :9091 (stays local to the VM)
                                              └─ sandbox-runner (privileged Docker-in-Docker)
```

## Why a VM instead of the in-chart sandbox?

The in-chart sandbox (`packages/apps/n8n/templates/sandbox.yaml`) can run its
runner either with **Sysbox** or **privileged**. On this cluster:

- Nodes run **Talos** with a **read-only rootfs**, so the Sysbox runtime
  **cannot be installed** — ever.
- `privileged: true` pods are a real containment risk: an escape from the
  runner container reaches the node.

A dedicated **VM** is therefore the only path to real isolation for the DinD
runner: the blast radius of a sandbox escape is the VM, not a node. Inside the
VM, API ↔ runner traffic is protected by **mutual TLS** that never leaves the
machine; n8n → API stays simple plain HTTP over the published port.

> This is an **opt-in** deployment of this MIT-licensed chart repo. The
> sandbox container images (`n8nio/n8n-sandbox-service-*`) themselves are
> subject to the **n8n Sustainable Use License** — see
> https://docs.n8n.io/license/ and the licensing notes in the top-level
> README. You do not need the in-chart sandbox (`sandbox.enabled`) when using
> this VM.

## Files

| File | Purpose |
|---|---|
| `vmdisk.yaml` | `VMDisk` CR — Ubuntu Noble qcow2 boot disk (40 GiB, `replicated`) |
| `vminstance.yaml` | `VMInstance` CR — `u1.medium` VM, cloud-init user-data inline |
| `cloud-init.yaml` | Readable standalone mirror of the `cloudInit` block (for review/validation; `vminstance.yaml` is what gets applied — keep them in sync) |

The cloud-init inside `vminstance.yaml` does everything on first boot:
installs `docker.io` + `docker-compose-v2`, writes `/opt/sandbox/.env`
(shared secrets), `/opt/sandbox/docker-compose.yml` (services `sandbox-api`
and `sandbox-runner`, exact env-var names copied from
`packages/apps/n8n/templates/sandbox.yaml` @ upstream `service/v1.16.0`) and
`/opt/sandbox/bootstrap-mtls.sh` (self-signed CA + the four mTLS leaf certs
mirroring the chart's four TLS Secrets), then starts the stack and marks
`/opt/sandbox/READY`. A `sandbox-compose.service` systemd unit re-runs
`docker compose up -d` on every boot, and both services use
`restart: unless-stopped`, so the VM survives reboots.

## Prerequisites

- Cozystack 1.7.x cluster with **KubeVirt + CDI healthy** and the
  `VMDisk` / `VMInstance` ApplicationDefinitions installed (standard on
  Cozystack 1.7).
- A **tenant namespace** (with its `cozystack-values` Secret) to deploy into;
  the VMDisk, VMInstance and the n8n app should live in the same namespace.
- An **Ubuntu cloud image URL** reachable from the cluster. The default
  (`https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img`)
  is a qcow2 image; the URL can be swapped for any qcow2/raw Ubuntu image —
  edit `vmdisk.yaml` accordingly. (CDI `DataSources`/`DataImportCrons` are
  empty on this cluster, so `source.http.url` is the reliable source;
  `image.name` references resolve to nothing.)
- **Capacity**: `u1.medium` = 4 vCPU / 4 GiB RAM, per the n8n sandbox docs.
- The nodes' `br_netfilter` settings are irrelevant *inside* the VM (the
  runner's Docker handles its own iptables there), but the VM's pod-network
  attachment assumes the cluster default networking is intact.
- `kubectl` with a context that can create these CRs in the target namespace.

## Step 0 — choose the admin API key (edit `vminstance.yaml` first)

The `.env` block inside the `cloudInit` scalar is written to
`/opt/sandbox/.env` on the VM. Set the admin key **before applying**:

1. Generate a long random string once (locally): `openssl rand -hex 24`
2. In `vminstance.yaml`, replace
   `SANDBOX_API_KEYS=CHANGE_ME_SANDBOX_ADMIN_KEY` with your value.
3. Use the **same value** below as `sandbox.external.apiKey` in the n8n chart
   values. This keeps both sides in lockstep — same pattern as the in-chart
   sandbox's `<release>-credentials` Secret.

If you leave the placeholder, `bootstrap-mtls.sh` generates a random admin key
on first boot and stores it (root-only) in `/opt/sandbox/.env` and
`/opt/sandbox/ADMIN_KEY.note`; you would then need SSH access to retrieve it
(see "Retrieving the key" below). Setting it explicitly is strongly preferred.

The two runner-facing secrets (`SANDBOX_API_RUNNER_REGISTRATION_TOKEN`,
`SANDBOX_API_RUNNER_API_KEY`) may stay as `CHANGE_ME_*` — they are shared only
between the two containers on the VM and are auto-generated on first boot.

## Step 1 — create the boot disk

```bash
kubectl -n <tenant-namespace> apply -f deploy/sandbox-vm/vmdisk.yaml
kubectl -n <tenant-namespace> get vmdisk n8n-sandbox-vmdisk -w
# wait until the disk import SUCCEEDED / phase Ready (CDI pulls the ~3 GiB
# image — takes a few minutes the first time)
```

## Step 2 — create the VM

```bash
kubectl -n <tenant-namespace> apply -f deploy/sandbox-vm/vminstance.yaml
kubectl -n <tenant-namespace> get vm,vmi -w   # KubeVirt VirtualMachine / VirtualMachineInstance
# wait for the VMI phase Running
```

First boot then takes a few minutes: cloud-init installs Docker, generates
the PKI, pulls the three sandbox images and starts the stack. Progress is in
the VM's console/serial log and `/var/log/cloud-init-output.log`.

## Step 3 — find the VM address and point n8n at it

Get the published external address:

```bash
kubectl -n <tenant-namespace> get vminstance n8n-sandbox-vm -o yaml
# look for the status fields with the external IP / host assigned by
# externalMethod: PortList (LB service / ingress behind Cozystack)
```

Then set the n8n chart values (`packages/apps/n8n`) in your Application:

```yaml
sandbox:
  external:
    enabled: true
    url: http://<vm-address>:8080   # plain HTTP; mTLS is only API<->runner
    apiKey: <the SANDBOX_API_KEYS value from Step 0>
  # in-chart sandbox must stay off:
  enabled: false
```

(Use the exact `sandbox.external.*` keys documented in the n8n app's
`values.schema.json` — that file is owned by a separate lane.)

### Networking caveats

- `external: true` + `externalMethod: PortList` + `externalPorts: [8080]`
  publishes the sandbox HTTP API through Cozystack's external access layer.
  Whether the resulting address (LB IP / DNS name) is **reachable from n8n
  pods** depends on your cluster's ingress/LB topology. If pods cannot reach
  the external address, add a `Service` (ExternalName or a selector-less
  service to the VMI) plus a DNS record, and point `sandbox.external.url` at
  that instead.
- Only **8080** is published by default. The mTLS gRPC ports (9090, 9091) and
  the runner's TLS :8080 are **not** published — API ↔ runner traffic stays
  local to the VM.
- Want SSH? Add `22` to `externalPorts` and put your public key(s) into
  `spec.sshKeys` in `vminstance.yaml`, then `ssh ubuntu@<vm-address>`.

### Retrieving the key if you left the placeholder

```bash
ssh ubuntu@<vm-address>                     # requires port 22 + sshKeys
sudo cat /opt/sandbox/.env                  # read SANDBOX_API_KEYS (or ADMIN_KEY.note)
```

Then use that value as `sandbox.external.apiKey` in the n8n values.

## Security caveats

- The VM runs a **privileged Docker-in-Docker** container. That is the point
  (real isolation from the cluster), but treat the VM as a root-equivalent
  workload: keep it single-purpose, patch the image periodically (re-import
  `vmdisk.yaml` with a newer image URL + fresh VM), and do not widen the
  published ports.
- Secrets live inside the VM: the admin/runner API keys in
  `/opt/sandbox/.env` (mode `0600`) and the TLS private keys under
  `/opt/sandbox/certs/` (keys `0600`). The `.env` content is also embedded in
  the `VMInstance` CR (`cloudInit` field) — anyone with read access to that CR
  (or to etcd) can see it. Scope RBAC accordingly.
- **Do not expose port 8080 to the public internet unauthenticated.** The
  sandbox API is guarded only by the API key. If the external address is
  internet-facing, front it with TLS + auth (or keep it cluster-internal).
- The self-signed PKI (`bootstrap-mtls.sh`) is generated **inside the VM** and
  is idempotent — it is never regenerated while `/opt/sandbox/certs/ca.crt`
  exists, so certificates don't rotate behind running containers (same policy
  as the in-chart sandbox's `lookup`-preserved Secrets). Regenerate by
  deleting `/opt/sandbox/certs/` and restarting the stack.
- To change user-data later (keys, ports, images), edit the `cloudInit` block
  in `vminstance.yaml` and **bump `cloudInitSeed`** (e.g. `...-v2`) so
  Cozystack re-propagates it to the VM; then restart the VM or run
  `cloud-init` re-execution on it. Note: secrets already generated inside
  `/opt/sandbox/.env` are preserved by the bootstrap script unless you wipe
  it.

## License

- This chart repo (and these manifests) are **MIT-licensed**.
- The sandbox images pulled by the VM
  (`n8nio/n8n-sandbox-service-api`, `-runner-dind`, `-sandbox`, tag `1.16.0`)
  are part of n8n and subject to the **n8n Sustainable Use License**
  (source-available; free for internal business use, not for offering n8n as
  a competing service). Review https://docs.n8n.io/license/ before use.

## Verification

```bash
kubectl -n <tenant-namespace> get vmdisk,vminstance

# inside the VM (or via SSH):
ssh ubuntu@<addr> 'docker compose -f /opt/sandbox/docker-compose.yml ps'
# -> sandbox-api  Up (healthy)
# -> sandbox-runner  Up

curl http://<addr>:8080/healthz
# -> {"status":"ok"}

# from a pod in the cluster, if the external address is not pod-reachable:
kubectl -n <tenant-namespace> run curl-test --rm -it --image=curlimages/curl -- \
  curl -s http://<addr>:8080/healthz
```

`/opt/sandbox/READY` on the VM is written once the stack came up; its
timestamp refreshes on every successful boot.

## Cleanup

```bash
kubectl -n <tenant-namespace> delete -f deploy/sandbox-vm/vminstance.yaml
kubectl -n <tenant-namespace> delete -f deploy/sandbox-vm/vmdisk.yaml
```

Deleting the `VMDisk` removes the boot disk (and its PVC-backed image). The
VM's runtime state (generated certs, secrets, logs) is lost with it —
re-applying regenerates everything, provided you set the admin key again (or
left the placeholder and are willing to fetch the newly generated one).
