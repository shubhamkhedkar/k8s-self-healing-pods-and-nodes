SHELL := /bin/bash
PY ?= python3
CLUSTER ?= self-healing

.PHONY: help lint test validate tf-validate kubeconform rules images kind-up deploy-kind chaos-pods chaos-node kind-down

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

# ---- local verification (never touches a cluster) -------------------------------------------
lint: ## ruff + yamllint
	ruff check app node-healer
	yamllint -c .yamllint.yaml deploy kind .github

test: ## pytest (app + node-healer)
	pytest -q

kubeconform: ## render kustomize overlays and validate against the k8s schemas
	for o in deploy/base deploy/overlays/kind deploy/overlays/eks; do \
	  kustomize build $$o | kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.30.0 ; done
	kustomize build deploy/monitoring | kubeconform -strict -summary \
	  -schema-location default \
	  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

rules: ## promtool check of the Prometheus alert rules
	scripts/check-rules.sh

tf-validate: ## terraform fmt + init(-backend=false) + validate. No AWS credentials, nothing is created.
	cd terraform && terraform fmt -check -recursive && terraform init -backend=false -input=false >/dev/null && terraform validate

validate: lint test kubeconform rules tf-validate ## everything above

# ---- local demo on kind (YOU run these; they create a local docker-based cluster) ----------------
images: ## build the two images
	docker build -t self-heal-demo:dev app
	docker build -t node-healer:dev node-healer

kind-up: images ## create kind cluster + load images + install metrics-server
	kind create cluster --config kind/kind-config.yaml
	kind load docker-image self-heal-demo:dev node-healer:dev --name $(CLUSTER)
	kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
	kubectl -n kube-system patch deploy metrics-server --type=json \
	  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

deploy-kind: ## apply the kind overlay
	kubectl apply -k deploy/overlays/kind
	kubectl -n self-healing rollout status deploy/demo-app --timeout=120s

chaos-pods: ## run the pod-level chaos suite
	chaos/run-all.sh

chaos-node: ## stop kubelet on one worker and watch the recovery
	chaos/node-failure.sh

kind-down: ## delete the kind cluster
	kind delete cluster --name $(CLUSTER)
