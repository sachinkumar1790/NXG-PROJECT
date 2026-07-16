## Python Test Case

#import pytest
#import yaml
from parse_manifest import parse_manifest

def test_parse_manifest_empty_when_no_file_found():
    """
    Test that if no manifest file exists, parse_manifest returns 
    a default schema dictionary with all flags set to False 
    and matrices initialized to empty lists.
    """
    # Act: Pass None to trigger the auto-discovery fallback when no files exist
    outputs = parse_manifest(manifest_path=None)
    
    # Assert: Verify the fallback empty structure returns correctly
    assert outputs["has-validate-npm"] is False
    assert outputs["validate-npm-matrix"] == []
    
    assert outputs["has-validate-python"] is False
    assert outputs["validate-python-matrix"] == []
    
    assert outputs["has-build-pack-cli"] is False
    assert outputs["build-pack-cli-matrix"] == []
    
    assert outputs["has-build-docker"] is False
    assert outputs["build-docker-matrix"] == []
    
    assert outputs["has-deploy-cloudrun"] is False
    assert outputs["deploy-cloudrun-matrix"] == []
    
    assert outputs["has-deploy-azure-ca"] is False
    assert outputs["deploy-azure-ca-matrix"] == []


def test_parse_manifest_resolves_registry_metadata_for_docker_build(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    config_dir = repo_dir / ".github" / "config"
    config_dir.mkdir(parents=True)
    (repo_dir / "pipeline.yml").write_text(
        "build:\n"
        "  - id: api\n"
        "    type: docker\n"
        "    path: node-app-test\n"
        "    registry: test-gar\n"
        "    repository: docker-dev\n",
        encoding="utf-8",
    )
    (config_dir / "registries.yml").write_text(
        "registries:\n"
        "  test-gar:\n"
        "    type: gar\n"
        "    endpoint: uscentral1-docker.pkg.dev\n"
        "    auth:\n"
        "      method: workload-identity\n"
        "      wif_provider: projects/123/locations/us-central1/workloadIdentityPools/test/providers/test-provider\n"
        "      wif_pool_id: projects/123/locations/us-central1/workloadIdentityPools/test\n"
        "      wif_service_account: github-actions-sa\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(repo_dir)

    outputs = parse_manifest(manifest_path=None)

    entry = outputs["build-docker-matrix"][0]
    assert entry["registry"] == "test-gar"
    assert entry["registry-type"] == "gar"
    assert entry["registry-endpoint"] == "uscentral1-docker.pkg.dev"
    assert entry["registry-auth-method"] == "workload-identity"
    assert entry["context"] == "node-app-test"
    assert entry["dockerfile"] == "node-app-test/Dockerfile"


def test_parse_manifest_builds_azure_ca_deploy_matrix(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    config_dir = repo_dir / ".github" / "config"
    config_dir.mkdir(parents=True)
    (repo_dir / "pipeline.yml").write_text(
        "build:\n"
        "  - id: api\n"
        "    type: docker\n"
        "    path: node-app-test\n"
        "    registry: test-acr\n"
        "    repository: docker-dev\n"
        "deploy:\n"
        "  - type: azure-ca\n"
        "    environment: dev\n"
        "    target: api\n"
        "    region: eastus\n"
        "    azure-subscription: sub-123\n"
        "    azure-rg: my-rg\n"
        "    app-name: my-app\n",
        encoding="utf-8",
    )
    (config_dir / "registries.yml").write_text(
        "registries:\n"
        "  test-acr:\n"
        "    type: acr\n"
        "    endpoint: myregistry.azurecr.io\n"
        "    auth:\n"
        "      method: workload-identity\n"
        "      client_id: client-1\n"
        "      tenant_id: tenant-1\n"
        "      subscription_id: sub-1\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(repo_dir)

    outputs = parse_manifest(manifest_path=None)

    assert outputs["has-deploy-azure-ca"] is True
    entry = outputs["deploy-azure-ca-matrix"][0]
    assert entry["target"] == "api"
    assert entry["region"] == "eastus"
    assert entry["azure-subscription"] == "sub-123"
    assert entry["azure-rg"] == "my-rg"
    assert entry["app-name"] == "my-app"
    assert entry["build-registry-endpoint"] == "myregistry.azurecr.io"
    assert entry["build-registry-auth"]["client_id"] == "client-1"


def test_parse_manifest_rejects_unknown_registry(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    config_dir = repo_dir / ".github" / "config"
    config_dir.mkdir(parents=True)
    (repo_dir / "pipeline.yml").write_text(
        "build:\n"
        "  - id: api\n"
        "    type: docker\n"
        "    path: node-app-test\n"
        "    registry: missing-registry\n",
        encoding="utf-8",
    )
    (config_dir / "registries.yml").write_text(
        "registries:\n"
        "  test-gar:\n"
        "    type: gar\n"
        "    endpoint: uscentral1-docker.pkg.dev\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(repo_dir)

    try:
        parse_manifest(manifest_path=None)
    except ValueError as exc:
        assert "missing-registry" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown registry")