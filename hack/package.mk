# Standalone shim for the shared Cozystack package makefile.
#
# Inside the cozystack/cozystack source tree this path (hack/package.mk) is the
# real shared makefile that defines the standard build/install/package targets
# used by every packages/*/Makefile. This external-apps repository keeps the
# same `include ../../../hack/package.mk` lines so the package Makefiles are
# byte-for-byte drop-in mergeable, but cozypkg never invokes make — the OCI
# artifact is built from the chart directories directly. A no-op shim is
# therefore enough to keep `make` from failing for local contributors.
#
# Real work is done by the top-level Makefile targets (verify, lint, template,
# generate, validate, push, tap, add) and by hack/verify.py.

.PHONY: package-mk-shim
package-mk-shim:
	@:
