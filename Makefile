# Convenience targets for the standalone n8n External-Apps repository.
#
# `verify` needs only helm + python3 (PyYAML/jsonschema). The `cozypkg-*`
# targets need the Cozystack 1.7 cozypkg CLI and an admin kubeconfig.

SHELL := /bin/sh

REGISTRY ?= git.klugeshaus.eu/key/n8n
TAG      ?= v1.0.0
SOURCE   ?= https://git.klugeshaus.eu/AIStack/n8n-cozy.git
REF      := $(REGISTRY):$(TAG)

.PHONY: help verify lint template tests generate check-generate validate \
        push tap add list status clean

help:
	@printf '%s\n' \
	  'verify          run the full local validation gate (hack/verify.sh)' \
	  'lint            helm lint both charts' \
	  'template        render the app chart with default values' \
	  'generate        regenerate the ApplicationDefinition from the schema' \
	  'check-generate  fail if the ApplicationDefinition is stale' \
	  'validate        cozypkg validate . --helm-lint' \
	  'push            push the OCI artifact (REGISTRY/TAG/SOURCE)' \
	  'tap             tap/connect the repository (installs nothing)' \
	  'add             install the Package non-interactively from deploy/package.yaml' \
	  'list            list available PackageSources' \
	  'status          show ApplicationDefinition / Package / PackageSource'

verify:
	./hack/verify.sh

lint:
	helm lint packages/apps/n8n
	helm lint packages/system/n8n-rd

template:
	helm template n8n-test packages/apps/n8n --namespace tenant-test

tests:
	helm unittest packages/apps/n8n

generate:
	python3 hack/gen-appdef.py

check-generate:
	python3 hack/gen-appdef.py --check

validate:
	cozypkg validate . --helm-lint

push:
	cozypkg push oci://$(REF) --path . --source $(SOURCE) --revision $(TAG) --helm-lint --reproducible

tap:
	cozypkg tap oci://$(REF)

add:
	cozypkg add -f deploy/package.yaml

list:
	cozypkg list

status:
	kubectl get applicationdefinition n8n
	kubectl get packagesource cozy-apps.n8n
	kubectl get package cozy-apps.n8n

clean:
	@rm -rf .pytest_cache __pycache__ hack/__pycache__
	@find . -name '*.pyc' -delete
