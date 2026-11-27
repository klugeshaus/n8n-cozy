#!/usr/bin/env python3
"""Local verification for the n8n Cozystack External-Apps repo.

Re-implements the important `cozypkg validate` rules plus chart render checks
without needing cozypkg/flux/jq/yq. Runs from the repo root:

    python3 hack/verify.py

Prints one PASS/FAIL line per check, WARN/INFO lines for non-fatal findings,
a final `RESULT: N checks, M failures` line, and exits 1 if any check failed.
"""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parent.parent
APPS_CHART = REPO / "packages" / "apps" / "n8n"
RD_CHART = REPO / "packages" / "system" / "n8n-rd"
AD_PATH = RD_CHART / "cozyrds" / "n8n.yaml"
SCHEMA_PATH = APPS_CHART / "values.schema.json"
VALUES_PATH = APPS_CHART / "values.yaml"
SOURCES_DIR = REPO / "packages" / "core" / "platform" / "sources"

RESERVED_PS_PREFIXES = ("cozystack.", "community.")
VALID_SOURCE_REF_KINDS = {"GitRepository", "OCIRepository"}

_failures = 0
_checks = 0


def warn(msg: str) -> None:
    print(f"WARN  {msg}")


def info(msg: str) -> None:
    print(f"INFO  {msg}")


def run_check(name: str, fn) -> None:
    """Run a check function; it calls ok()/fail() on the Check helper."""
    global _failures, _checks
    _checks += 1
    c = Check(name)
    try:
        fn(c)
    except Exception as exc:  # noqa: BLE001 - keep verifying other checks
        c.fail(f"unexpected error: {type(exc).__name__}: {exc}")
    if not c.failed:
        print(f"PASS  {name}: {c.detail}")


class Check:
    def __init__(self, name: str):
        self.name = name
        self.detail = "ok"
        self.failed = False

    def ok(self, detail: str) -> None:
        if not self.failed:
            self.detail = detail

    def fail(self, msg: str) -> None:
        global _failures
        self.failed = True
        _failures += 1
        print(f"FAIL  {self.name}: {msg}")


def load_all_docs(path: Path):
    """Parse a YAML file into a list of non-empty documents."""
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def artifact_name(ps_name: str, variant: str, component: str) -> str:
    """naming.ArtifactName equivalent (cozypkg naming rules)."""
    return (ps_name.replace(".", "-") + "-" + variant.replace(".", "-")
            + "-" + component.replace(".", "-"))


def helm(args, cwd: Path = REPO):
    return subprocess.run(["helm", *args], capture_output=True, text=True, cwd=cwd)


# --------------------------------------------------------------------------
# 1. PackageSource
# --------------------------------------------------------------------------
def check_packagesource(c: Check):
    files = sorted(SOURCES_DIR.rglob("*.yaml")) if SOURCES_DIR.is_dir() else []
    sources = []
    for f in files:
        for doc in load_all_docs(f):
            if doc.get("apiVersion") == "cozystack.io/v1alpha1" and doc.get("kind") == "PackageSource":
                sources.append((f, doc))
    if len(sources) < 1:
        c.fail(f"no PackageSource documents found under {SOURCES_DIR.relative_to(REPO)}")
        return

    for f, ps in sources:
        rel = f.relative_to(REPO)
        name = (ps.get("metadata") or {}).get("name") or ""
        if not name:
            c.fail(f"{rel}: PackageSource metadata.name is empty")
            continue
        if name.startswith(RESERVED_PS_PREFIXES):
            c.fail(f"{rel}: reserved PackageSource name prefix: {name!r}")

        sr = ((ps.get("spec") or {}).get("sourceRef") or {})
        if sr.get("kind") not in VALID_SOURCE_REF_KINDS:
            c.fail(f"{rel}: spec.sourceRef.kind must be one of "
                   f"{sorted(VALID_SOURCE_REF_KINDS)}, got {sr.get('kind')!r}")

        variants = (ps.get("spec") or {}).get("variants") or []
        if len(variants) < 1:
            c.fail(f"{rel}: PackageSource {name} has no variants")
            continue

        vnames = [v.get("name") or "" for v in variants]
        if any(not n for n in vnames):
            c.fail(f"{rel}: PackageSource {name} has a variant with an empty name")
        dupes = {n for n in vnames if n and vnames.count(n) > 1}
        if dupes:
            c.fail(f"{rel}: duplicate variant names: {sorted(dupes)}")

        for v in variants:
            vname = v.get("name") or "<unnamed>"
            # Upstream PackageSource API: Variant.Libraries is []Library{name,path};
            # Component.Libraries is []string of library NAMES (not paths).
            # validate.go keys the declared set by library name, falling back to
            # filepath.Base(path) when no explicit name is given.
            vlib_names = set()
            vlib_paths = set()
            for lib in (v.get("libraries") or []):
                if isinstance(lib, str):
                    vlib_names.add(lib)
                    continue
                if not isinstance(lib, dict):
                    continue
                lib_path = lib.get("path") or ""
                if lib_path:
                    vlib_paths.add(lib_path)
                lib_name = lib.get("name") or Path(lib_path).name
                if lib_name:
                    vlib_names.add(lib_name)
            for lib_path in sorted(vlib_paths):
                if not (REPO / "packages" / lib_path).is_dir():
                    c.fail(f"{rel}: variant {vname}: declared library path "
                           f"{lib_path} does not exist under packages/")
            comps = v.get("components") or []
            cnames = [comp.get("name") or "" for comp in comps]
            if any(not n for n in cnames):
                c.fail(f"{rel}: variant {vname}: component with empty name")
            cdupes = {n for n in cnames if n and cnames.count(n) > 1}
            if cdupes:
                c.fail(f"{rel}: variant {vname}: duplicate component names: {sorted(cdupes)}")
            for comp in comps:
                cname = comp.get("name") or "<unnamed>"
                cpath = comp.get("path") or ""
                chart = REPO / "packages" / cpath / "Chart.yaml"
                if not cpath or not chart.is_file():
                    c.fail(f"{rel}: variant {vname}: component {cname}: path {cpath!r} "
                           f"does not resolve to a directory containing Chart.yaml")
                for lib_name in (comp.get("libraries") or []):
                    if lib_name not in vlib_names:
                        c.fail(f"{rel}: variant {vname}: component {cname}: "
                               f"library {lib_name!r} not declared at variant level")
                install = comp.get("install") or {}
                if install.get("privileged") is True:
                    warn(f"{name}/{vname}/{cname}: install.privileged=true "
                         f"(privileged package; review required)")

            for dep in (v.get("dependsOn") or []):
                dep_name = dep if isinstance(dep, str) else (dep.get("name") or "")
                if dep_name.startswith("cozystack."):
                    info(f"{name}/{vname}: unresolved dependsOn {dep_name} (core package)")
                else:
                    warn(f"{name}/{vname}: unresolved dependsOn {dep_name}")

    # cozypkg validate normalizes dots to dashes over every
    # (variant, component) pair and rejects colliding artifact names.
    seen_artifacts = {}
    for f, ps in sources:
        ps_name = ps["metadata"]["name"]
        for v in (ps.get("spec") or {}).get("variants") or []:
            for comp in v.get("components") or []:
                vname = v.get("name") or ""
                cname = comp.get("name") or ""
                if not vname or not cname:
                    continue
                an = artifact_name(ps_name, vname, cname)
                if an in seen_artifacts:
                    c.fail(f"artifact-name collision: {an!r} produced by both "
                           f"{seen_artifacts[an]} and {ps_name}/{vname}/{cname}")
                else:
                    seen_artifacts[an] = f"{ps_name}/{vname}/{cname}"

    c.ok(f"{len(sources)} PackageSource ({', '.join(ps['metadata']['name'] for _, ps in sources)})")


# --------------------------------------------------------------------------
# 2. Artifact naming + chartRef wiring
# --------------------------------------------------------------------------
def check_artifact_naming(c: Check):
    ps_name, variant, component = "cozy-apps.n8n", "default", "n8n"
    expected = artifact_name(ps_name, variant, component)
    if expected != "cozy-apps-n8n-default-n8n":
        c.fail(f"ArtifactName('cozy-apps.n8n','default','n8n') = {expected!r}, "
               f"expected 'cozy-apps-n8n-default-n8n'")
        return

    docs = load_all_docs(AD_PATH)
    ad = next((d for d in docs if d.get("kind") == "ApplicationDefinition"), None)
    if ad is None:
        c.fail(f"{AD_PATH.relative_to(REPO)}: no ApplicationDefinition document")
        return
    chart_ref = ((ad.get("spec") or {}).get("release") or {}).get("chartRef")
    if not chart_ref:
        c.fail("spec.release.chartRef is nil/missing")
        return
    if chart_ref.get("kind") != "ExternalArtifact":
        c.fail(f"release.chartRef.kind = {chart_ref.get('kind')!r}, expected 'ExternalArtifact'")
    if chart_ref.get("name") != expected:
        c.fail(f"release.chartRef.name = {chart_ref.get('name')!r}, expected {expected!r}")
    if chart_ref.get("namespace") != "cozy-system":
        c.fail(f"release.chartRef.namespace = {chart_ref.get('namespace')!r}, expected 'cozy-system'")
    c.ok(f"chartRef -> ExternalArtifact/{expected} in cozy-system")


# --------------------------------------------------------------------------
# 3. Strict YAML decode
# --------------------------------------------------------------------------
def check_strict_yaml(c: Check):
    roots = [REPO / "packages", REPO / "deploy"]
    files = sorted({f for root in roots if root.is_dir() for f in root.rglob("*.yaml")})
    parsed, skipped = 0, []
    for f in files:
        rel = f.relative_to(REPO)
        # Helm templates are not valid YAML; skip packages/**/templates/*.yaml.
        # cozyrds/*.yaml is plain YAML and MUST be parsed (its `{{ .name }}`
        # literals live inside quoted/plain string values).
        if "templates" in f.parts and f.name.endswith(".yaml") and (REPO / "packages") in f.parents:
            skipped.append(rel)
            continue
        try:
            list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            c.fail(f"{rel}: strict YAML decode failed: "
                   f"{str(exc).splitlines()[0] if str(exc) else type(exc).__name__}")
            continue
        parsed += 1
    c.ok(f"{parsed} YAML files strict-decoded "
         f"({len(skipped)} helm template files skipped)")


# --------------------------------------------------------------------------
# 4. ApplicationDefinition contract
# --------------------------------------------------------------------------
TABS_ALLOWED = {"workloads", "ingresses", "services", "secrets", "yaml"}
CHART_RESOURCE_PATTERNS_SERVICES = [
    "n8n-{{ .name }}",
    "n8n-{{ .name }}-sandbox",
    "n8n-{{ .name }}-sandbox-runner",
    "n8n-{{ .name }}-search",
]
CHART_RESOURCE_PATTERNS_SECRETS = [
    "n8n-{{ .name }}-credentials",
    "n8n-{{ .name }}-search-config",
    "n8n-{{ .name }}-sandbox-auth",
    "n8n-{{ .name }}-sandbox-ca",
    "n8n-{{ .name }}-sandbox-tls-api-registration",
    "n8n-{{ .name }}-sandbox-tls-api-control-client",
    "n8n-{{ .name }}-sandbox-tls-runner-registration",
    "n8n-{{ .name }}-sandbox-tls-runner-control-server",
]
CHART_RESOURCE_PATTERNS_INGRESSES = ["n8n-{{ .name }}-ingress"]


def check_appdef(c: Check):
    docs = load_all_docs(AD_PATH)
    ad = next((d for d in docs if d.get("kind") == "ApplicationDefinition"), None)
    if ad is None:
        c.fail(f"{AD_PATH.relative_to(REPO)}: no ApplicationDefinition document")
        return
    rel = AD_PATH.relative_to(REPO)
    if ad.get("apiVersion") != "cozystack.io/v1alpha1":
        c.fail(f"{rel}: apiVersion = {ad.get('apiVersion')!r}")
    if (ad.get("metadata") or {}).get("name") != "n8n":
        c.fail(f"{rel}: metadata.name = {(ad.get('metadata') or {}).get('name')!r}, expected 'n8n'")

    spec = ad.get("spec") or {}
    app = spec.get("application") or {}
    if app.get("kind") != "N8N":
        c.fail(f"spec.application.kind = {app.get('kind')!r}, expected 'N8N'")
    if app.get("plural") != "n8ns":
        c.fail(f"spec.application.plural = {app.get('plural')!r}, expected 'n8ns'")
    if app.get("singular") != "n8n":
        c.fail(f"spec.application.singular = {app.get('singular')!r}, expected 'n8n'")

    release = spec.get("release") or {}
    prefix = release.get("prefix")
    if not isinstance(prefix, str) or not re.fullmatch(r"[a-z0-9-]*", prefix):
        c.fail(f"spec.release.prefix = {prefix!r} must match ^[a-z0-9-]*$ (dot-free)")

    dash = spec.get("dashboard") or {}
    if dash.get("category") != "PaaS":
        c.fail(f"spec.dashboard.category = {dash.get('category')!r}, expected 'PaaS'")

    icon = dash.get("icon") or ""
    try:
        decoded = base64.b64decode(icon, validate=True)
        head = decoded.lstrip()[:5]
        if not (head.startswith(b"<?xml") or head.startswith(b"<svg")):
            c.fail("spec.dashboard.icon does not decode to an XML/SVG document")
    except Exception as exc:  # noqa: BLE001
        c.fail(f"spec.dashboard.icon is not valid base64: {exc}")

    tabs = dash.get("tabs")
    if not isinstance(tabs, list) or not set(tabs).issubset(TABS_ALLOWED):
        c.fail(f"spec.dashboard.tabs = {tabs!r} not a subset of {sorted(TABS_ALLOWED)}")

    keys_order = dash.get("keysOrder")
    if not isinstance(keys_order, list) or not all(isinstance(e, list) for e in keys_order):
        c.fail("spec.dashboard.keysOrder must be a list of lists")

    # secrets/services include resourceNames must match chart resource names
    secrets_include = (spec.get("secrets") or {}).get("include")
    if not isinstance(secrets_include, list):
        c.fail("spec.secrets.include is missing")
    else:
        names = [n for entry in secrets_include for n in (entry.get("resourceNames") or [])]
        for pat in CHART_RESOURCE_PATTERNS_SECRETS:
            if pat not in names:
                c.fail(f"spec.secrets.include resourceNames missing {pat!r} (chart resource)")

    services_include = (spec.get("services") or {}).get("include")
    if not isinstance(services_include, list):
        c.fail("spec.services.include is missing")
    else:
        names = [n for entry in services_include for n in (entry.get("resourceNames") or [])]
        for pat in CHART_RESOURCE_PATTERNS_SERVICES:
            if pat not in names:
                c.fail(f"spec.services.include resourceNames missing {pat!r} (chart resource)")

    # The dashboard declares the `ingresses` tab, so spec.ingresses must have
    # include selectors; an empty include hides the Ingress from the tenant.
    ingresses_include = (spec.get("ingresses") or {}).get("include")
    if not isinstance(ingresses_include, list) or not ingresses_include:
        c.fail("spec.ingresses.include is missing but spec.dashboard.tabs lists 'ingresses'")
    else:
        names = [n for entry in ingresses_include for n in (entry.get("resourceNames") or [])]
        for pat in CHART_RESOURCE_PATTERNS_INGRESSES:
            if pat not in names:
                c.fail(f"spec.ingresses.include resourceNames missing {pat!r} (chart resource)")

    c.ok(f"{rel}: ApplicationDefinition n8n (kind N8N, PaaS dashboard, "
         f"{len(keys_order or [])} keysOrder entries)")


# --------------------------------------------------------------------------
# 5. openAPISchema sync
# --------------------------------------------------------------------------
def check_openapi_schema(c: Check):
    ad = load_all_docs(AD_PATH)[0]
    app = (ad.get("spec") or {}).get("application") or {}
    raw = app.get("openAPISchema")
    if not isinstance(raw, str):
        c.fail("spec.application.openAPISchema must be a JSON string")
        return
    try:
        embedded = json.loads(raw)
    except json.JSONDecodeError as exc:
        c.fail(f"openAPISchema is not valid JSON: {exc}")
        return
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if embedded != on_disk:
        c.fail("openAPISchema differs from values.schema.json "
               "(run: python3 hack/gen-appdef.py)")
        return

    if embedded.get("type") != "object":
        c.fail(f"schema root type = {embedded.get('type')!r}, expected 'object'")
    props = embedded.get("properties") or {}
    for key in ("sandbox", "search"):
        sub = props.get(key)
        if not isinstance(sub, dict):
            c.fail(f"schema root properties missing {key!r}")
            continue
        enabled = (sub.get("properties") or {}).get("enabled")
        if not isinstance(enabled, dict):
            c.fail(f"schema {key}.properties.enabled missing")
            continue
        if enabled.get("type") != "boolean":
            c.fail(f"schema {key}.enabled.type = {enabled.get('type')!r}, expected 'boolean'")
        if enabled.get("default") is not False:
            c.fail(f"schema {key}.enabled.default = {enabled.get('default')!r}, expected false")
    if embedded.get("additionalProperties") is False:
        c.fail("schema root sets additionalProperties: false - injected "
               "_namespace/_cluster values would be rejected")
    c.ok("openAPISchema == values.schema.json (sandbox/search toggles, "
         "no additionalProperties:false)")


# --------------------------------------------------------------------------
# 6. values.yaml <-> values.schema.json consistency
# --------------------------------------------------------------------------
def check_values_schema(c: Check):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    values = yaml.safe_load(VALUES_PATH.read_text(encoding="utf-8")) or {}
    try:
        jsonschema.validate(values, schema)
    except jsonschema.ValidationError as exc:
        c.fail(f"values.yaml does not validate against values.schema.json: "
               f"{exc.message} (path: {list(exc.absolute_path)})")
        return
    vkeys = set(values.keys())
    skeys = set((schema.get("properties") or {}).keys())
    missing_in_values = sorted(skeys - vkeys)
    undeclared = sorted(vkeys - skeys)
    if missing_in_values:
        c.fail(f"schema properties missing from values.yaml: {missing_in_values}")
    if undeclared:
        c.fail(f"values.yaml keys not declared in schema: {undeclared}")

    # The Marketplace form is generated from this schema. On clusters without a
    # Sysbox node pool (e.g. Talos) the shipped defaults MUST be schedulable,
    # otherwise every fresh Deploy times out waiting for the runner StatefulSet.
    runner = (schema["properties"]["sandbox"]["properties"]["runner"]
              ["properties"])
    expected_defaults = {
        "isolation": "privileged",
        "acknowledgePrivileged": True,
        "nodeSelector": {},
        "tolerations": [],
    }
    for key, want in expected_defaults.items():
        got = runner[key].get("default")
        if got != want:
            c.fail(f"sandbox.runner.{key} default = {got!r}, expected {want!r} "
                   f"(fresh Marketplace deploys must be schedulable without Sysbox)")
    # The structural CRD generator rejects arrays without an items schema.
    if "items" not in runner["tolerations"]:
        c.fail("sandbox.runner.tolerations lost its 'items' schema "
               "(structural CRD generation would reject the injected default)")
    c.ok(f"values.yaml validates; {len(vkeys)} top-level keys == schema properties; "
         f"runner defaults are portable (privileged)")


# --------------------------------------------------------------------------
# 7. helm lint
# --------------------------------------------------------------------------
def check_helm_lint(c: Check):
    for chart in (APPS_CHART, RD_CHART):
        rel = chart.relative_to(REPO)
        proc = helm(["lint", str(chart)])
        if proc.returncode != 0:
            c.fail(f"helm lint {rel} failed (rc={proc.returncode})\n{proc.stdout}{proc.stderr}")
            return
    c.ok("helm lint packages/apps/n8n, packages/system/n8n-rd (0 errors)")


# --------------------------------------------------------------------------
# 8. helm template render matrix
# --------------------------------------------------------------------------
def render_docs(c: Check, *set_args):
    proc = helm(["template", "n8n-test", str(APPS_CHART), "--namespace", "tenant-test",
                 *set_args])
    if proc.returncode != 0:
        c.fail(f"helm template failed for args {list(set_args)} "
               f"(rc={proc.returncode})\n{proc.stdout}{proc.stderr}")
        return None
    try:
        return [d for d in yaml.safe_load_all(proc.stdout) if d]
    except yaml.YAMLError as exc:
        c.fail(f"helm template output not parseable as YAML for args {list(set_args)}: {exc}")
        return None


def by_name(docs, kind, name):
    return next((d for d in docs if d.get("kind") == kind
                 and (d.get("metadata") or {}).get("name") == name), None)


def pod_labels(doc):
    return ((doc.get("spec") or {}).get("template") or {}).get("metadata", {}).get("labels") or {}


def service_selector(doc):
    return (doc.get("spec") or {}).get("selector") or {}


def container_resources(doc, container="n8n"):
    for cont in ((doc.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers", []):
        if cont.get("name") == container:
            return cont.get("resources") or {}
    return {}


def container_probes(doc, container="n8n"):
    """Return the probe dict of a named container in a Deployment doc."""
    for cont in ((doc.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers", []):
        if cont.get("name") == container:
            return {k: cont.get(k) for k in ("startupProbe", "readinessProbe", "livenessProbe")}
    return {}


def doc_names(docs, kind):
    return sorted(d["metadata"]["name"] for d in docs
                  if d.get("kind") == kind and isinstance(d.get("metadata"), dict))


def image_tag(doc):
    for cont in ((doc.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers", []):
        img = cont.get("image") or ""
        if ":" in img:
            return img.rsplit(":", 1)[1]
    return None


def check_render_matrix(c: Check):
    """Render the chart across the toggle combinations and assert the
    structural contract of the n8n sandbox service (Setup 1).

    Counts are derived from the chart, not guessed: default 8 docs; enabling
    the sandbox adds the CA + 4 leaf TLS Secrets, the auth Secret, the API
    ConfigMap/Service/Deployment/PVC and the runner Service/StatefulSet;
    enabling search adds its Secret/Service/Deployment.
    """
    # Sprig buildCustomCert takes base64-encoded PEM and decodes it internally.
    # Secret.data values are already base64, so b64dec before the call breaks
    # every upgrade after the first install (lookup finds the CA Secret).
    tls_src = (APPS_CHART / "templates" / "sandbox.yaml").read_text(encoding="utf-8")
    if re.search(r"buildCustomCert[^\n]*b64dec", tls_src):
        c.fail("sandbox.yaml decodes PEM before buildCustomCert; it expects raw base64")
    if re.search(r"\{\{- with \.Values\.sandbox\.runner\.nodeSelector \}\}", tls_src) \
            and "eq .Values.sandbox.runner.isolation \"sysbox\"" not in tls_src:
        c.fail("runner nodeSelector is not gated on sysbox isolation (strands privileged runners)")
    # The CA + 4 leaf Secrets MUST be emitted on EVERY render, otherwise Helm
    # deletes them on the second upgrade (lookup finds them -> omitted) and the
    # runner pod fails with MountVolume.SetUp secret not found.
    if "TLS-ALWAYS-EMIT" not in tls_src:
        c.fail("sandbox.yaml lost the TLS-ALWAYS-EMIT marker (unconditional TLS Secret emission)")
    if re.search(r"\{\{-?\s*if \$genCA\s*\}\}", tls_src):
        c.fail("sandbox.yaml still gates the CA Secret emission on $genCA")
    if re.search(r"\{\{-?\s*if not \$existing\s*\}\}", tls_src):
        c.fail("sandbox.yaml still gates leaf Secret emission on $existing")

    cases = [
        ("default", (), 8),
        ("sandbox", ("--set", "sandbox.enabled=true"), 20),
        ("search", ("--set", "search.enabled=true"), 11),
        ("sandbox+search", ("--set", "sandbox.enabled=true", "--set", "search.enabled=true"), 23),
        ("namespaces", ("--set", "sandbox.enabled=true", "--set", "search.enabled=true",
                        "--set", "_namespace.gateway=cozy-system",
                        "--set", "_namespace.ingress=nginx",
                        "--set", "_namespace.host=example.org"), 23),
        ("wildcard", ("--set", "_cluster.wildcard-secret-name=wildcard-tls"), 8),
        ("preset", ("--set", "resourcesPreset=t1.medium"), 8),
        ("external", ("--set", "sandbox.enabled=true",
                      "--set", "sandbox.external.enabled=true",
                      "--set", "sandbox.external.url=http://10.244.1.50:8080",
                      "--set", "sandbox.external.apiKey=test-key-123",
                      "--set", "search.enabled=true"), 11),
        # Opt-in sysbox mode must still render the RuntimeClass + node selector
        # even though the shipped default is now portable privileged isolation.
        ("sysbox", ("--set", "sandbox.enabled=true",
                    "--set", "sandbox.runner.isolation=sysbox",
                    "--set", "sandbox.runner.nodeSelector.sysbox-install=yes"), 20),
    ]
    rendered = {}
    for label, args, expected in cases:
        docs = render_docs(c, *args)
        if docs is None:
            return
        rendered[label] = docs
        if len(docs) != expected:
            c.fail(f"case {label}: expected {expected} docs, got {len(docs)}")
            return

    sandbox_env = {
        "N8N_INSTANCE_AI_SANDBOX_ENABLED": "true",
        "N8N_INSTANCE_AI_SANDBOX_PROVIDER": "n8n-sandbox",
        "N8N_SANDBOX_SERVICE_URL": "http://n8n-test-sandbox:8080",
        "N8N_SANDBOX_SERVICE_API_KEY": None,  # secretKeyRef, checked separately
    }

    def main_env(docs):
        dep = by_name(docs, "Deployment", "n8n-test")
        if dep is None:
            return {}
        out = {}
        for e in (((dep.get("spec") or {}).get("template") or {}).get("spec", {})
                  .get("containers", [{}])[0].get("env", [])):
            out[e.get("name")] = e
        return out

    def raw_contains(docs, needle):
        return needle in yaml.safe_dump_all([d for d in docs if d])

    # a) default: baseline kinds, no HTTPRoute, exactly one Ingress, no sandbox
    default = rendered["default"]
    kinds = {d.get("kind") for d in default}
    required = {"Secret", "PersistentVolumeClaim", "Role", "RoleBinding",
                "Service", "Deployment", "Ingress", "WorkloadMonitor"}
    if not required.issubset(kinds):
        c.fail(f"default render missing kinds: {sorted(required - kinds)}")
    if any(k == "HTTPRoute" for k in kinds):
        c.fail("default render must not contain an HTTPRoute")
    if sum(1 for d in default if d.get("kind") == "Ingress") != 1:
        c.fail("default render must contain exactly one Ingress")
    if raw_contains(default, "N8N_RUNNERS") or raw_contains(default, "n8n-test-broker"):
        c.fail("default render still contains task-runner / broker references")
    for name in sandbox_env:
        if name in main_env(default):
            c.fail(f"default render must not set {name} when sandbox.enabled=false")
    if any("sandbox" in (d.get("metadata", {}).get("name") or "") for d in default):
        c.fail("default render must not contain any sandbox-* object")

    # a2) cold-boot probes: n8n main + SearXNG must gate readiness/liveness
    # behind a startupProbe so slow first boots do not emit Unhealthy events.
    both = rendered["sandbox+search"]
    for deploy_name, cont in (("n8n-test", "n8n"), ("n8n-test-search", "searxng")):
        dep = by_name(both, "Deployment", deploy_name)
        probes = container_probes(dep or {}, cont)
        sp = probes.get("startupProbe") or {}
        if not sp:
            c.fail(f"{deploy_name}/{cont} is missing startupProbe (cold-boot Unhealthy events)")
        elif ((sp.get("httpGet") or {}).get("path") != "/healthz"
              or (sp.get("httpGet") or {}).get("port") != "http"):
            c.fail(f"{deploy_name}/{cont} startupProbe must hit /healthz on port http")
        for p in ("readinessProbe", "livenessProbe"):
            if (probes.get(p) or {}).get("initialDelaySeconds") is not None:
                c.fail(f"{deploy_name}/{cont} {p} still sets initialDelaySeconds "
                       "(startupProbe should gate it)")

    # b) sandbox-on object set
    sandbox = rendered["sandbox"]
    tls_names = [
        "n8n-test-sandbox-ca",
        "n8n-test-sandbox-tls-api-registration",
        "n8n-test-sandbox-tls-api-control-client",
        "n8n-test-sandbox-tls-runner-registration",
        "n8n-test-sandbox-tls-runner-control-server",
    ]
    expected_objs = (
        [("Secret", n) for n in tls_names]
        + [("Secret", "n8n-test-sandbox-auth"),
           ("ConfigMap", "n8n-test-sandbox-config"),
           ("Service", "n8n-test-sandbox"),
           ("Deployment", "n8n-test-sandbox"),
           ("PersistentVolumeClaim", "n8n-test-sandbox-data"),
           ("Service", "n8n-test-sandbox-runner"),
           ("StatefulSet", "n8n-test-sandbox-runner")]
    )
    for kind, name in expected_objs:
        if by_name(sandbox, kind, name) is None:
            c.fail(f"sandbox case: missing {kind} named {name}")
    for n in tls_names:
        sec = by_name(sandbox, "Secret", n)
        if sec is None:
            continue
        data = sec.get("data") or {}
        # The CA Secret holds only the CA keypair; leaf Secrets additionally
        # carry ca.crt so that the API and runner can verify each other.
        required = ("tls.crt", "tls.key") if n.endswith("-ca") else ("tls.crt", "tls.key", "ca.crt")
        for key in required:
            if not data.get(key):
                c.fail(f"sandbox TLS Secret {n} is missing data.{key}")
    creds = by_name(sandbox, "Secret", "n8n-test-credentials")
    if creds is None or not (creds.get("data") or {}).get("SANDBOX_API_KEY"):
        c.fail("credentials Secret must carry SANDBOX_API_KEY (single source of truth)")
    if not (creds.get("data") or {}).get("N8N_ENCRYPTION_KEY"):
        c.fail("credentials Secret must still carry N8N_ENCRYPTION_KEY")

    # c) n8n env wiring (on) and no legacy runner vars anywhere
    on_env = main_env(sandbox)
    for name, value in sandbox_env.items():
        if name not in on_env:
            c.fail(f"sandbox case: n8n main is missing {name}")
        elif value is not None and on_env[name].get("value") != value:
            c.fail(f"sandbox case: {name} = {on_env[name].get('value')!r}, expected {value!r}")
    key_ref = ((on_env.get("N8N_SANDBOX_SERVICE_API_KEY") or {}).get("valueFrom") or {})
    if key_ref.get("secretKeyRef", {}).get("key") != "SANDBOX_API_KEY":
        c.fail("N8N_SANDBOX_SERVICE_API_KEY must reference the SANDBOX_API_KEY secret key")
    if raw_contains(sandbox, "N8N_RUNNERS") or raw_contains(sandbox, "n8n-test-broker"):
        c.fail("sandbox render still contains task-runner / broker references")

    # d) sandbox + search
    both = rendered["sandbox+search"]
    for kind, name in (("Service", "n8n-test-search"),
                       ("Deployment", "n8n-test-search"),
                       ("Secret", "n8n-test-search-config")):
        if by_name(both, kind, name) is None:
            c.fail(f"sandbox+search case: missing {kind} named {name}")
    sec = by_name(both, "Secret", "n8n-test-search-config")
    if sec is not None and "json" not in ((sec.get("stringData") or {}).get("settings.yml") or ""):
        c.fail("search-config settings.yml does not enable the SearXNG JSON API")

    # e) gateway namespace overrides switch Ingress -> HTTPRoute
    ns = rendered["namespaces"]
    if not any(d.get("kind") == "HTTPRoute" for d in ns):
        c.fail("namespaces case: expected a gateway.networking.k8s.io HTTPRoute, none found")
    if any(d.get("kind") == "Ingress" for d in ns):
        c.fail("namespaces case: must not render a networking.k8s.io Ingress when "
               "_namespace.gateway is set")

    # f) Service selectors must target only their own pods. Inclusive selectors
    #    would otherwise load-balance the main UI onto sandbox/search pods.
    main_svc = by_name(both, "Service", "n8n-test")
    sandbox_svc = by_name(both, "Service", "n8n-test-sandbox")
    runner_svc = by_name(both, "Service", "n8n-test-sandbox-runner")
    search_svc = by_name(both, "Service", "n8n-test-search")
    main_dep = by_name(both, "Deployment", "n8n-test")
    api_dep = by_name(both, "Deployment", "n8n-test-sandbox")
    runner_sts = by_name(both, "StatefulSet", "n8n-test-sandbox-runner")
    search_dep = by_name(both, "Deployment", "n8n-test-search")
    for svc, label, expected in ((main_svc, "main Service", "main"),
                                 (sandbox_svc, "sandbox API Service", "sandbox-api"),
                                 (runner_svc, "runner Service", "sandbox-runner"),
                                 (search_svc, "search Service", "search")):
        if svc is None:
            c.fail(f"{label} missing from sandbox+search render")
        elif service_selector(svc).get("app.kubernetes.io/component") != expected:
            c.fail(f"{label} selector must include app.kubernetes.io/component: {expected} "
                   f"(got {service_selector(svc)!r})")
    for obj, label, expected in ((main_dep, "main", "main"),
                                 (api_dep, "sandbox API", "sandbox-api"),
                                 (runner_sts, "sandbox runner", "sandbox-runner"),
                                 (search_dep, "search", "search")):
        if obj is None:
            c.fail(f"{label} workload missing from sandbox+search render")
        elif pod_labels(obj).get("app.kubernetes.io/component") != expected:
            c.fail(f"{label} pod labels must include app.kubernetes.io/component: {expected} "
                   f"(got {pod_labels(obj)!r})")

    # g) Cozystack resource-preset matrix (t1.small default)
    res = container_resources(main_dep or {})
    exp_limits = {"cpu": "1", "memory": "512Mi", "ephemeral-storage": "2Gi"}
    exp_requests = {"cpu": "100m", "memory": "512Mi"}
    if res.get("limits") != exp_limits:
        c.fail(f"default main resources.limits = {res.get('limits')!r}, expected {exp_limits!r}")
    for k, v in exp_requests.items():
        if (res.get("requests") or {}).get(k) != v:
            c.fail(f"default main resources.requests.{k} = "
                   f"{(res.get('requests') or {}).get(k)!r}, expected {v!r}")
    preset_dep = by_name(rendered["preset"], "Deployment", "n8n-test")
    preset_limits = container_resources(preset_dep or {}).get("limits") or {}
    if preset_limits.get("cpu") != "2" or preset_limits.get("memory") != "1Gi":
        c.fail(f"t1.medium preset limits = {preset_limits!r}, expected cpu '2' / memory '1Gi'")

    # h) wildcard cert: keep the tls section (HTTP->HTTPS redirect) but drop
    #    secretName and all cert-manager annotations.
    ing = next((d for d in rendered["wildcard"] if d.get("kind") == "Ingress"), None)
    if ing is None:
        c.fail("wildcard case: no Ingress rendered")
    else:
        tls = (ing.get("spec") or {}).get("tls") or []
        if not tls or not tls[0].get("hosts"):
            c.fail("wildcard case: spec.tls must still be present with hosts")
        if tls and tls[0].get("secretName"):
            c.fail("wildcard case: spec.tls[0].secretName must be omitted")
        anns = (ing.get("metadata") or {}).get("annotations") or {}
        if any(k.startswith("cert-manager.io") or k.startswith("acme.cert-manager.io")
               for k in anns):
            c.fail(f"wildcard case: cert-manager annotations must be omitted (got {sorted(anns)!r})")
    # i) external sandbox mode: the Cozystack VM (deploy/sandbox-vm) runs the
    #    sandbox API, so the chart must render NO in-cluster sandbox objects and
    #    wire n8n to the external URL/key with plain env values.
    ext = rendered["external"]
    if any("sandbox" in (d.get("metadata", {}).get("name") or "") for d in ext):
        c.fail("external mode must not render any sandbox-* object")
    ext_env = main_env(ext)
    ext_expected = {
        "N8N_INSTANCE_AI_SANDBOX_ENABLED": "true",
        "N8N_INSTANCE_AI_SANDBOX_PROVIDER": "n8n-sandbox",
        "N8N_SANDBOX_SERVICE_URL": "http://10.244.1.50:8080",
        "N8N_SANDBOX_SERVICE_API_KEY": "test-key-123",
    }
    for name, value in ext_expected.items():
        if name not in ext_env:
            c.fail(f"external mode: n8n main is missing {name}")
        elif ext_env[name].get("value") != value:
            c.fail(f"external mode: {name} = {ext_env[name].get('value')!r}, expected {value!r}")
    if (ext_env.get("N8N_SANDBOX_SERVICE_API_KEY") or {}).get("valueFrom"):
        c.fail("external mode: API key must be a plain value, not a secretKeyRef")
    if by_name(ext, "Service", "n8n-test-search") is None:
        c.fail("external mode: search must still render when enabled")
    if raw_contains(ext, "N8N_RUNNERS") or raw_contains(ext, "n8n-test-broker"):
        c.fail("external render still contains task-runner / broker references")
    # j) explicit sysbox opt-in still renders the RuntimeClass + node selector
    sysbox = rendered["sysbox"]
    sysbox_sts = by_name(sysbox, "StatefulSet", "n8n-test-sandbox-runner")
    if sysbox_sts is None:
        c.fail("sysbox opt-in: runner StatefulSet missing")
    else:
        ssp = sysbox_sts["spec"]["template"]["spec"]
        if ssp.get("runtimeClassName") != "sysbox-runc":
            c.fail("sysbox opt-in: runtimeClassName != sysbox-runc")
        if (ssp.get("nodeSelector") or {}).get("sysbox-install") != "yes":
            c.fail("sysbox opt-in: nodeSelector sysbox-install=yes missing")
        if (ssp["containers"][0].get("securityContext") or {}).get("privileged"):
            c.fail("sysbox opt-in: runner must not be privileged")
    c.ok("render matrix: 8/20/11/23/23/8/8/11/20 docs, sandbox service objects, "
         "external mode, sysbox opt-in, n8n env wiring, HTTPRoute switch, "
         "selector contract, preset matrix, wildcard TLS")

# --------------------------------------------------------------------------
# 9. RD chart render
# --------------------------------------------------------------------------
def check_rd_render(c: Check):
    proc = helm(["template", "test", str(RD_CHART)])
    if proc.returncode != 0:
        c.fail(f"helm template packages/system/n8n-rd failed (rc={proc.returncode})\n"
               f"{proc.stdout}{proc.stderr}")
        return
    try:
        docs = [d for d in yaml.safe_load_all(proc.stdout) if d]
    except yaml.YAMLError as exc:
        c.fail(f"RD render output not parseable: {exc}")
        return
    ads = [d for d in docs if d.get("kind") == "ApplicationDefinition"]
    if len(ads) != 1:
        c.fail(f"RD render must contain exactly one ApplicationDefinition, got {len(ads)}")
        return
    ad = ads[0]
    if ad.get("metadata", {}).get("name") != "n8n":
        c.fail(f"rendered AD metadata.name = {ad.get('metadata', {}).get('name')!r}, expected 'n8n'")
    if (ad.get("spec", {}).get("application") or {}).get("kind") != "N8N":
        c.fail("rendered AD spec.application.kind != 'N8N'")
    c.ok("RD chart renders 1 ApplicationDefinition (n8n / N8N)")


# --------------------------------------------------------------------------
# 10. gen-appdef --check
# --------------------------------------------------------------------------
def check_gen_appdef(c: Check):
    proc = subprocess.run([sys.executable, "hack/gen-appdef.py", "--check"],
                          capture_output=True, text=True, cwd=REPO)
    if proc.returncode != 0:
        c.fail(f"hack/gen-appdef.py --check failed (rc={proc.returncode})\n"
               f"{proc.stdout}{proc.stderr}")
        return
    c.ok("hack/gen-appdef.py --check up to date")


# --------------------------------------------------------------------------
# 11. test specs parse
# --------------------------------------------------------------------------
def check_test_specs(c: Check):
    specs = sorted((APPS_CHART / "tests").glob("*_test.yaml"))
    if not specs:
        c.fail("no packages/apps/n8n/tests/*_test.yaml specs found")
        return
    for f in specs:
        try:
            list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            c.fail(f"{f.relative_to(REPO)}: does not parse: {exc}")
            return
    c.ok(f"{len(specs)} helm-unittest specs parse "
         f"({', '.join(f.name for f in specs)})")


def main() -> int:
    checks = [
        ("packagesource", check_packagesource),
        ("artifact-naming", check_artifact_naming),
        ("strict-yaml", check_strict_yaml),
        ("appdef", check_appdef),
        ("openapi-schema", check_openapi_schema),
        ("values-schema", check_values_schema),
        ("helm-lint", check_helm_lint),
        ("render-matrix", check_render_matrix),
        ("rd-render", check_rd_render),
        ("gen-appdef", check_gen_appdef),
        ("test-specs", check_test_specs),
    ]
    for name, fn in checks:
        run_check(name, fn)
    print(f"RESULT: {_checks} checks, {_failures} failures")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
