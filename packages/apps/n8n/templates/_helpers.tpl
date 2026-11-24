{{/*
  Shared helpers for the n8n Marketplace application chart.

  The chart is intentionally self-contained: it does not depend on the
  cozy-lib chart, so `cozypkg validate --helm-lint` can lint it without
  staging libraries, and it can be dropped into the Cozystack source tree
  as-is. Injected Cozystack values (`_namespace`, `_cluster`) are always
  accessed through `default dict` so the chart also renders standalone.
*/}}

{{- define "n8n.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: n8n
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "n8n.selectorLabels" -}}
app.kubernetes.io/name: n8n
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
  Selectors for the n8n main pod ONLY. Use these for the main Deployment's
  matchLabels/pod labels, its Service, the task broker Service and the
  WorkloadMonitor. Kubernetes Service selectors are inclusive: reusing the
  generic n8n.selectorLabels would also match the task-runner and SearXNG
  pods (whose labels only differ by `app.kubernetes.io/component`).
*/}}
{{- define "n8n.mainSelectorLabels" -}}
{{- include "n8n.selectorLabels" . }}
app.kubernetes.io/component: main
{{- end -}}

{{/*
  External hostname. In a tenant namespace the injected
  _namespace.host is the tenant apex domain; the default hostname is
  <release>.<apex>. A standalone render (no _namespace) falls back to the
  release name so `helm lint`/`helm template` always produce valid YAML.
*/}}
{{- define "n8n.host" -}}
{{- $ns := .Values._namespace | default dict -}}
{{- $apex := $ns.host | default "" -}}
{{- if .Values.host -}}
{{- .Values.host -}}
{{- else if $apex -}}
{{- printf "%s.%s" .Release.Name $apex -}}
{{- else -}}
{{- .Release.Name -}}
{{- end -}}
{{- end -}}

{{/*
  Cozystack resource presets, reproduced from
  packages/library/cozy-lib/templates/_resourcepresets.tpl (v1.7.1).

  cozy-lib.resources.unsanitizedPreset maps a size (nano .. 4xlarge) and a
  series (t1, c1, s1, u1, m1) onto LIMITS:
    cpu:                 250m, 500m, 1, 2, 4, 8, 16, 32
    memory (t1 series):  128Mi, 256Mi, 512Mi, 1Gi, 2Gi, 4Gi, 8Gi, 16Gi
    series multiplier:   t1=1, c1=2, s1=4, u1=8, m1=16
    ephemeral-storage:   2Gi for every preset
  The deprecated flat aliases (nano, micro, small, medium, large, xlarge,
  2xlarge) keep their own historical CPU values (medium=1, large=2, ...).
  cozy-lib.resources.sanitize then derives REQUESTS from those limits:
    cpu = ceil(limit / 10), memory = limit,
    ephemeral-storage = int(limit / 40).
  defaultingSanitize merges explicit `.Values.resources` OVER the preset
  map before sanitizing, so explicit cpu/memory/ephemeral-storage win.

  This local equivalent keeps the chart self-contained; call with:
    include "n8n.resources" (dict "preset" .Values.resourcesPreset "explicit" .Values.resources)
*/}}
{{- define "n8n.resources.preset" -}}
{{- $cpu := dict "nano" "250m" "micro" "500m" "small" "1" "medium" "2" "large" "4" "xlarge" "8" "2xlarge" "16" "4xlarge" "32" -}}
{{- $memMi := dict "nano" 128 "micro" 256 "small" 512 "medium" 1024 "large" 2048 "xlarge" 4096 "2xlarge" 8192 "4xlarge" 16384 -}}
{{- $series := dict "t1" 1.0 "c1" 2.0 "s1" 4.0 "u1" 8.0 "m1" 16.0 -}}
{{- $legacy := dict
      "nano"    (dict "cpu" "250m" "memory" "128Mi")
      "micro"   (dict "cpu" "500m" "memory" "256Mi")
      "small"   (dict "cpu" "1"    "memory" "512Mi")
      "medium"  (dict "cpu" "1"    "memory" "1Gi")
      "large"   (dict "cpu" "2"    "memory" "2Gi")
      "xlarge"  (dict "cpu" "4"    "memory" "4Gi")
      "2xlarge" (dict "cpu" "8"    "memory" "8Gi") -}}
{{- $p := toString (.preset | default "t1.small") -}}
{{- $limits := dict "ephemeral-storage" "2Gi" -}}
{{- if hasKey $legacy $p -}}
{{- $limits = mergeOverwrite $limits (get $legacy $p) -}}
{{- else -}}
{{- $parts := splitList "." $p -}}
{{- $fam := "t1" -}}
{{- $size := "small" -}}
{{- if eq (len $parts) 2 -}}
{{- $fam = index $parts 0 -}}
{{- $size = index $parts 1 -}}
{{- else -}}
{{- $size = index $parts 0 -}}
{{- end -}}
{{- $factor := get $series $fam | default 1.0 -}}
{{- $mi := mulf (get $memMi $size | default 512) $factor -}}
{{- $gi := divf $mi 1024.0 -}}
{{- $mem := printf "%dMi" (int $mi) -}}
{{- if eq $gi (floor $gi) -}}
{{- $mem = printf "%dGi" (int $gi) -}}
{{- end -}}
{{- $limits = mergeOverwrite $limits (dict "cpu" (get $cpu $size | default "1") "memory" $mem) -}}
{{- end -}}
{{- toYaml $limits -}}
{{- end -}}

{{/* Parse a Kubernetes quantity into bytes (supports Ki/Mi/Gi/Ti, k/M/G, m). */}}
{{- define "n8n.resources.toBytes" -}}
{{- $q := toString . -}}
{{- $n := regexReplaceAll "[A-Za-z]" $q "" | float64 -}}
{{- $mult := 1.0 -}}
{{- if hasSuffix "Ki" $q -}}{{- $mult = 1024.0 -}}
{{- else if hasSuffix "Mi" $q -}}{{- $mult = 1048576.0 -}}
{{- else if hasSuffix "Gi" $q -}}{{- $mult = 1073741824.0 -}}
{{- else if hasSuffix "Ti" $q -}}{{- $mult = 1099511627776.0 -}}
{{- else if hasSuffix "k" $q -}}{{- $mult = 1000.0 -}}
{{- else if hasSuffix "M" $q -}}{{- $mult = 1000000.0 -}}
{{- else if hasSuffix "G" $q -}}{{- $mult = 1000000000.0 -}}
{{- else if hasSuffix "m" $q -}}{{- $mult = 0.001 -}}
{{- end -}}
{{- printf "%.0f" (mulf $n $mult) -}}
{{- end -}}

{{/* cpu request = ceil(cpu limit in millicores / 10). */}}
{{- define "n8n.resources.cpuRequest" -}}
{{- $q := toString . -}}
{{- $mc := 0.0 -}}
{{- if hasSuffix "m" $q -}}
{{- $mc = trimSuffix "m" $q | float64 -}}
{{- else -}}
{{- $mc = mulf ($q | float64) 1000.0 -}}
{{- end -}}
{{- printf "%dm" (int (ceil (divf $mc 10.0))) -}}
{{- end -}}

{{/* ephemeral-storage request = int(limit bytes / 40). */}}
{{- define "n8n.resources.ephemeralRequest" -}}
{{- $bytes := include "n8n.resources.toBytes" . | float64 -}}
{{- printf "%.0f" (floor (divf $bytes 40.0)) -}}
{{- end -}}

{{- define "n8n.resources" -}}
{{- $limits := include "n8n.resources.preset" (dict "preset" .preset) | fromYaml -}}
{{- $limits = mergeOverwrite $limits (.explicit | default dict) -}}
{{- $cpu := get $limits "cpu" -}}
{{- $mem := get $limits "memory" -}}
{{- $eph := get $limits "ephemeral-storage" -}}
limits:
  cpu: {{ $cpu | quote }}
  memory: {{ $mem | quote }}
  ephemeral-storage: {{ $eph | quote }}
requests:
  cpu: {{ include "n8n.resources.cpuRequest" $cpu | trim | quote }}
  memory: {{ $mem | quote }}
  ephemeral-storage: {{ include "n8n.resources.ephemeralRequest" $eph | trim | quote }}
{{- end -}}

{{/*
  Subjects for the dashboard resource RoleBinding. Equivalent to
  cozy-lib.rbac.subjectsForTenantAndAccessLevel (list "use" $namespace):
  ServiceAccount + use/admin/super-admin Groups for the tenant and every
  parent tenant, always including tenant-root. Non-tenant namespaces (e.g.
  a standalone `helm template`) get a single set of subjects for that
  namespace instead of failing.
*/}}
{{- define "n8n.rbac.subjects" -}}
{{- $ns := . -}}
{{- $tenants := list -}}
{{- if hasPrefix "tenant-" $ns -}}
{{- $parts := splitList "-" $ns -}}
{{- range $i := untilStep 2 (add (len $parts) 1 | int) 1 -}}
{{- $tenants = append $tenants (slice $parts 0 $i | join "-") -}}
{{- end -}}
{{- if not (has "tenant-root" $tenants) -}}
{{- $tenants = append $tenants "tenant-root" -}}
{{- end -}}
{{- else -}}
{{- $tenants = list $ns -}}
{{- end -}}
{{- range $t := $tenants }}
- kind: ServiceAccount
  name: {{ $t }}
  namespace: {{ $t }}
{{- range $l := list "use" "admin" "super-admin" }}
- kind: Group
  name: {{ printf "%s-%s" $t $l }}
  apiGroup: rbac.authorization.k8s.io
{{- end }}
{{- end }}
{{- end -}}
