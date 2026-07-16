""" Parse a pipeline.yml manifest (spec) or custon yml and produce validation & build outputs

usage: 
    python parse_manifest.py pipeline.yml

"""
from __future__ import annotations

import os
import argparse 
import json
import yaml
import sys
from pathlib import Path
from typing import Any

_MANIFEST_CANDIDATES  = ("pipeline.yaml", "pipeline.yml")


def _load_registry_config(manifest_path: Path | None) -> dict[str, dict[str, Any]]:
    """Load registry configuration from the workflow repository's shared .github/config/registries.yml."""
    if manifest_path is None:
        return {}

    search_roots: list[Path] = []

    script_root = Path(__file__).resolve().parents[3]
    if script_root.exists():
        search_roots.append(script_root)

    current = manifest_path.parent
    while current != current.parent:
        if current not in search_roots:
            search_roots.append(current)
        current = current.parent

    for root in search_roots:
        registry_file = root / ".github" / "config" / "registries.yml"
        if registry_file.is_file():
            with open(registry_file, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            registries = data.get("registries", {})
            if isinstance(registries, dict):
                return registries

    return {}


def _normalize_entry(entry: dict, registry_config: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Strip 'type' while preserving other manifest key names and enrich docker builds with registry metadata."""
    nomalized = {k: v for k,v in entry.items() if k != "type"}
    if entry.get("type") == "docker":
        path = entry.get("path", ".")
        nomalized.setdefault("context", path)
        nomalized.setdefault("dockerfile", f"{path}/Dockerfile")

        registry_name = entry.get("registry")
        if registry_name:
            registry_def = (registry_config or {}).get(registry_name, {})
            if not isinstance(registry_def, dict):
                raise ValueError(f"Unknown registry '{registry_name}'")
            nomalized["registry"] = registry_name
            nomalized["registry-type"] = registry_def.get("type", "")
            nomalized["registry-endpoint"] = registry_def.get("endpoint", "")
            nomalized["registry-auth-method"] = (registry_def.get("auth") or {}).get("method", "")
            nomalized["registry-auth"] = registry_def.get("auth", {})
            nomalized.setdefault("repository", entry.get("repository", ""))
        else:
            nomalized.setdefault("registry", "")
            nomalized.setdefault("registry-type", "")
            nomalized.setdefault("registry-endpoint", "")
            nomalized.setdefault("registry-auth-method", "")
            nomalized.setdefault("registry-auth", {})
            nomalized.setdefault("repository", entry.get("repository", ""))
    return nomalized


def _resolve_manifest(manifest_path: str | None) -> Path | None:
    """ Internal helper function "_" Resolve manifest path (pipeline.yml), auto-discover if not provided
    Args: [not required b/c default value set] manifest_path: Path to manifest file. (defaults to pipeline.yml in dir)
    Returns: A resolved path
    Raises: 
        ValueError: if both pipeline.yml & pipeline.yaml
        FileNotFoundError: if path dsnt exist - given or derived
    """
    if manifest_path:
        path = Path(manifest_path)
        if not path.is_file():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
        return path
    
    found_candidate = [Path(c) for c in _MANIFEST_CANDIDATES if Path(c).is_file()]
    if len(found_candidate) > 1:
        raise ValueError(
            f"Multiple pipelines auto-detected pipeline.yaml & pipeline.yml"
            f"Please remove one"
        )
    return found_candidate[0] if found_candidate else None


def _build_id_lookup(manifest: dict) -> dict[str, dict]:
    """Return a mapping of build ``id`` to raw manifest entry
       single build w/o explicit ``id`` is auto-assigned ``"default"``.
       Multiple builds must declare a unique ``id``
    """
    builds: list = manifest.get("build", [])
    if not isinstance(builds, list):
        return {}
    
    lookup: dict[str, dict] = {}
    for idx, entry in enumerate(builds):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in {"docker", "pack-cli"}:
            continue
        build_id = entry.setdefault("id", "default")
        if build_id in lookup:
            raise ValueError(f"build[{idx}] duplicate id '{build_id}'")
        lookup[build_id] = entry
    print("build_id_lookup", lookup)
    return lookup


def parse_manifest( 
    manifest_path: str | None = None,
    *,
    environment: str = "",
    target: str = "",                
) -> dict[str, Any]:
    """ Parse pipeline manifest and return planned output
    
    Args: [not required b/c default value set]
        manifest_path: Path to manifest file. (defaults to pipeline.yml in dir)
        environment: environment for deploy
        target: target for deploy
        
    Returns:
        A dict with matices for build & validation (list of validations & builds needed)
        + presence flags
        
    Raises:
        FileNotFoundError: If an explicit manifest path doesnt exist
        ValueError: if both pipeline.yml & pipeline.yaml found or schema validation fail
    
    """
    path = _resolve_manifest(manifest_path)
    
    # no manifest empty matrix and all flags False
    if path is None:
        return {
            # validates (flag + matrix)
            "has-validate-npm": False,
            "validate-npm-matrix": [],
            "has-validate-python": False,
            "validate-python-matrix": [],
            
            # builds (flag + matrix)
            "has-build-pack-cli": False,
            "build-pack-cli-matrix": [],
            "has-build-docker": False,
            "build-docker-matrix": [],
            
            # deploys (flag + matrix)
            "has-deploy-cloudrun": False,
            "deploy-cloudrun-matrix": [],
            "has-deploy-azure-ca": False,
            "deploy-azure-ca-matrix": [],
        }
    
    with open(path, encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
        
    if not isinstance(manifest, dict):
        raise ValueErro("Manifest must be YAML mapping")
    
    registry_config = _load_registry_config(path)

    # validate matices
    validate_python_matrix = _validate_matrix(manifest, "python-pytest")
    validate_npm_matrix = _validate_matrix(manifest, "npm-jest")    
    
    # build lookup
    build_lookup = _build_id_lookup(manifest)
    
    # build matrices
    build_pack_cli_matrix = _build_matrix(manifest, "pack-cli")
    build_docker_matrix = _build_matrix(manifest, "docker", registry_config)
    
    # deploy matrices
    deploy_cloudrun_matrix = _deploy_matrix(manifest, build_lookup, "cloudrun")
    deploy_azure_ca_matrix = _deploy_matrix(manifest, build_lookup, "azure-ca")
    
    # ---- Filter by Environment ----
    # if environment exists & not "all"
    if environment and environment != "all":
        deploy_cloudrun_matrix = [
            d for d in deploy_cloudrun_matrix if d["target"] == target
        ]
        deploy_azure_ca_matrix = [
            d for d in deploy_azure_ca_matrix if d["target"] == target
        ]
    
    # --- Filter by Target ---
    # Target links to build id (only build targets we want to deploy)
    if target and target != "all":
        deploy_cloudrun_matrix = [
            d for d in deploy_cloudrun_matrix
            if not d.get("environment") or d.get("environment") == environment
        ]
        deploy_azure_ca_matrix = [
            d for d in deploy_azure_ca_matrix
            if not d.get("environment") or d.get("environment") == environment
        ]
        deployed_targets = {
            d["target"] for d in deploy_cloudrun_matrix + deploy_azure_ca_matrix
        }
        build_pack_cli_matrix = [
            b for b in build_pack_cli_matrix
            if b["id"] == target and b["id"] in deployed_targets
        ]
        build_docker_matrix = [
            b for b in build_docker_matrix
        ]
        print(
            f"target filter '{target}': "
            f"{len(build_pack_cli_matrix)} pack-cli build(s), "
            f"{len(build_docker_matrix)} docker build(s), "
            f"{len(deploy_cloudrun_matrix)} cloudrun deploy(s), "
            f"{len(deploy_azure_ca_matrix)} azure container apps deploy(s), ",
            file=sys.stderr
        )
    
    return {
        # validates (flag + matrix)
        "has-validate-npm": len(validate_npm_matrix) > 0,
        "validate-npm-matrix": validate_npm_matrix,
        "has-validate-python": len(validate_python_matrix) > 0,
        "validate-python-matrix": validate_python_matrix,
            
        # builds (flag + matrix)
        "has-build-pack-cli": len(build_pack_cli_matrix) > 0,
        "build-pack-cli-matrix": build_pack_cli_matrix,
        "has-build-docker": len(build_docker_matrix) > 0,
        "build-docker-matrix": build_docker_matrix,
        
        # deploys (flag + matrix)
        "has-deploy-cloudrun": len(deploy_cloudrun_matrix) > 0,
        "deploy-cloudrun-matrix": deploy_cloudrun_matrix,
        "has-deploy-azure-ca": len(deploy_azure_ca_matrix) > 0,
        "deploy-azure-ca-matrix": deploy_azure_ca_matrix
    }

def _validate_matrix(
    manifest: dict,
    validate_type: str
) -> list[dict[str, Any]]:
    """ Create validate matrix for the different validate types (python, npm) 
    Args:  
        manifest - dictionary containing the pipeline manifest
        validate_type - type field of the validation object (python-pytest, npm-jist, etc)
    Return: Matrix of the validate type
    Raises:
        ValueError: if object/children invalid format or "validate" > "type" field missing
    """
    validates: list[dict] = manifest.get("validate", [])
    if not isinstance(validates, list):
        raise ValueError("'validate' must be a list")
    
    matrix: list[dict[str, Any]] = []
    for idx, entry in enumerate(validates): 
        if not isinstance(entry, dict): 
            raise ValueError(f"validate[{idx}] must be a mapping")
        if not entry.get("type"): 
            raise ValueError(f"validate[{idx}] missing required 'type' field")
        if entry["type"] == validate_type: 
            matrix.append(_normalize_entry(entry))
    return matrix
   
def _build_matrix(
    manifest: dict,
    build_type: str,
    registry_config: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """ Create build matrix for the different build types (docker, pack-cli) 
    Args:  
        manifest - dictionary containing the pipeline manifest
        build_type - type field of the build object (docker, pack-cli, etc)
    Return: Matrix of the build type
    Raises:
        ValueError: if object/children invalid format or "build" > "type" field missing
    """
    builds: list[dict] = manifest.get("build", [])
    if not isinstance(builds, list):
        raise ValueError("'build' must be a list")
    
    matrix: list[dict[str, Any]] = []
    for idx, entry in enumerate(builds):
        if not isinstance(entry, dict): 
            raise ValueError(f"build[{idx}] must be a mapping")
        if not entry.get("type"): 
            raise ValueError(f"build[{idx}] missing required 'type' field")
        if entry["type"] == build_type: 
            matrix.append(_normalize_entry(entry, registry_config))
    return matrix

def _deploy_matrix(
    manifest: dict,
    build_lookup: dict[str, dict],
    deploy_type: str
) -> list[dict[str,any]]:
    """ Create Deploy matrix for the different deploy types (cloudrun, azure-ca)
    Args:  
        manifest - dictionary containing the pipeline manifest
        build_lookup - contains build information (build id, type etc)
        deploy_type - type field of the deploy object (cloudrun, azure-ca)
    Return: Matrix of the deploys
    Raises:
        ValueError: if object/children invalid format or "deploy" > "type" field missing
    """
    deploys: list[dict] = manifest.get("deploy", [])  
    if not isinstance(deploys, list):
        raise ValueError("'deploy' must be a list") 
    
    matrix: list[dict[str, Any]] = []
    for idx, entry in enumerate(deploys):
        if not isinstance(entry, dict): 
            raise ValueError(f"deploy[{idx}] must be a mapping")
        if not entry.get("type"): 
            raise ValueError(f"deploy[{idx}] missing required 'type' field")
        if entry["type"] == deploy_type: 
            continue
        
        target = entry.get("target")
        
        if target is None and "image" not in entry:
            target = "default"
            if target not in build_lookup:
                raise ValueError(
                    f"deploy[{idx}] has no 'target' and no 'image'; "
                    "expected a build with id 'default'"
                )
        elif target is not None and "image" in entry:
            raise ValueError(
                f"deploy[{idx}] has both 'target' and 'image'; "
                "Omit target when providing an image or vice versa (mutually exclusive)"
            )
            
        if target not in build_lookup and target  is not None:
            raise ValueError(
                f"deploy[{idx}] target '{target}' does not match "
                "any build id"
            )
        
        normalized = _normalize_entry(entry)
        normalized["target"] = target or ""
        matrix.append(normalized)
    return matrix
               
            
def _write_github_output(outputs: dict[str, Any]) -> None:
    """ Write Plan output to $GITHUB_OUTPUT
    Args: outputs object in dictionary format
    Return: None - but prints output to github actions in output format (f"{key}={value_str}\n)
    """
    output_file = os.environ.get("GITHUB_OUTPUT","")
    if not output_file:
        return
    
    with open(output_file, "a", encoding="utf-8") as fh:
        # validates (flag + matrix)
        fh.write(
            "has-validate-npm="
            f"{'true' if outputs['has-validate-npm'] else 'false'}\n"
        )
        fh.write(
            "validate-npm-matrix="
            f"{json.dumps(outputs['validate-npm-matrix'])}\n"
        )
        fh.write(
            "has-validate-python="
            f"{'true' if outputs['has-validate-python'] else 'false'}\n"
        )
        fh.write(
            "validate-python-matrix="
            f"{json.dumps(outputs['validate-python-matrix'])}\n"
        )
        
        # builds (flag + matrix)
        fh.write(
            "has-build-pack-cli="
            f"{'true' if outputs['has-build-pack-cli'] else 'false'}\n"
        )
        fh.write(
            "build-pack-cli-matrix="
            f"{json.dumps(outputs['build-pack-cli-matrix'])}\n"
        )
        fh.write(
            "has-build-docker="
            f"{'true' if outputs.get('has-build-docker') else 'false'}\n"
        )
        fh.write(
            "build-docker-matrix="
            f"{json.dumps(outputs.get('build-docker-matrix', []))}\n"
        )
        
        # deploy (flag + matrix)
        fh.write(
            "has-deploy-cloudrun="
            f"{'true' if outputs['has-deploy-cloudrun'] else 'false'}\n"
        )
        fh.write(
            "deploy-cloudrun-matrix="
            f"{json.dumps(outputs['deploy-cloudrun-matrix'])}\n"
        )
        fh.write(
            "has-deploy-azure-ca="
            f"{'true' if outputs.get('has-deploy-azure-ca') else 'false'}\n"
        )
        fh.write(
            "deploy-azure-ca-matrix="
            f"{json.dumps(outputs.get('deploy-azure-ca-matrix', []))}\n"
        )

def _emit_manifest_error(manifest_path: str, message: str) -> None:
    escaped = message.replace("\n", "%0A")
    print(
        f"::error title=Invalid Pipeline Manifest, file={manifest_path}::{escaped}",
        file=sys.stderr,
    )
    print(f"Invalid pipeline manifest '{manifest_path}': {message}", file=sys.stderr)

def main(argv: list[str] | None = None) -> None:
    """ Main function to take cli args (arg vector) and execute parse_manifest
    Args: argument vector of --manifest, --environment,--target (all optional)
    Returns: none
    """
    parser = argparse.ArgumentParser(
        description="Parse pipeline manifest and output github actions plan output"
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="Path to manifest file. Pass empty string (default) to auto discover pipeline.yml/yaml"
    )
    parser.add_argument(
        "--environment",
        default="",
        help="Deployment environment filter (empty for 'all' runs in all environments)"
    )
    parser.add_argument(
        "--target",
        default="",
        help="Build/deploy target filter (empty or 'all' runs everything)"
    )
    args = parser.parse_args(argv)
    
    manifest_path: str | None = args.manifest or None

    try:
        outputs = parse_manifest(
            manifest_path=manifest_path,
            environment=args.environment,
            target=args.target
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        _emit_manifest_error(manifest_path or "(auto-discover)", str(exc))
        raise SystemExit(1) from exc
    
    _write_github_output(outputs)
    
    # Always print json
    json.dump(outputs, sys.stdout, indent=2)
    print()
    
if __name__ == "__main__":
    main()      # This launches script when run from terminal
