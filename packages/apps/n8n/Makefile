export NAME=n8n
export NAMESPACE=cozy-system

include ../../../hack/package.mk

# NOTE: values.schema.json and README.md are hand-authored in this chart.
# This is an external/tapped Marketplace app (not a codegen'd appdef), so
# `make generate` is optional and only meaningful inside the Cozystack
# source tree where hack/ and api/ exist. Standalone users work directly
# on the chart files or via `cozypkg`.

generate:
	cozyvalues-gen -m 'n8n' -v values.yaml -s values.schema.json -r README.md -g ../../../api/apps/v1alpha1/n8n/types.go
	../../../hack/update-crd.sh

test:
	helm unittest .
