#!/usr/bin/env python3
"""Generate the ApplicationDefinition for the n8n Marketplace app.

Usage:
    python3 hack/gen-appdef.py                 # regenerate packages/system/n8n-rd/cozyrds/n8n.yaml
    python3 hack/gen-appdef.py --check         # exit 1 if the file is stale (needs regeneration)
    python3 hack/gen-appdef.py --ps-name X     # override the PackageSet name (default: cozy-apps.n8n)

Inputs:
    packages/apps/n8n/values.schema.json      -> minified into spec.application.openAPISchema
    packages/apps/n8n/logos/n8n.svg           -> base64-encoded into spec.dashboard.icon

Output:
    packages/system/n8n-rd/cozyrds/n8n.yaml   (single-line, minified JSON; idempotent)

Why openAPISchema must be byte-identical to values.schema.json:
    The Cozystack Marketplace dashboard renders the install form directly from
    spec.application.openAPISchema with its SchemaForm component. If that schema
    drifted from packages/apps/n8n/values.schema.json, the form would validate
    values the chart rejects (or hide values it accepts). Embedding the exact
    minified schema keeps the UI contract and the Helm chart contract in sync by
    construction -- the two can never diverge because this script derives one
    from the other on every build. It must include every toggle (e.g.
    sandbox.enabled, search.enabled) so the install form exposes them.

Why the icon is raw base64 (not a data URI):
    Cozystack convention stores the marketplace icon as plain base64 in
    spec.dashboard.icon; the dashboard frontend prepends the image MIME type
    itself. A "data:image/svg+xml;base64,..." prefix would be stored as part of
    the payload and break rendering, so we emit base64 of the SVG only.

Notes on templating:
    The literal Go-templating placeholders ({{ .name }}) inside resourceNames
    are intentional: templates/cozyrd.yaml emits each cozyrds/ file verbatim via
    $.Files.Get, and cozypkg validate skips strict decoding of documents that
    contain "{{". Helm resolves them when the ApplicationDefinition is applied.
"""
import argparse
import base64
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "packages" / "apps" / "n8n" / "values.schema.json"
ICON_PATH = REPO_ROOT / "packages" / "apps" / "n8n" / "logos" / "n8n.svg"
OUTPUT_PATH = REPO_ROOT / "packages" / "system" / "n8n-rd" / "cozyrds" / "n8n.yaml"

# Sentinel tokens are replaced with .replace() (NOT str.format) because the
# minified JSON schema is full of braces that str.format would choke on.
TEMPLATE = """apiVersion: cozystack.io/v1alpha1
kind: ApplicationDefinition
metadata:
  name: n8n
spec:
  application:
    kind: N8N
    plural: n8ns
    singular: n8n
    openAPISchema: |-
      __OPENAPI_SCHEMA__
  release:
    prefix: n8n-
    labels:
      sharding.fluxcd.io/key: tenants
    chartRef:
      kind: ExternalArtifact
      name: __ARTIFACT_NAME__
      namespace: cozy-system
  dashboard:
    description: Workflow automation with optional Code Sandbox and private SearXNG search
    icon: __ICON_BASE64__
    category: PaaS
    singular: N8N
    plural: N8N
    tags:
      - workflow-automation
      - automation
      - ai
      - low-code
    tabs:
      - workloads
      - ingresses
      - services
      - secrets
      - yaml
    keysOrder:
      - ["spec", "host"]
      - ["spec", "size"]
      - ["spec", "storageClass"]
      - ["spec", "resourcesPreset"]
      - ["spec", "resources"]
      - ["spec", "timezone"]
      - ["spec", "image"]
      - ["spec", "communityPackages"]
      - ["spec", "sandbox"]
      - ["spec", "sandbox", "enabled"]
      - ["spec", "search"]
      - ["spec", "search", "enabled"]
  secrets:
    exclude: []
    include:
      - resourceNames: ["n8n-{{ .name }}-credentials", "n8n-{{ .name }}-search-config", "n8n-{{ .name }}-sandbox-auth", "n8n-{{ .name }}-sandbox-ca", "n8n-{{ .name }}-sandbox-tls-api-registration", "n8n-{{ .name }}-sandbox-tls-api-control-client", "n8n-{{ .name }}-sandbox-tls-runner-registration", "n8n-{{ .name }}-sandbox-tls-runner-control-server"]
      - matchLabels:
          internal.cozystack.io/tenant-ca: "true"
  services:
    exclude: []
    include:
      - resourceNames: ["n8n-{{ .name }}", "n8n-{{ .name }}-sandbox", "n8n-{{ .name }}-sandbox-runner", "n8n-{{ .name }}-search"]
  ingresses:
    exclude: []
    include:
      # The classic Ingress is named <release>-ingress. The Gateway API
      # HTTPRoute is named <release> and is not handled by the lineage
      # webhook, so listing it here is inert but future-proof.
      - resourceNames: ["n8n-{{ .name }}-ingress", "n8n-{{ .name }}"]
"""


def minified_schema() -> str:
    """Read values.schema.json and return it minified (compact separators)."""
    import json

    return json.dumps(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
                      separators=(",", ":"), ensure_ascii=False)


def icon_b64() -> str:
    """Read the SVG logo and return single-line base64 (no data: prefix)."""
    return base64.b64encode(ICON_PATH.read_bytes()).decode("ascii")


def artifact_name(ps_name: str) -> str:
    """cozy-apps.n8n -> cozy-apps-n8n-default-n8n"""
    return ps_name.replace(".", "-") + "-default-n8n"


def generate(ps_name: str) -> str:
    return (TEMPLATE
            .replace("__OPENAPI_SCHEMA__", minified_schema())
            .replace("__ICON_BASE64__", icon_b64())
            .replace("__ARTIFACT_NAME__", artifact_name(ps_name)))


def self_validate(content: str, ps_name: str) -> None:
    """Parse the generated YAML and assert contract invariants. Raises AssertionError."""
    import json

    try:
        import yaml
    except ImportError:
        yaml = None

    doc = None
    if yaml is not None:
        doc = yaml.safe_load(content)
        assert doc["apiVersion"] == "cozystack.io/v1alpha1", "apiVersion mismatch"
        assert doc["kind"] == "ApplicationDefinition", "kind mismatch"
        assert doc["metadata"]["name"] == "n8n", "metadata.name mismatch"

        app = doc["spec"]["application"]
        schema = json.loads(app["openAPISchema"])
        assert schema == json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), \
            "openAPISchema does not equal values.schema.json"
        assert "sandbox" in schema["properties"], "sandbox toggle missing from schema"
        assert "enabled" in schema["properties"]["sandbox"]["properties"], \
            "sandbox.enabled toggle missing from schema"
        assert "search" in schema["properties"], "search toggle missing from schema"
        assert "enabled" in schema["properties"]["search"]["properties"], \
            "search.enabled toggle missing from schema"

        icon = base64.b64decode(doc["spec"]["dashboard"]["icon"])
        assert icon == ICON_PATH.read_bytes(), "icon does not decode to the SVG"
        assert doc["spec"]["dashboard"]["category"] == "PaaS", "category mismatch"

        release = doc["spec"]["release"]
        assert release["chartRef"]["name"] == artifact_name(ps_name), "chartRef.name mismatch"
        assert release["chartRef"]["kind"] == "ExternalArtifact", "chartRef.kind mismatch"
        assert release["chartRef"]["namespace"] == "cozy-system", "chartRef.namespace mismatch"
        assert release["prefix"] == "n8n-", "release prefix mismatch"

        selectors = doc["spec"]
        ing = (selectors.get("ingresses") or {}).get("include") or []
        ing_names = [n for sel in ing for n in (sel.get("resourceNames") or [])]
        assert "n8n-{{ .name }}-ingress" in ing_names, \
            "spec.ingresses.include is missing the Ingress name"
        sec = (selectors.get("secrets") or {}).get("include") or []
        sec_names = [n for sel in sec for n in (sel.get("resourceNames") or [])]
        assert "n8n-{{ .name }}-search-config" in sec_names, \
            "spec.secrets.include is missing the SearXNG config Secret"
        assert "n8n-{{ .name }}-sandbox-auth" in sec_names, \
            "spec.secrets.include is missing the sandbox auth Secret"
        svc = (selectors.get("services") or {}).get("include") or []
        svc_names = [n for sel in svc for n in (sel.get("resourceNames") or [])]
        for name in ("n8n-{{ .name }}-sandbox", "n8n-{{ .name }}-sandbox-runner"):
            assert name in svc_names, \
                f"spec.services.include is missing the sandbox Service {name}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate packages/system/n8n-rd/cozyrds/n8n.yaml (ApplicationDefinition).")
    parser.add_argument("--ps-name", default="cozy-apps.n8n",
                        help="PackageSet name used to compute the chartRef artifact name "
                             "(default: cozy-apps.n8n)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the generated file is stale")
    args = parser.parse_args()

    content = generate(args.ps_name)

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"STALE: {OUTPUT_PATH} does not exist. "
                  f"Run: python3 hack/gen-appdef.py")
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if current != content:
            print(f"STALE: {OUTPUT_PATH} is out of date with values.schema.json / n8n.svg "
                  f"(or --ps-name differs). "
                  f"Run: git diff {OUTPUT_PATH.relative_to(REPO_ROOT)} then "
                  f"python3 hack/gen-appdef.py")
            return 1
        print(f"OK: {OUTPUT_PATH.relative_to(REPO_ROOT)} is up to date")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    self_validate(content, args.ps_name)
    print(f"OK: wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
          f"(schema minified, icon base64-encoded, chartRef={artifact_name(args.ps_name)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
